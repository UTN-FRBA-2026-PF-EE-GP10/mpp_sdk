"""Adaptive-step Perturb & Observe MPPT for a SEPIC (or boost) converter."""

import math

from .base import MPPTAlgorithm


class AdaptivePerturbAndObserve(MPPTAlgorithm):
    """Perturb & Observe whose duty step follows the measured power slope.

    The direction rule is the one of ``PerturbAndObserve`` (SEPIC sign
    convention: raising ``D`` lowers the panel voltage). The step size is
    ``gain * |dP/dD| / P``, clamped to ``[min_step, max_step]``. ``dP/dD`` is
    estimated as ``dP`` over the last applied step. Far from the MPP the slope
    is large and the step grows to ``max_step``. Near the MPP the slope goes to
    zero and the step shrinks to ``min_step``, which is the steady-state ripple.

    Dividing by ``P`` makes ``gain`` independent of the panel power rating.
    State is four scalars and ``step`` uses no loops or libraries.
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        min_step: float = 0.0005,
        max_step: float = 0.01,
        gain: float = 0.002,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
    ) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if not (math.isfinite(min_step) and min_step > 0):
            raise ValueError(f"min_step must be a finite positive number; got {min_step=}")
        if not (math.isfinite(max_step) and max_step >= min_step):
            raise ValueError(f"need max_step >= min_step; got {min_step=}, {max_step=}")
        if not (math.isfinite(gain) and gain > 0):
            raise ValueError(f"gain must be a finite positive number; got {gain=}")
        self._duty = max(min_duty, min(max_duty, initial_duty))
        self._min_step = min_step
        self._max_step = max_step
        self._gain = gain
        self._min = min_duty
        self._max = max_duty
        self._last_v: float | None = None
        self._last_p: float | None = None
        self._last_step = min_step

    def step(self, voltage: float, current: float) -> float:
        power = voltage * current

        if self._last_v is None or self._last_p is None:
            self._last_v = voltage
            self._last_p = power
            self._last_step = self._min_step
            self._duty = self._clamp(self._duty + self._last_step)
            return self._duty

        dv = voltage - self._last_v
        dp = power - self._last_p

        if dp == 0.0:
            direction = 0
        elif dp * dv > 0.0:
            direction = -1
        else:
            direction = +1

        # Floor on P avoids a divide by zero in the dark
        slope = abs(dp) / (self._last_step * max(power, 1e-6))
        size = max(self._min_step, min(self._max_step, self._gain * slope))

        self._duty = self._clamp(self._duty + direction * size)
        self._last_v = voltage
        self._last_p = power
        self._last_step = size
        return self._duty

    def _clamp(self, duty: float) -> float:
        return max(self._min, min(self._max, duty))

    @property
    def duty(self) -> float:
        return self._duty

    @property
    def last_step(self) -> float:
        """Size of the most recent duty perturbation."""
        return self._last_step
