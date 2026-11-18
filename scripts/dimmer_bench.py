"""Automatic checks for the lamp dimmer bench procedure (docs/hardware_v1/dimmer_bench.md).

Usage:
    uv run python3 scripts/dimmer_bench.py                    # Test 0, no mains, no lamp
    uv run python3 scripts/dimmer_bench.py --auto-only        # skip the steps that need a human
    uv run python3 scripts/dimmer_bench.py --only trip        # one check by name
    uv run python3 scripts/dimmer_bench.py --mains            # Test 2 checks (asks to confirm)
    uv run python3 scripts/dimmer_bench.py --list

This script has never run on the real bench. It was tested only with a fake source.

The lamp is always left off. Every check runs inside try/finally that sends OFF,
Ctrl-C and SIGTERM end with OFF, and every lamp-on command has a deadline
(`max_on_s`). Without --mains the script refuses to command an angle when the
status says mains is present.

Exit code: 0 all checks passed (or skipped), 1 a check failed, 2 a check was
inconclusive and none failed, 3 refused to start, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mpp_sdk.io.dimmer import DimmerStatus

PASS, FAIL, INCONCLUSIVE, SKIP = "PASS", "FAIL", "INCONCLUSIVE", "SKIP"

# Values that mirror firmware/dimmer-link and the Pico (see docs/hardware_v1/dimmer_link.md).
EXPOSURE_MAX_S = 120.0
EXPOSURE_RESUME_S = 60.0
PICO_HOST_TIMEOUT_S = 3.0
LINK_LOSS_S = 2.0
# The Pico sends a cached dimmer status, up to about 1 s old, plus poll jitter.
STATUS_LAG_S = 1.5
OFF_DEG = 180.0
# The firmware limits the firing delay: about 25 to 153 degrees at 50 Hz.
APPLIED_MIN_DEG = 24.0
APPLIED_MAX_DEG = 154.0
CONFIRM_TEXT = "mains on, small lamp, supervised"
# Each on-command lasts at most this long and is renewed by the check that needs more.
ON_WINDOW_S = 30.0
RENEW_S = 10.0

Read = tuple[float, DimmerStatus | None]


@dataclass
class Verdict:
    status: str
    detail: str


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    reads: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure judgement functions. Input: reads as (time_s, DimmerStatus | None).
# ---------------------------------------------------------------------------


def _valid(reads: Sequence[Read]) -> list[tuple[float, DimmerStatus]]:
    return [(t, s) for t, s in reads if s is not None]


def _near(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


def judge_link(reads: Sequence[Read]) -> Verdict:
    """Idle link: valid replies, link up, no mains, not locked."""
    good = _valid(reads)
    if len(reads) < 3 or len(good) != len(reads):
        return Verdict(FAIL, f"{len(reads) - len(good)} of {len(reads)} reads had no valid reply")
    if not all(s.link_ok for _, s in good):
        return Verdict(FAIL, "link_ok was false")
    if any(s.mains or s.locked for _, s in good):
        return Verdict(FAIL, "mains or locked is true: this is not a no-mains setup")
    return Verdict(PASS, f"{len(good)} reads: link_ok true, mains and locked false")


def judge_alpha_readback(
    reads: Sequence[Read], expected_deg: float, *, mains: bool = False
) -> Verdict:
    good = _valid(reads)
    if not good or len(good) != len(reads):
        return Verdict(FAIL, "a read had no valid reply")
    if not all(s.link_ok for _, s in good):
        return Verdict(FAIL, "link_ok was false")
    bad = [s.set_alpha_deg for _, s in good if not _near(s.set_alpha_deg, expected_deg)]
    if bad:
        return Verdict(FAIL, f"set alpha {bad[0]:.2f} deg, expected {expected_deg:.2f} deg")
    if not mains and any(s.applied_alpha_deg is not None for _, s in good):
        return Verdict(FAIL, "applied alpha is not None without mains")
    return Verdict(PASS, f"set alpha {expected_deg:.2f} deg read back")


def judge_stable(reads: Sequence[Read], max_age_s: float = STATUS_LAG_S) -> Verdict:
    """The link stays up. The Pi cannot read BAD_FRAMES, so this is the nearest check."""
    good = _valid(reads)
    if len(reads) < 5:
        return Verdict(FAIL, "too few reads")
    if len(good) != len(reads):
        return Verdict(FAIL, f"{len(reads) - len(good)} reads had no valid reply")
    if not all(s.link_ok for _, s in good):
        return Verdict(FAIL, "link_ok dropped")
    oldest = max(s.age_s for _, s in good)
    if oldest > max_age_s:
        return Verdict(FAIL, f"status age reached {oldest:.1f} s (limit {max_age_s:.1f} s)")
    return Verdict(PASS, f"{len(good)} reads, link_ok always true, oldest status {oldest:.1f} s")


def judge_pico_timeout(
    reads: Sequence[Read], t_event: float, limit_s: float = PICO_HOST_TIMEOUT_S + STATUS_LAG_S
) -> Verdict:
    """After the host stops, the Pico must hold alpha 180 within the limit and keep it."""
    after = [(t, s) for t, s in _valid(reads) if t >= t_event]
    first = next((t for t, s in after if s.set_alpha_deg >= OFF_DEG - 0.01), None)
    if first is None:
        return Verdict(FAIL, "set alpha never returned to 180 deg")
    elapsed = first - t_event
    if elapsed > limit_s:
        return Verdict(FAIL, f"set alpha reached 180 deg after {elapsed:.1f} s (limit {limit_s} s)")
    if any(s.set_alpha_deg < OFF_DEG - 0.01 for t, s in after if t > first):
        return Verdict(FAIL, "set alpha left 180 deg again")
    return Verdict(PASS, f"set alpha was 180 deg {elapsed:.1f} s after the event")


def judge_link_loss(reads: Sequence[Read], t_event: float, limit_s: float = 4.0) -> Verdict:
    first = next((t for t, s in _valid(reads) if t >= t_event and not s.link_ok), None)
    if first is None:
        return Verdict(FAIL, "link_ok never went false")
    elapsed = first - t_event
    if elapsed > limit_s:
        return Verdict(FAIL, f"link_ok went false after {elapsed:.1f} s (limit {limit_s} s)")
    return Verdict(PASS, f"link_ok went false {elapsed:.1f} s after the event")


def judge_recovered(reads: Sequence[Read]) -> Verdict:
    if any(s.link_ok for _, s in _valid(reads)):
        return Verdict(PASS, "link_ok came back")
    return Verdict(FAIL, "link_ok did not come back")


def judge_stays_off(reads: Sequence[Read]) -> Verdict:
    good = _valid(reads)
    if len(good) < 3:
        return Verdict(FAIL, "too few valid reads")
    if any(s.set_alpha_deg < OFF_DEG - 0.01 for _, s in good):
        return Verdict(FAIL, "the Pico set an angle below 180 deg without a command")
    return Verdict(PASS, f"set alpha stayed 180 deg over {len(good)} reads")


def judge_timed_out_seen(reads: Sequence[Read]) -> Verdict:
    if any(s.timed_out for _, s in _valid(reads)):
        return Verdict(PASS, "timed_out was seen")
    return Verdict(
        INCONCLUSIVE,
        "timed_out was not seen: the Pico repeats alpha at once after the cable is back and "
        "clears it. Check the dimmer USB log instead.",
    )


def judge_budget_slope(reads: Sequence[Read], direction: str) -> Verdict:
    """`direction` is "fall" (lamp on) or "rise" (lamp off). Expect about 1 s per s."""
    good = [(t, s) for t, s in _valid(reads) if s.link_ok and not s.tripped]
    if len(good) < 3 or good[-1][0] - good[0][0] < 5.0:
        return Verdict(FAIL, "not enough good reads over 5 s")
    (t0, s0), (t1, s1) = good[0], good[-1]
    if direction == "rise" and s0.budget_s >= 118:
        return Verdict(INCONCLUSIVE, "budget was already full: run budget-fall first")
    change = (s1.budget_s - s0.budget_s) / (t1 - t0)
    rate = -change if direction == "fall" else change
    if not 0.8 <= rate <= 1.2:
        return Verdict(FAIL, f"budget {direction}s {rate:.2f} s per s (expect 0.8 to 1.2)")
    return Verdict(PASS, f"budget {s0.budget_s} -> {s1.budget_s} s, {rate:.2f} s per s")


def judge_trip(reads: Sequence[Read], t_start: float, budget0_s: float, tol_s: float = 6.0):
    first = next(((t, s) for t, s in _valid(reads) if s.tripped), None)
    if first is None:
        return Verdict(FAIL, f"tripped never set (budget at start {budget0_s:.0f} s)")
    elapsed = first[0] - t_start
    if abs(elapsed - budget0_s) > tol_s:
        return Verdict(FAIL, f"tripped after {elapsed:.0f} s, expected about {budget0_s:.0f} s")
    return Verdict(PASS, f"tripped after {elapsed:.0f} s (budget at start {budget0_s:.0f} s)")


def judge_refused(reads: Sequence[Read], mains: bool = False) -> Verdict:
    good = _valid(reads)
    if len(good) < 3:
        return Verdict(FAIL, "too few valid reads")
    if not all(s.tripped for _, s in good):
        return Verdict(FAIL, "tripped cleared while the dimmer was still hot")
    if not mains and any(s.applied_alpha_deg is not None for _, s in good):
        return Verdict(FAIL, "the dimmer fired while tripped")
    return Verdict(PASS, "on-commands refused while tripped")


def judge_cooldown_rearm(
    reads: Sequence[Read], t_trip: float, wait_s: float, tol_s: float = 6.0
) -> Verdict:
    """After an early OFF, tripped must clear at about trip time + wait, not before."""
    cleared = next((t for t, s in _valid(reads) if not s.tripped), None)
    if cleared is None:
        return Verdict(FAIL, "tripped never cleared")
    elapsed = cleared - t_trip
    if elapsed < wait_s - tol_s:
        return Verdict(
            FAIL, f"re-armed after {elapsed:.0f} s, before the cool-down ({wait_s:.0f} s)"
        )
    if elapsed > wait_s + tol_s:
        return Verdict(FAIL, f"re-armed after {elapsed:.0f} s, expected about {wait_s:.0f} s")
    return Verdict(PASS, f"re-armed {elapsed:.0f} s after the trip (cool-down {wait_s:.0f} s)")


def judge_no_restart(status: DimmerStatus | None) -> Verdict:
    """Read after a long on-command stream with no OFF: must still be tripped and cooled."""
    if status is None or not status.link_ok:
        return Verdict(FAIL, "no valid status")
    if not status.tripped:
        return Verdict(FAIL, "the dimmer restarted by itself (tripped cleared without an OFF)")
    if status.budget_s != 0:
        return Verdict(INCONCLUSIVE, f"still {status.budget_s} s from cooled: stream was too short")
    return Verdict(PASS, "still tripped, cooled, waiting for an OFF")


def judge_cleared(reads: Sequence[Read], limit_s: float = 4.0) -> Verdict:
    good = _valid(reads)
    if not good:
        return Verdict(FAIL, "no valid reads")
    t0 = good[0][0]
    first = next((t for t, s in good if not s.tripped), None)
    if first is None or first - t0 > limit_s:
        return Verdict(FAIL, "tripped did not clear after the OFF")
    return Verdict(PASS, "tripped cleared after the OFF")


def judge_on_accepted(reads: Sequence[Read]) -> Verdict:
    good = _valid(reads)
    if not good or good[-1][1].tripped or not good[-1][1].link_ok:
        return Verdict(FAIL, "the on-command was refused after re-arm")
    return Verdict(PASS, "on-command accepted after re-arm")


def judge_reset_cleared(before: DimmerStatus | None, after: DimmerStatus | None) -> Verdict:
    if before is None or not before.link_ok:
        return Verdict(FAIL, "no valid status before the reset")
    if not before.tripped and before.budget_s > 117:
        return Verdict(INCONCLUSIVE, "budget was full before the reset: use the lamp first")
    if after is None or not after.link_ok:
        return Verdict(FAIL, "link did not come back after the reset")
    if after.tripped or after.budget_s < 118:
        return Verdict(
            FAIL, f"limiter not cleared: tripped={after.tripped} budget={after.budget_s}"
        )
    return Verdict(PASS, f"budget {before.budget_s} -> {after.budget_s} s, tripped clear")


def judge_mains_locked(reads: Sequence[Read]) -> Verdict:
    good = _valid(reads)
    if len(good) < 3 or len(good) != len(reads):
        return Verdict(FAIL, "reads had no valid reply")
    if not all(s.link_ok and s.mains and s.locked for _, s in good):
        return Verdict(FAIL, "link_ok, mains and locked are not all true")
    return Verdict(PASS, "mains true and locked true")


def judge_applied(pairs: Sequence[tuple[float, DimmerStatus | None]]) -> Verdict:
    """Requested angle against the angle the dimmer reports it fires at."""
    notes = []
    for requested, status in pairs:
        if status is None or status.applied_alpha_deg is None:
            return Verdict(FAIL, f"no applied angle at {requested:g} deg")
        applied = status.applied_alpha_deg
        if not APPLIED_MIN_DEG <= applied <= APPLIED_MAX_DEG:
            return Verdict(FAIL, f"applied {applied:.1f} deg at {requested:g} deg is out of range")
        if (
            APPLIED_MIN_DEG + 1.0 <= requested <= APPLIED_MAX_DEG - 1.0
            and abs(applied - requested) > 1.0
        ):
            return Verdict(FAIL, f"requested {requested:g} deg, applied {applied:.1f} deg")
        notes.append(f"{requested:g}->{applied:.1f}")
    return Verdict(PASS, "requested->applied: " + ", ".join(notes))


def judge_dark(reads: Sequence[Read]) -> Verdict:
    good = _valid(reads)
    if not good or any(s.applied_alpha_deg is not None for _, s in good):
        return Verdict(FAIL, "the dimmer still fires")
    return Verdict(PASS, "applied alpha is None: the dimmer does not fire")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class MainsPolicyError(RuntimeError):
    """The mains state does not match what the operator asked for."""


class Holder:
    """A second Python process that sets an angle and keeps it alive; kill it to test timeouts."""

    def __init__(self, proc) -> None:
        self._proc = proc

    def kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()


def _spawn_holder(alpha_deg: float, bus: int, device: int, mains: bool) -> Holder:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child-hold",
        str(alpha_deg),
        "--bus",
        str(bus),
        "--device",
        str(device),
        "--child-mains",
        "1" if mains else "0",
    ]
    return Holder(subprocess.Popen(cmd))


class Bench:
    def __init__(
        self,
        source,
        *,
        mains: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        ask: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
        spawn_holder: Callable[[float], Holder] | None = None,
        stable_s: float = 60.0,
        human: bool = True,
    ) -> None:
        self.source = source
        self.mains = mains
        self.clock = clock
        self.sleep = sleep
        self.ask = ask
        self.out = out
        self.spawn_holder = spawn_holder
        self.stable_s = stable_s
        self.human = human
        self.results: list[CheckResult] = []
        self._reads: list[Read] = []

    # -- helpers ----------------------------------------------------------

    def read(self) -> Read:
        item = (self.clock(), self.source.dimmer_status())
        self._reads.append(item)
        return item

    def poll(self, duration_s: float, interval_s: float) -> list[Read]:
        end = self.clock() + duration_s
        reads = [self.read()]
        while self.clock() < end:
            self.sleep(interval_s)
            reads.append(self.read())
        return reads

    def guard(self) -> DimmerStatus:
        """Refuse to command the lamp when the mains state is not what the operator asked for."""
        status = self.source.dimmer_status()
        if status is None:
            raise MainsPolicyError("no valid dimmer status: not commanding the lamp")
        if status.mains and not self.mains:
            raise MainsPolicyError(
                "the status says mains is present, but --mains was not given: not commanding"
            )
        if self.mains and not status.mains:
            raise MainsPolicyError("--mains was given but the status says no mains: not commanding")
        return status

    def command_on(self, alpha_deg: float, *, check: bool = True) -> None:
        if check:
            self.guard()
        self.source.set_dimmer_alpha(alpha_deg, max_on_s=ON_WINDOW_S)

    def hold_on(
        self, alpha_deg: float, duration_s: float, *, read_each_s: float | None
    ) -> list[Read]:
        """Keep the lamp commanded on for `duration_s` in short, renewed windows."""
        reads: list[Read] = []
        end = self.clock() + duration_s
        while self.clock() < end:
            self.command_on(alpha_deg, check=read_each_s is not None)
            step_end = min(end, self.clock() + RENEW_S)
            while self.clock() < step_end:
                if read_each_s is None:
                    self.sleep(step_end - self.clock())
                    continue
                reads.append(self.read())
                if reads[-1][1] is not None and reads[-1][1].tripped:
                    return reads
                self.sleep(read_each_s)
        return reads

    def safe_off(self) -> None:
        for _ in range(3):
            try:
                self.source.dimmer_off()
                return
            except Exception as exc:  # noqa: BLE001
                self.out(f"  OFF failed: {exc}")
        self.out("!!! LAMP OFF FAILED: cut the mains now !!!")

    def start_holder(self, alpha_deg: float) -> Holder:
        if self.spawn_holder is None:
            raise RuntimeError("no way to start the holder process")
        self.guard()
        return self.spawn_holder(alpha_deg)

    def wait_set(self, alpha_deg: float, timeout_s: float) -> bool:
        end = self.clock() + timeout_s
        while self.clock() < end:
            _, status = self.read()
            if status is not None and _near(status.set_alpha_deg, alpha_deg):
                return True
            self.sleep(0.25)
        return False

    # -- Test 0 checks (no mains) -----------------------------------------

    def c_link(self) -> Verdict:
        return judge_link(self.poll(3.0, 0.5))

    def c_alpha(self) -> Verdict:
        self.command_on(90.0)
        t0 = self.clock()
        on = [r for r in self.poll(4.0, 0.5) if r[0] >= t0 + 2.0]
        first = judge_alpha_readback(on, 90.0)
        self.source.dimmer_off()
        t1 = self.clock()
        off = [r for r in self.poll(4.0, 0.5) if r[0] >= t1 + 2.0]
        second = judge_alpha_readback(off, 180.0)
        return _combine(("set 90", first), ("set 180", second))

    def c_stable(self) -> Verdict:
        return judge_stable(self.poll(self.stable_s, 1.0))

    def c_host_timeout(self) -> Verdict:
        holder = self.start_holder(90.0)
        try:
            if not self.wait_set(90.0, 5.0):
                return Verdict(FAIL, "the holder process did not set 90 deg")
            t_kill = self.clock()
            holder.kill()
            return judge_pico_timeout(self.poll(PICO_HOST_TIMEOUT_S + 3.0, 0.25), t_kill)
        finally:
            holder.kill()

    def c_i2c_unplug(self) -> Verdict:
        self.ask("Press Enter, then UNPLUG the I2C cable and watch. ")
        # The operator unplugs on the Enter key, so time zero is the Enter.
        t0 = self.clock()
        reads = self.poll(6.0, 0.25)
        loss = judge_link_loss(reads, t0)
        self.ask("Plug the I2C cable back in and press Enter. ")
        recovered = judge_recovered(self.poll(5.0, 0.5))
        return _combine(("link loss", loss), ("recovery", recovered))

    def c_spi_unplug(self) -> Verdict:
        holder = self.start_holder(90.0)
        try:
            if not self.wait_set(90.0, 5.0):
                return Verdict(FAIL, "the holder process did not set 90 deg")
            self.ask("UNPLUG the SPI cable, then press Enter. ")
            holder.kill()
            self.ask("Wait 10 s, plug the SPI cable back in, press Enter. ")
            return judge_stays_off(self.poll(4.0, 0.5))
        finally:
            holder.kill()

    def c_deadman(self) -> Verdict:
        self.command_on(90.0)
        self.poll(2.0, 0.5)
        self.ask("Press Enter, UNPLUG the I2C cable, wait 4 s, plug it back, press Enter. ")
        return judge_timed_out_seen(self.poll(3.0, 0.1))

    def c_budget_fall(self) -> Verdict:
        self.command_on(90.0)
        return judge_budget_slope(self.poll(10.0, 1.0), "fall")

    def c_budget_rise(self) -> Verdict:
        self.source.dimmer_off()
        return judge_budget_slope(self.poll(12.0, 1.0), "rise")

    def c_trip(self) -> Verdict:
        s0 = self.guard()
        if not s0.link_ok or s0.tripped:
            return Verdict(
                INCONCLUSIVE, "the dimmer is tripped or the link is down: wait and retry"
            )
        budget0 = float(s0.budget_s)
        t_start = self.clock()
        reads = self.hold_on(90.0, budget0 + 30.0, read_each_s=1.0)
        trip = judge_trip(reads, t_start, budget0)
        if trip.status != PASS:
            return trip
        t_trip, s_trip = next((t, s) for t, s in _valid(reads) if s.tripped)
        wait_s = float(s_trip.budget_s)
        # A new on-command while tripped must be refused.
        self.command_on(90.0)
        refused = judge_refused(self.poll(4.0, 0.5))
        self.source.dimmer_off()
        # The OFF above is early (before the cool-down). The dimmer must remember it.
        rearm_reads = self.poll(wait_s + 15.0, 1.0)
        rearm = judge_cooldown_rearm(rearm_reads, t_trip, wait_s)
        self.command_on(90.0)
        accepted = judge_on_accepted(self.poll(3.0, 0.5))
        return _combine(("trip", trip), ("refused", refused), ("re-arm", rearm), ("on", accepted))

    def c_no_restart(self) -> Verdict:
        s0 = self.guard()
        if not s0.link_ok or s0.tripped:
            return Verdict(
                INCONCLUSIVE, "the dimmer is tripped or the link is down: wait and retry"
            )
        # No status read while streaming: a read that sees tripped makes the host send OFF.
        stream_s = s0.budget_s + 10.0 + EXPOSURE_RESUME_S + 5.0
        self.hold_on(90.0, stream_s, read_each_s=None)
        _, status = self.read()
        first = judge_no_restart(status)
        # That read made the host send the OFF. Now the dimmer may re-arm.
        second = judge_cleared(self.poll(4.0, 0.5))
        return _combine(("no restart", first), ("re-arm after OFF", second))

    def c_reset_clears(self) -> Verdict:
        _, before = self.read()
        self.ask("Reset the dimmer (EN button or power cycle), wait for it to start, press Enter. ")
        reads = self.poll(6.0, 0.5)
        after = next((s for _, s in reversed(reads) if s is not None and s.link_ok), None)
        return judge_reset_cleared(before, after)

    # -- Test 2 checks (mains, small lamp) --------------------------------

    def c_mains_lock(self) -> Verdict:
        self.source.dimmer_off()
        return judge_mains_locked(self.poll(4.0, 0.5))

    def c_mains_range(self) -> Verdict:
        pairs = []
        for requested in (10.0, 30.0, 60.0, 90.0, 120.0, 150.0, 170.0):
            self.command_on(requested)
            self.sleep(2.5)
            reads = [r for r in self.poll(2.0, 0.5) if r[1] is not None]
            pairs.append((requested, reads[-1][1] if reads else None))
            self.source.dimmer_off()
            self.sleep(1.0)
        return judge_applied(pairs)

    def c_mains_dark(self) -> Verdict:
        self.source.dimmer_off()
        off = judge_dark([r for r in self.poll(4.0, 0.5)][2:])
        holder = self.start_holder(90.0)
        try:
            if not self.wait_set(90.0, 5.0):
                return Verdict(FAIL, "the holder process did not set 90 deg")
            t_kill = self.clock()
            holder.kill()
            reads = self.poll(PICO_HOST_TIMEOUT_S + 3.0, 0.5)
            after = judge_dark([r for r in reads if r[0] >= t_kill + PICO_HOST_TIMEOUT_S + 1.5])
        finally:
            holder.kill()
        parts = [("alpha 180", off), ("keepalive stopped", after)]
        if self.human:
            answer = self.ask(
                "Is the lamp DARK now (also at the time the process was killed)? [y/N] "
            )
            parts.append(
                (
                    "lamp dark by eye",
                    Verdict(PASS if answer.strip().lower() == "y" else FAIL, answer),
                )
            )
        return _combine(*parts)

    # -- running ----------------------------------------------------------

    def run_check(self, name: str, func: Callable[[], Verdict]) -> CheckResult:
        self.out(f"[{name}] running")
        self._reads = []
        try:
            verdict = func()
        except MainsPolicyError as exc:
            verdict = Verdict(FAIL, str(exc))
        except KeyboardInterrupt:
            self.results.append(CheckResult(name, FAIL, "interrupted", _dump(self._reads)))
            raise
        except Exception as exc:  # noqa: BLE001
            verdict = Verdict(FAIL, f"error: {exc!r}")
        finally:
            self.safe_off()
        result = CheckResult(name, verdict.status, verdict.detail, _dump(self._reads))
        self.results.append(result)
        self.out(f"{result.status}  {name}: {result.detail}")
        return result


def _combine(*parts: tuple[str, Verdict]) -> Verdict:
    status = PASS
    for _, verdict in parts:
        if verdict.status == FAIL:
            status = FAIL
            break
        if verdict.status == INCONCLUSIVE:
            status = INCONCLUSIVE
    return Verdict(status, "; ".join(f"{name}: {v.status} ({v.detail})" for name, v in parts))


def _dump(reads: Sequence[Read]) -> list[dict]:
    return [{"t": round(t, 3), "status": None if s is None else asdict(s)} for t, s in reads]


# name, needs a human, method
TEST0_CHECKS: list[tuple[str, bool, str]] = [
    ("link", False, "c_link"),
    ("alpha", False, "c_alpha"),
    ("stable", False, "c_stable"),
    ("host-timeout", False, "c_host_timeout"),
    ("i2c-unplug", True, "c_i2c_unplug"),
    ("spi-unplug", True, "c_spi_unplug"),
    ("deadman", True, "c_deadman"),
    ("budget-fall", False, "c_budget_fall"),
    ("budget-rise", False, "c_budget_rise"),
    ("trip", False, "c_trip"),
    ("no-restart", False, "c_no_restart"),
    ("reset-clears", True, "c_reset_clears"),
]
MAINS_CHECKS: list[tuple[str, bool, str]] = [
    ("mains-lock", False, "c_mains_lock"),
    ("mains-range", False, "c_mains_range"),
    ("mains-dark", False, "c_mains_dark"),
]


def select_checks(
    only: Sequence[str] | None, *, mains: bool, auto_only: bool
) -> list[tuple[str, bool, str]]:
    pool = MAINS_CHECKS if mains else TEST0_CHECKS
    known = {name for name, _, _ in TEST0_CHECKS + MAINS_CHECKS}
    for name in only or ():
        if name not in known:
            raise ValueError(f"unknown check {name!r}")
        if name not in {n for n, _, _ in pool}:
            raise ValueError(
                f"check {name!r} is not available {'with' if not mains else 'without'} --mains"
            )
    chosen = [c for c in pool if not only or c[0] in only]
    if auto_only:
        chosen = [c for c in chosen if not c[1]]
    return chosen


def exit_code(results: Sequence[CheckResult]) -> int:
    if any(r.status == FAIL for r in results):
        return 1
    if any(r.status == INCONCLUSIVE for r in results):
        return 2
    return 0


def write_results(
    path: str, results: Sequence[CheckResult], *, mains: bool, code: int, note: str = ""
) -> None:
    data = {
        "mains_mode": mains,
        "note": note,
        "exit_code": code,
        "checks": [asdict(r) for r in results],
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _child_hold(args, source_factory=None) -> int:
    """Hold an angle for the parent. It applies the same mains rule as the parent."""
    angle = args.child_hold
    if args.child_mains is None:
        print("refused: --child-mains is required with --child-hold")
        return 3
    if not math.isfinite(angle) or not 0.0 <= angle < OFF_DEG:
        print(f"refused: angle {angle!r} is not in [0, {OFF_DEG:g}) degrees")
        return 3
    if source_factory is None:
        from mpp_sdk.io.spi_mcu import SpiMcuSource  # noqa: PLC0415

        def source_factory():
            return SpiMcuSource(bus=args.bus, device=args.device)

    source = source_factory()
    try:
        Bench(source, mains=bool(args.child_mains)).guard()
    except MainsPolicyError as exc:
        source.close()
        print(f"refused: {exc}")
        return 3
    try:
        source.set_dimmer_alpha(args.child_hold, max_on_s=ON_WINDOW_S + 10.0)
        time.sleep(ON_WINDOW_S + 10.0)
    finally:
        source.close()
    return 0


def main(argv: Sequence[str] | None = None, *, source_factory=None, ask=input, out=print) -> int:
    from mpp_sdk.io.board import default_spi_bus  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--auto-only", action="store_true", help="skip steps that need a human")
    parser.add_argument("--only", action="append", help="run one check by name (repeatable)")
    parser.add_argument("--list", action="store_true", help="list the check names and exit")
    parser.add_argument("--mains", action="store_true", help="Test 2 checks (mains, small lamp)")
    parser.add_argument("--out", default=None, help="write the results as JSON to this file")
    parser.add_argument("--stable-s", type=float, default=60.0, help="length of the stable check")
    parser.add_argument("--bus", type=int, default=default_spi_bus())
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--child-hold", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--child-mains", type=int, choices=(0, 1), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.list:
        for name, human, _ in TEST0_CHECKS + MAINS_CHECKS:
            out(f"{name}{'  (needs a human)' if human else ''}")
        return 0
    if args.child_hold is not None:
        return _child_hold(args, source_factory)
    try:
        checks = select_checks(args.only, mains=args.mains, auto_only=args.auto_only)
    except ValueError as exc:
        parser.error(str(exc))

    if source_factory is None:
        try:
            from mpp_sdk.io.spi_mcu import SpiMcuSource  # noqa: PLC0415
        except ModuleNotFoundError as exc:
            sys.exit(f"{exc}\nThis script needs spidev on the Pi: uv sync --extra hardware")

        def source_factory():
            return SpiMcuSource(bus=args.bus, device=args.device)

    if args.mains:
        out("MAINS MODE: a lamp will light. Small lamp (25 to 40 W), isolation transformer or")
        out("GFCI, fuse in line, someone ready to cut the plug. Read hardware/dimmer/README.md.")
        try:
            answer = ask(f"Type exactly '{CONFIRM_TEXT}' to continue: ")
        except EOFError:
            answer = ""
        if answer.strip() != CONFIRM_TEXT:
            out("not confirmed, nothing was commanded")
            return 3

    def _on_sigterm(*_: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, _on_sigterm)
    source = source_factory()
    bench = Bench(
        source,
        mains=args.mains,
        ask=ask,
        out=out,
        spawn_holder=lambda alpha: _spawn_holder(alpha, args.bus, args.device, args.mains),
        stable_s=args.stable_s,
        human=not args.auto_only,
    )
    code = 0
    note = ""
    try:
        try:
            bench.guard()
        except MainsPolicyError as exc:
            out(f"REFUSED: {exc}")
            note = f"refused: {exc}"
            code = 3
        else:
            for name, _, method in checks:
                bench.run_check(name, getattr(bench, method))
            code = exit_code(bench.results)
    except KeyboardInterrupt:
        out("\ninterrupted, switching off")
        note = "interrupted"
        code = 130
    finally:
        bench.safe_off()
        source.close()
        signal.signal(signal.SIGTERM, previous)
        if args.out:
            write_results(args.out, bench.results, mains=args.mains, code=code, note=note)
    out("")
    for r in bench.results:
        out(f"{r.status:12} {r.name}")
    out(f"exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
