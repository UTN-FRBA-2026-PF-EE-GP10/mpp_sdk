"""Lamp dimmer control for the server: a source holder, a status cache and commands.

Why the lamp does not go through the poll thread: a live run holds that thread
for up to 10 minutes, and OFF must act within about a second. The lamp methods
of ``SpiMcuSource`` are lock-protected (one RLock around every SPI exchange, and
the dimmer keepalive thread already uses them from its own thread), so request
threads call them directly on the source the poll thread published here.

Worst case for a lamp command: the lock is held for one SPI exchange at a time
(a few milliseconds; the longest is the bulk read of a sweep result, with a 2 ms
pause), so a command waits for that. An ON then also confirms the link and can
take up to about 1.5 s more. OFF takes one exchange, or 3 attempts if the link
fails.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from mpp_sdk.io.dimmer import (
    MAX_LAMP_WINDOW_S,
    DimmerRefused,
    DimmerStatus,
    lamp_power_fraction,
)

_log = logging.getLogger(__name__)

REFRESH_S = 1.0
# A status older than this is not shown: the page must never see the last "on".
STALE_S = 3.0
_OFF_ATTEMPTS = 3
_CONFIRM_S = 1.5
_CONFIRM_POLL_S = 0.25


class LampError(Exception):
    """A lamp command that failed. ``status_code`` is the HTTP code to return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_CAP_TOLERANCE = 1e-9


def checked_power(power: float | None, alpha_deg: float | None, max_power: float) -> float:
    """The power a request asks for, or LampError 422 above the server cap.

    An angle is capped through the power it gives, so --lamp-max-power binds both.
    """
    value = power if power is not None else lamp_power_fraction(alpha_deg)
    # The alpha that gives exactly the cap power is found by bisection, so it can be a hair over.
    if value > max_power + _CAP_TOLERANCE:
        raise LampError(422, f"lamp power {value:.3f} is above the server cap {max_power:g}")
    return value


