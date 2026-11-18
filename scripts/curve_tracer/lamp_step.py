"""Lamp-assisted sweeps and runs: the lamp is on only for the measurement.

A step is: check, lamp on, warm-up, measurement, lamp off. The warm-up and the
wait for the end run in a small thread of their own, never in the poll thread:
that thread must keep polling sweep progress and serving commands.

The lamp is switched off in a `finally`, so every end path is covered: normal
end, run aborted by its limits, Stop (also during the warm-up, which cancels the
measurement), an error, a sweep that never reports (the wait has a deadline) and
the server shutting down. Every lamp command goes through `_LampController`,
which orders OFF before ON. The step switches off only if no operator command
came since its own ON (`generations`): a newer manual window is never ended by it.

Manual OFF during the step: the lamp phase ends ("off") and the step never
switches the lamp on again. During the warm-up the measurement is cancelled
(it would run in the dark). During the measurement it goes on, and its data is
dark from the OFF on; the operator has chosen that.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from scripts.curve_tracer.lamp import LampError, _LampController, checked_power
from scripts.curve_tracer.limits import _LAMP_STEP_MARGIN_S, _LAMP_STEP_MAX_ON_S

_log = logging.getLogger(__name__)

_TICK_S = 0.1


@dataclass(frozen=True)
class _LampPlan:
    """The `lamp` option of a request, validated against the server cap."""

    power: float | None
    alpha_deg: float | None
    warmup_s: float

    def settings(self) -> dict:
        """What the run record keeps: the level asked for and the warm-up, nothing else."""
        level = {"power": self.power} if self.power is not None else {"alpha_deg": self.alpha_deg}
        return {**level, "warmup_s": self.warmup_s}


class _LampStepRunner:
    def __init__(self, lamp: _LampController, *, tick_s: float = _TICK_S) -> None:
        self.lamp = lamp
        self._tick_s = tick_s
        self._lock = threading.Lock()
        self._active = False
        self._kind: str | None = None
        self._phase: str | None = None
        self._warmup_end = 0.0
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    # -- state for the page -------------------------------------------------------

    def snapshot(self, kind: str) -> dict:
        """`lamp_phase` (null, "warming", "measuring", "off") of the last step of `kind`
        ("run" or "sweep"), and `lamp_warmup_left_s` while warming."""
        with self._lock:
            if self._kind != kind:
                return {"lamp_phase": None, "lamp_warmup_left_s": None}
            left = (
                max(0.0, self._warmup_end - time.monotonic()) if self._phase == "warming" else None
            )
            return {"lamp_phase": self._phase, "lamp_warmup_left_s": left}

    def active(self) -> bool:
        with self._lock:
            return self._active

    def forget(self) -> None:
        """A measurement without the lamp option starts: its status shows no lamp phase."""
        with self._lock:
            if not self._active:
                self._kind = None
                self._phase = None

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    # -- checks, before anything is switched on or started -------------------------

    def plan(self, power: float | None, alpha_deg: float | None, warmup_s: float) -> _LampPlan:
        """Validate the level. LampError 422 above the cap, or for power 0 (not a light)."""
        level = checked_power(power, alpha_deg, self.lamp.max_power)
        if level <= 0.0 or alpha_deg == 180.0:
            raise LampError(422, "the lamp option needs a power above 0")
        return _LampPlan(power, alpha_deg, warmup_s)

    def needed_s(self, plan: _LampPlan, measure_s: float) -> float:
        return plan.warmup_s + measure_s + _LAMP_STEP_MARGIN_S

    def preflight(self, plan: _LampPlan, measure_s: float, what: str) -> float:
        """Refuse (LampError) when the step cannot run. Returns the lamp time it needs.

        422 total too long, 503 no confirmed dimmer link, 409 tripped or budget too small.
        """
        needed = self.needed_s(plan, measure_s)
        if needed > _LAMP_STEP_MAX_ON_S:
            raise LampError(
                422,
                f"the lamp would be on for {needed:g} s (warm-up {plan.warmup_s:g} s + "
                f"{what} {measure_s:g} s + margin {_LAMP_STEP_MARGIN_S:g} s), above the limit "
                f"of {_LAMP_STEP_MAX_ON_S:g} s (the dimmer trips at 120 s of continuous on time)",
            )
        # A fresh read, not the cache: the budget changes every second.
        self.lamp.refresh_once()
        snap = self.lamp.snapshot()
        if not snap["link_ok"]:
            raise LampError(503, f"no confirmed dimmer link: {snap['error']}")
        budget = snap["budget_s"] or 0
        if snap["tripped"]:
            raise LampError(
                409,
                f"dimmer exposure limiter tripped: wait {budget} s, then press Off to re-arm",
            )
        if budget < needed:
            wait = int(needed - budget + 0.999)
            raise LampError(
                409,
                f"the lamp budget is {budget} s but the step needs {needed:g} s: "
                f"wait {wait} s for the dimmer to cool",
            )
        return needed

    # -- the step ------------------------------------------------------------------

    def begin(
        self,
        kind: str,
        plan: _LampPlan,
        needed_s: float,
        *,
        cancel: threading.Event,
        start: Callable[[], None],
        is_done: Callable[[], bool],
        on_abort: Callable[[str], None],
        measure_deadline_s: float,
    ) -> None:
        """Switch the lamp on (raises LampError, nothing started), then warm up, start the
        measurement and watch it in a thread of its own.

        `cancel` is set by Stop and by the runner on a late failure; `start` queues the
        measurement; `is_done` says it ended; `on_abort` closes a step that never started it.
        """
        with self._lock:
            if self._active:
                raise LampError(409, "a lamp-assisted step is already in progress")
            self._active = True
            self._kind = kind
            self._phase = "warming"
            self._warmup_end = time.monotonic() + plan.warmup_s
        try:
            _, generations = self.lamp.on_tracked(
                power=plan.power, alpha_deg=plan.alpha_deg, max_on_s=needed_s
            )
        except BaseException:
            with self._lock:
                self._active = False
                self._kind = None
                self._phase = None
            raise
        try:
            thread = threading.Thread(
                target=self._drive,
                args=(plan, generations, cancel, start, is_done, on_abort, measure_deadline_s),
                name="lamp-step",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        except BaseException:
            # No thread will switch the lamp off or free the runner: do both here.
            self.lamp.off()
            with self._lock:
                self._active = False
                self._phase = "off"
            raise

    def _lamp_lost(self, generations: tuple[int, int]) -> str | None:
        """Why the lamp is no longer this step's, or None."""
        now = self.lamp.generations()
        if now[0] != generations[0]:
            return "the lamp was switched off by the operator"
        if now[1] != generations[1]:
            return "the lamp was changed by the operator"
        return None

    def _drive(
        self,
        plan: _LampPlan,
        generations: tuple[int, int],
        cancel: threading.Event,
        start: Callable[[], None],
        is_done: Callable[[], bool],
        on_abort: Callable[[str], None],
        measure_deadline_s: float,
    ) -> None:
        started = False
        try:
            reason = None
            end = time.monotonic() + plan.warmup_s
            while (left := end - time.monotonic()) > 0:
                if cancel.is_set():
                    reason = "stopped during the lamp warm-up"
                elif self._shutdown.is_set():
                    reason = "server shutting down"
                elif lost := self._lamp_lost(generations):
                    reason = f"{lost} during the warm-up"
                if reason:
                    break
                cancel.wait(min(self._tick_s, left))
            if reason is None and cancel.is_set():
                reason = "stopped during the lamp warm-up"
            if reason is not None:
                on_abort(reason)
                return
            self._set_phase("measuring")
            start()
            started = True
            deadline = time.monotonic() + measure_deadline_s
            lamp_phase_ended = False
            while not is_done():
                if self._shutdown.is_set() or time.monotonic() > deadline:
                    cancel.set()
                    break
                if not lamp_phase_ended and self._lamp_lost(generations) is not None:
                    lamp_phase_ended = True
                    self._set_phase("off")
                # Not cancel.wait: after a Stop it returns at once and this would spin.
                self._shutdown.wait(self._tick_s)
        except Exception as exc:
            _log.exception("lamp-assisted step failed")
            if started:
                cancel.set()
            else:
                try:
                    on_abort(f"error: {exc}")
                except Exception:
                    _log.exception("closing the failed step failed")
        finally:
            try:
                self.lamp.off(only_if_on_gen=generations[1])
            except Exception:
                _log.exception("lamp OFF at the end of a step failed")
            self._set_phase("off")
            with self._lock:
                self._active = False

    def shutdown(self) -> None:
        """Server shutdown: end any step (its thread switches the lamp off)."""
        self._shutdown.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
