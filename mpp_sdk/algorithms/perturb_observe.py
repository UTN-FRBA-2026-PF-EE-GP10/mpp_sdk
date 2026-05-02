"""Fixed-step Perturb & Observe MPPT for a SEPIC (or boost) converter."""

import math

from .base import MPPTAlgorithm


class PerturbAndObserve(MPPTAlgorithm):
    """Classical fixed-step Perturb & Observe.

    Each call perturbs the duty cycle by ``±step_size`` and uses the sign of
    the most recent ``(ΔP, ΔV)`` pair to decide whether to keep going or
    reverse.

    Sign convention is chosen for the SDK's default **SEPIC** converter,
    where increasing the duty cycle decreases the panel terminal voltage
    (``R_eff = R_load · ((1-D)/D)²``, monotonically decreasing in D over
    ``(0, 1)``). The same sign held for the earlier boost variant, so this
    block does not change when the topology does. The classical P&O
    decision (in V) is therefore mapped to its inverse in D:

        - ΔP·ΔV > 0  → "we improved while V was moving in some direction" →
                       keep increasing V → **decrease** D.
        - ΔP·ΔV < 0  → "we got worse while V was moving" → **increase** D.

    A smaller ``step_size`` reduces steady-state oscillation around the MPP
    but slows convergence — the well-known accuracy/speed tradeoff.
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        step_size: float = 0.005,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
    ) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if not (math.isfinite(step_size) and step_size > 0):
            raise ValueError(f"step_size must be a finite positive number; got {step_size=}")
        self._duty = max(min_duty, min(max_duty, initial_duty))
        self._step_size = step_size
        self._min = min_duty
        self._max = max_duty
        self._last_v: float | None = None
        self._last_p: float | None = None

    def step(self, voltage: float, current: float) -> float:
        power = voltage * current

        if self._last_v is None or self._last_p is None:
            self._last_v = voltage
            self._last_p = power
            self._duty = self._clamp(self._duty + self._step_size)
            return self._duty

        dv = voltage - self._last_v
        dp = power - self._last_p

        if dp == 0.0:
            direction = 0
        elif dp * dv > 0.0:
            direction = -1
        else:
            direction = +1

        self._duty = self._clamp(self._duty + direction * self._step_size)
        self._last_v = voltage
        self._last_p = power
        return self._duty

    def _clamp(self, duty: float) -> float:
        return max(self._min, min(self._max, duty))

    @property
    def duty(self) -> float:
        return self._duty