class _LampHolder:
    """Thread-safe slot for the source the lamp methods are called on.

    The poll thread sets it once the source exists and clears it before the
    source closes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._source: Any = None

    def set(self, source: Any) -> None:
        with self._lock:
            self._source = source

    def clear(self) -> None:
        with self._lock:
            self._source = None

    def get(self) -> Any:
        with self._lock:
            return self._source


class _LampController:
    def __init__(
        self,
        holder: _LampHolder | None = None,
        *,
        max_power: float = 1.0,
        refresh_s: float = REFRESH_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.holder = holder if holder is not None else _LampHolder()
        self.max_power = max_power
        self._refresh_s = refresh_s
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: dict | None = None
        self._captured_at = 0.0
        # Sequence numbers: a status read takes one before it reads, and a result
        # older than the stored one is dropped (a refresh that started before an
        # OFF must not overwrite the OFF's status).
        self._seq = 0
        self._stored_seq = 0
        # Ordering of commands. `_gen_lock` guards the counters and is never held
        # across I/O. `_cmd_lock` serialises sends to the source, separate from the
        # source's own SPI lock. OFF bumps `_off_gen`, so an ON that arrived before
        # it cannot light the lamp after it. Every ON bumps `_on_gen`, so a failing
        # ON cannot switch off a newer ON.
        self._gen_lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._off_gen = 0
        self._on_gen = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- status ----------------------------------------------------------------

    def _unavailable(self, error: str, *, available: bool) -> dict:
        return {
            "available": available,
            "state": "unavailable",
            "power": None,
            "alpha_deg": None,
            "applied_alpha_deg": None,
            "window_left_s": None,
            "max_on_s": MAX_LAMP_WINDOW_S,
            "budget_s": None,
            "tripped": None,
            "mains": None,
            "locked": None,
            "timed_out": None,
            "link_ok": False,
            "max_power": self.max_power,
            "error": error,
        }

    def _build(self, source: Any, status: DimmerStatus | None) -> dict:
        if status is None:
            return self._unavailable("dimmer status unreadable", available=True)
        if not status.link_ok:
            return self._unavailable("dimmer link not confirmed", available=True)
        window_left = source.dimmer_window_left_s()
        if status.tripped:
            state = "tripped"
        elif window_left is not None:
            state = "on"
        else:
            state = "off"
        on = state == "on"
        return {
            "available": True,
            "state": state,
            "power": lamp_power_fraction(status.set_alpha_deg) if on else None,
            "alpha_deg": status.set_alpha_deg if on else None,
            "applied_alpha_deg": status.applied_alpha_deg,
            "window_left_s": window_left,
            "max_on_s": MAX_LAMP_WINDOW_S,
            "budget_s": status.budget_s,
            "tripped": status.tripped,
            "mains": status.mains,
            "locked": status.locked,
            "timed_out": status.timed_out,
            "link_ok": True,
            "max_power": self.max_power,
            "error": None,
        }

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def _store(self, snapshot: dict, seq: int | None = None) -> None:
        if seq is None:
            seq = self._next_seq()
        with self._lock:
            if seq < self._stored_seq:
                return
            self._stored_seq = seq
            self._snapshot = snapshot
            self._captured_at = self._clock()

    def snapshot(self) -> dict:
        """The cached status. Never touches SPI."""
        with self._lock:
            snap = self._snapshot
            age = self._clock() - self._captured_at
        if snap is None:
            if self.holder.get() is None:
                return self._unavailable("no board configured", available=False)
            return self._unavailable("no dimmer status yet", available=True)
        if age > STALE_S:
            return self._unavailable(
                f"dimmer status is stale ({age:.1f} s old)", available=snap["available"]
            )
        out = dict(snap)
        if out["window_left_s"] is not None:
            out["window_left_s"] = max(0.0, out["window_left_s"] - age)
        return out

    def refresh_once(self) -> None:
        """Read the status from the source and cache it. Runs in the refresh thread."""
        source = self.holder.get()
        if source is None:
            self._store(self._unavailable("no board configured", available=False))
            return
        seq = self._next_seq()
        try:
            snapshot = self._build(source, source.dimmer_status())
        except Exception as exc:
            _log.warning("dimmer status read failed: %s", exc)
            snapshot = self._unavailable(f"dimmer status read failed: {exc}", available=True)
        self._store(snapshot, seq)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lamp-status", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while True:
            try:
                self.refresh_once()
            except Exception:
                _log.exception("lamp status refresh failed")
            if self._stop.wait(self._refresh_s):
                return

    # -- commands (called from request threads) -----------------------------------

    def _off_with_retry(self, source: Any) -> Exception | None:
        error: Exception | None = None
        for _ in range(_OFF_ATTEMPTS):
            try:
                source.dimmer_off()
                return None
            except Exception as exc:
                error = exc
                _log.exception("dimmer OFF failed")
        return error

    def generations(self) -> tuple[int, int]:
        """`(off_gen, on_gen)`. A lamp-assisted step compares it with the value it
        saw after its own ON: any change means an operator command came since."""
        with self._gen_lock:
            return self._off_gen, self._on_gen

    def off(self, *, only_if_on_gen: int | None = None) -> dict | None:
        """Switch the lamp off and return the status. Never raises: OFF is the safe command.

        With `only_if_on_gen`, the OFF is skipped (and None returned) when an ON newer
        than that one came in, so a lamp-assisted step never ends an operator's newer
        window. The check and the generation bump share one lock section.
        """
        source = self.holder.get()
        if source is None:
            snap = self._unavailable("no board configured", available=False)
            self._store(snap)
            return snap
        with self._gen_lock:
            if only_if_on_gen is not None and self._on_gen != only_if_on_gen:
                return None
            self._off_gen += 1
        with self._cmd_lock:
            error = self._off_with_retry(source)
            seq = self._next_seq()
        if error is not None:
            snap = self._unavailable(f"OFF failed, lamp state unknown: {error}", available=True)
            self._store(snap, seq)
            return snap
        try:
            snap = self._build(source, source.dimmer_status())
        except Exception as exc:
            snap = self._unavailable(f"dimmer status read failed: {exc}", available=True)
        self._store(snap, seq)
        return snap

    def _off_if_current(self, source: Any, off_gen: int, on_gen: int) -> None:
        """Failure path of an ON: switch off, unless an OFF or a newer ON came since."""
        with self._cmd_lock:
            with self._gen_lock:
                current = self._off_gen == off_gen and self._on_gen == on_gen
            if current:
                self._off_with_retry(source)

    def on(self, *, power: float | None, alpha_deg: float | None, max_on_s: float) -> dict:
        """Open a lamp window and return the confirmed status, or raise LampError."""
        return self.on_tracked(power=power, alpha_deg=alpha_deg, max_on_s=max_on_s)[0]

    def on_tracked(
        self, *, power: float | None, alpha_deg: float | None, max_on_s: float
    ) -> tuple[dict, tuple[int, int]]:
        """Like `on`, also returning the `generations()` pair right after this ON."""
        with self._gen_lock:
            self._on_gen += 1
            on_gen, off_gen = self._on_gen, self._off_gen
        source = self.holder.get()
        if source is None:
            raise LampError(503, "no board configured: the lamp is not available")
        cancelled = LampError(409, "cancelled by Off")
        try:
            with self._cmd_lock:
                # Re-checked under the command lock: an OFF that arrived while this
                # request was on its way has already sent its OFF frame, and this
                # ON must not follow it.
                with self._gen_lock:
                    if self._off_gen != off_gen:
                        raise cancelled
                if power is not None:
                    source.set_dimmer_power(power, max_on_s=max_on_s)
                else:
                    source.set_dimmer_alpha(alpha_deg, max_on_s=max_on_s)
        except LampError:
            raise
        except DimmerRefused as exc:
            raise LampError(409, str(exc)) from exc
        except Exception as exc:
            _log.exception("lamp command failed")
            self._off_if_current(source, off_gen, on_gen)
            raise LampError(503, f"lamp command failed: {exc}") from exc
        # Fail closed: the lamp stays on only if the dimmer link is confirmed.
        # The poll runs outside the command lock, so an OFF is never held up by it.
        seq = self._next_seq()
        status = self._confirm(source)
        if status is None:
            self._off_if_current(source, off_gen, on_gen)
            raise LampError(503, "dimmer link not confirmed, lamp switched off")
        with self._gen_lock:
            if self._off_gen != off_gen:
                raise cancelled
        # This ON's own generations, not the current ones: a newer ON must show as a change.
        generations = (off_gen, on_gen)
        snap = self._build(source, status)
        self._store(snap, seq)
        if status.tripped:
            # The status read already sent the acknowledgment OFF.
            raise LampError(
                409,
                f"dimmer exposure limiter tripped: wait {status.budget_s} s, "
                "then press Off to re-arm",
            )
        return snap, generations

    def _confirm(self, source: Any) -> DimmerStatus | None:
        end = time.monotonic() + _CONFIRM_S
        while True:
            try:
                status = source.dimmer_status()
            except RuntimeError, OSError:
                status = None
            if status is not None and status.link_ok:
                return status
            if time.monotonic() >= end:
                return None
            time.sleep(_CONFIRM_POLL_S)

    def shutdown_off(self) -> None:
        """Stop the refresh thread and switch the lamp off (server shutdown)."""
        self.stop()
        source = self.holder.get()
        if source is not None:
            with self._gen_lock:
                self._off_gen += 1
            with self._cmd_lock:
                error = self._off_with_retry(source)
            if error is not None:
                _log.error("lamp OFF at shutdown failed: %s", error)
