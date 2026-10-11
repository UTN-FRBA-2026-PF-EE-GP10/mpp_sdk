"""Run a registered MPPT algorithm against real hardware and record a
closed-loop run: a time series of (V, I, D) captured while the algorithm
drove the live SEPIC via `SpiMcuSource`.

Needs `mpp-sdk[hardware]` (spidev). By default also sweeps and saves a
static I-V curve first (ground truth for `scripts/plot_run.py`) - skip
that with `--no-sweep --curve <path>` to reuse an existing capture.

`FirmwareMode::MppTracker` (the firmware's default mode) already applies
whatever duty the Pi last wrote, unconditionally - there is no on-target
safety cutoff for this continuous-drive use case (unlike the curve
tracer's own `breach()` check), so this script adds a client-side abort:
if readings stay above `--v-max`/`--i-max` (defaults: the board limits
`BOARD_V_MAX`/`BOARD_I_MAX` below), or the link looks down (a sustained
run of corrupt SPI frames - see `_BAD_FRAMES_LINK_DOWN` below), duty is
driven to zero and the run is marked aborted. `run_control_loop` is also
what `scripts/curve_tracer_server.py` calls to drive a run started from
the web UI - one control loop, one abort path, shared by both.

Usage::

    uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import math
import time
from collections.abc import Callable

from harness.common import algorithm_specs
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves.library import save as curves_save
from mpp_sdk.curves.record import now_utc as curves_now_utc
from mpp_sdk.runs import RunRecord, RunSample
from mpp_sdk.runs import save as runs_save
from mpp_sdk.runs.record import now_utc as runs_now_utc

# Consecutive bad SPI frames before a run treats the link as down (see
# SpiMcuSource.consecutive_bad_frames). Conceptually the same idea as
# curve_tracer_server.py's own _BAD_FRAMES_LINK_DOWN (8, at that loop's
# ~50 ms poll period - about 400 ms to notice a pulled cable), but this
# loop has no sleep between exchanges by default (period_s=0) and each
# exchange is on the order of 1-2 ms, so the count is scaled up to reach
# a similar wall-clock detection time rather than tripping on one burst
# of ordinary line noise.
_BAD_FRAMES_LINK_DOWN = 300

# Consecutive readings over v_max / i_max / v_out_max before a run aborts.
# A single garbage sample (seen on the bench: normal readings, then one
# absurd V, I or V out) would otherwise end the run at once. A real
# overvoltage or overcurrent lasts far longer than this many exchanges.
_LIMIT_DEBOUNCE_SAMPLES = 5
# Also require the streak to span this long: a failed SPI frame replays the
# last good reading, so one garbage frame can repeat for several exchanges.
_LIMIT_DEBOUNCE_S = 0.05

# Board limits a run is held to unless the operator narrows them. The web
# server imports these, so the CLI and the UI enforce the same values.
#
# Current: the INA229 is scaled to a 1000 mA full scale (`I_MAX_MA` in
# firmware/pipico_board/src/ina229.rs). Its CURRENT register is 20-bit
# signed, so the largest real reading is 999 mA. A 1.0 A limit could never
# trip on a real reading, so the limit sits below the sensor maximum.
#
# Output voltage: the on-chip ADC's `Low` divider range reads up to about
# 27 V; above that the reading saturates and a higher limit never trips.
BOARD_V_MAX = 40.0
BOARD_I_MAX = 0.9
BOARD_V_OUT_MAX = 25.0

_log = logging.getLogger(__name__)


def _check_positive_finite(name: str, value: float) -> None:
    # NaN compares False against everything, so a NaN limit would switch
    # its abort off without a sign. Refuse it before any duty is written.
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number above 0; got {value!r}")


def run_control_loop(
    source,
    algorithm,
    *,
    duration_s: float,
    v_max: float,
    i_max: float,
    v_out_max: float | None = None,
    initial_duty: float = 0.5,
    clock=time.monotonic,
    sleep=time.sleep,
    period_s: float = 0.0,
    should_stop: Callable[[], bool] | None = None,
    max_consecutive_bad_frames: int = _BAD_FRAMES_LINK_DOWN,
    on_sample: Callable[[RunSample], None] | None = None,
    samples: list[RunSample] | None = None,
) -> tuple[list[RunSample], bool, str | None]:
    """Run `algorithm` against `source` for `duration_s` seconds,
    recording one `RunSample` per control step. Returns
    `(samples, aborted, reason)`.

    `samples`, if given, is the list appended to and returned - the
    caller's own reference, not a copy. Pass one in when the samples
    collected before an exception propagates still matter (e.g. a web
    server wants to save a partial run rather than lose it): the caller
    keeps a live view of what was recorded even though this function
    never gets to return normally. Defaults to a fresh list.

    `aborted` is True, and `reason` names why, if any of these fire
    (source is driven to 0 duty before returning either way):

    - `"overvoltage"` / `"overcurrent"`: a reading exceeded `v_max`/`i_max`.
      A limit aborts only when `_LIMIT_DEBOUNCE_SAMPLES` readings in a row
      break it and the streak spans `_LIMIT_DEBOUNCE_S`. A shorter streak is
      dropped: the loop holds the duty, reads again, and the reading never
      reaches the algorithm or `samples`. This applies to the output limit
      below too.
    - `"output-overvoltage"`: the converter output (`source.vout`, absent on
      a simulated source, which never trips this) exceeded `v_out_max`. The
      panel limits cannot see this: with a light or missing load the SEPIC
      output climbs far past the input while the panel side looks normal.
    - `"link-down"`: `source.consecutive_bad_frames` (absent on a fake or
      simulated source, which reads as 0 and never trips this) reached
      `max_consecutive_bad_frames` - SPI has no presence detection, so a
      disconnected board otherwise looks like valid-but-stale telemetry.
    - `"stopped"`: `should_stop()` returned True - an explicit request to
      end the run early (e.g. a UI Stop button), checked once per step.
    - `"invalid-reading"`: V or I is not a finite number, held for the same
      debounce as the limits.
    - `"invalid-duty"`: the algorithm returned a duty that is not a finite
      number. It is never written.

    A limit or `initial_duty` that is not finite, or not in range, raises
    `ValueError` before any duty is written.

    `reason` is `None` on an ordinary `duration_s` timeout - that is not
    an abort.

    Every exit path - normal completion, an abort above, or an exception
    raised by `source`/`algorithm` - drives duty to zero before returning
    or propagating. This is the function's one safety-critical guarantee;
    do not reimplement this loop elsewhere; extend it here instead so the
    CLI and any other caller keep exactly one abort path.

    `period_s > 0` adds a `sleep()` pad between steps; 0 (default) runs as
    fast as `source.read()/write()` allow. `on_sample`, if given, is
    called with each `RunSample` as it's recorded - for a caller (e.g. a
    web server) that wants to observe the run live without waiting for it
    to finish.
    """
    _check_positive_finite("v_max", v_max)
    _check_positive_finite("i_max", i_max)
    if v_out_max is not None:
        _check_positive_finite("v_out_max", v_out_max)
    if not (math.isfinite(initial_duty) and 0.0 <= initial_duty < 1.0):
        raise ValueError(f"initial_duty must be a finite number in [0, 1); got {initial_duty!r}")
    samples = [] if samples is None else samples
    start = clock()
    aborted = False
    reason: str | None = None
    try:
        # Seed write moved inside the try: a raising seed write used to
        # skip the `finally` below entirely, breaking the zero-duty
        # guarantee this docstring promises for every exit path.
        source.write(initial_duty)  # SpiMcuSource.read() raises before the first write()
        duty = initial_duty
        over_limit = 0
        streak: list[tuple[float, float, float, float | None, float, str]] = []
        while clock() - start < duration_s:
            voltage, current = source.read()
            t = clock() - start
            v_out = getattr(source, "vout", None)
            suspect: str | None = None
            if not (math.isfinite(voltage) and math.isfinite(current)):
                suspect = "invalid-reading"
            elif voltage > v_max:
                suspect = "overvoltage"
            elif current > i_max:
                suspect = "overcurrent"
            elif v_out_max is not None and v_out is not None and v_out > v_out_max:
                suspect = "output-overvoltage"
            over_limit = over_limit + 1 if suspect else 0
            if suspect:
                streak.append((round(t, 4), voltage, current, v_out, duty, suspect))
            elif streak:
                _log.warning("ignored %d suspect reading(s): %s", len(streak), streak)
                streak = []
            if (
                suspect
                and over_limit >= _LIMIT_DEBOUNCE_SAMPLES
                and t - streak[0][0] >= _LIMIT_DEBOUNCE_S
            ):
                aborted = True
                reason = suspect
                _log.warning("run aborted (%s), t,V,I,Vout,duty,kind: %s", reason, streak)
                break
            if getattr(source, "consecutive_bad_frames", 0) >= max_consecutive_bad_frames:
                aborted = True
                reason = "link-down"
                break
            if should_stop is not None and should_stop():
                aborted = True
                reason = "stopped"
                break
            if suspect:
                # Hold the duty and fetch a fresh reading; the suspect one
                # never reaches the algorithm or the saved samples.
                source.write(duty)
                if period_s > 0:
                    sleep(period_s)
                continue
            next_duty = algorithm.step(voltage, current)
            if not math.isfinite(next_duty):
                aborted = True
                reason = "invalid-duty"
                break
            duty = next_duty
            source.write(duty)
            sample = RunSample(t=t, voltage=voltage, current=current, duty=duty)
            samples.append(sample)
            if on_sample is not None:
                on_sample(sample)
            if period_s > 0:
                sleep(period_s)
    finally:
        # Zeroing duty is the priority on the way out; a broken write here
        # must not mask whatever exception is already propagating (or
        # silently replace a clean return with a spurious one).
        with contextlib.suppress(Exception):
            source.write(0.0)
    return samples, aborted, reason


def _sweep_and_save_curve(src, *, timeout_s: float, poll_interval_s: float, label: str) -> str:
    """Trigger one sweep, save it via mpp_sdk.curves, release the relay,
    and return the saved file's name (for RunRecord.curve_ref)."""
    from scripts.curve_tracer_bench_test import run_sweep_and_fetch

    points = run_sweep_and_fetch(src, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
    record = CurveRecord(
        captured_at=curves_now_utc(),
        label=label,
        measurement="baseline",
        panels=(),
        points=tuple(points),
        # This script only ever runs against a real board (it needs
        # spidev), so the sweep it saves is always a measurement.
        source="hardware",
    )
    path = curves_save(record)
    src.release_relay()
    return path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    specs = {s.label.lower(): s for s in algorithm_specs()}
    parser.add_argument(
        "--algorithm",
        required=True,
        help=f"one of: {', '.join(s.label for s in specs.values())} (case-insensitive)",
    )
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument("--label", required=True)
    parser.add_argument("--v-max", type=float, default=BOARD_V_MAX)
    parser.add_argument(
        "--i-max",
        type=float,
        default=BOARD_I_MAX,
        help="input current limit (below the INA229's 999 mA maximum reading)",
    )
    parser.add_argument(
        "--v-out-max",
        type=float,
        default=BOARD_V_OUT_MAX,
        help="converter output limit (below the ADC Low range, ~27 V)",
    )
    parser.add_argument("--no-sweep", action="store_true", help="skip the curve sweep")
    parser.add_argument("--curve", default=None, help="existing curve filename (with --no-sweep)")
    parser.add_argument("--bus", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--speed-hz", type=int, default=200_000)
    args = parser.parse_args()

    spec = specs.get(args.algorithm.lower())
    if spec is None:
        parser.error(f"unknown --algorithm {args.algorithm!r}; choices: {', '.join(specs)}")

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    with SpiMcuSource(bus=args.bus, device=args.device, speed_hz=args.speed_hz) as src:
        curve_ref = args.curve
        if not args.no_sweep:
            print("Sweeping curve...")
            curve_ref = _sweep_and_save_curve(
                src, timeout_s=15.0, poll_interval_s=0.05, label=args.label
            )
            print(f"  saved curve: {curve_ref}")

        print(f"Running {spec.label} for {args.duration_s}s...")
        algorithm = spec.make(0.5)
        samples, aborted, reason = run_control_loop(
            src,
            algorithm,
            duration_s=args.duration_s,
            v_max=args.v_max,
            i_max=args.i_max,
            v_out_max=args.v_out_max,
        )

    record = RunRecord(
        captured_at=runs_now_utc(),
        label=args.label,
        algorithm=spec.label,
        samples=tuple(samples),
        curve_ref=curve_ref,
        aborted=aborted,
        notes=reason or "",
        # This script only ever runs against a real board (it needs
        # spidev), so the run it saves always drove real hardware.
        source="hardware",
    )
    path = runs_save(record)

    print(f"\n{'steps':<10}{'aborted':<10}{'final V':<10}{'final I':<10}{'final D':<10}")
    last = samples[-1] if samples else None
    print(
        f"{len(samples):<10}{aborted!s:<10}"
        f"{last.voltage if last else 0.0:<10.3f}"
        f"{last.current if last else 0.0:<10.3f}"
        f"{last.duty if last else 0.0:<10.3f}"
    )
    if reason:
        print(f"Abort reason: {reason}")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
