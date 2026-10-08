"""Fixed-step Incremental Conductance MPPT for a SEPIC converter."""

import math

from .base import MPPTAlgorithm

_EPSILON = 1e-9  # guard against zero ΔV / zero ΔI comparisons


class IncrementalConductance(MPPTAlgorithm):
    """Classical fixed-step Incremental Conductance (InCond).

    At the MPP the power–voltage curve is flat, so ``dP/dV = 0``.
    Expanding ``P = V·I``:

        dP/dV = I + V·dI/dV = 0  →  dI/dV = −I/V

    The algorithm compares the incremental conductance ``ΔI/ΔV`` against
    the instantaneous conductance ``−I/V`` to decide which way to move:

    * ``ΔI/ΔV > −I/V``  →  left of MPP  → increase V → **decrease** D
    * ``ΔI/ΔV < −I/V``  →  right of MPP → decrease V → **increase** D
    * ``ΔI/ΔV ≈ −I/V``  →  at MPP       → hold D

    Division by ΔV is avoided by comparing ``(ΔI·V + I·ΔV)`` and ``ΔV``
    for sign agreement: same sign ↔ left of MPP.

    The SEPIC sign convention (D↑ → V↓) is identical to that of
    ``PerturbAndObserve``; InCond is a drop-in replacement.
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        step_size: float = 0.001,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
    ) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if not (math.isfinite(step_size) and step_size > 0):
            raise ValueError(f"step_size must be a finite positive number; got {step_size=}")
        self._duty = max(min_duty, min(max_duty, initial_duty))
        self._step = step_size
        self._min = min_duty
        self._max = max_duty
        self._last_v: float | None = None
        self._last_i: float | None = None

    def step(self, voltage: float, current: float) -> float:
        v, i = voltage, current

        if self._last_v is None:
            self._last_v = v
            self._last_i = i
            self._duty = self._clamp(self._duty + self._step)
            return self._duty

        dv = v - self._last_v
        di = i - self._last_i

        if abs(dv) < _EPSILON:
            # ΔV ≈ 0: use ΔI alone (dP/dV ≈ I·dI/|dV|→ sign follows ΔI)
            if abs(di) < _EPSILON:
                direction = 0  # stationary — hold
            elif di > 0:
                direction = -1  # current still rising → left of MPP
            else:
                direction = +1  # current falling → right of MPP
        else:
            # cond = ΔI·V + I·ΔV  (= (ΔI/ΔV + I/V) · ΔV · V)
            # same sign as ΔV  ↔  g_diff > 0  ↔  left of MPP → decrease D
            cond = di * v + i * dv
            if cond * dv > 0:
                direction = -1
            elif cond * dv < 0:
                direction = +1
            else:
                direction = 0

        self._duty = self._clamp(self._duty + direction * self._step)
        self._last_v = v
        self._last_i = i
        return self._duty

    def _clamp(self, duty: float) -> float:
        return max(self._min, min(self._max, duty))

    @property
    def duty(self) -> float:
        return self._duty
