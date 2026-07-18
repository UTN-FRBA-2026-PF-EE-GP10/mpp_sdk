"""Simple fuzzy-logic MPPT controller (local tracker) for a SEPIC converter."""

import math

from .base import MPPTAlgorithm

_EPSILON = 1e-9

# Five fuzzy sets, centres on the normalized universe [-1, 1]:
#   index 0..4 = NB, NS, ZE, PS, PB
_CENTERS = (-1.0, -0.5, 0.0, 0.5, 1.0)
_HALF_WIDTH = 0.5  # triangular membership half-base

# Rule base — output ΔD singleton centre for (error E, change-of-error dE).
# E = dP/dV: E > 0 ⇒ left of MPP (raise V ⇒ lower D), so ΔD opposes E.
# Rows: E = NB..PB.  Columns: dE = NB..PB.
_RULES = (
    (1.0, 1.0, 1.0, 0.5, 0.5),  # E NB → ΔD mostly PB (increase D)
    (1.0, 0.5, 0.5, 0.5, 0.0),  # E NS
    (0.5, 0.5, 0.0, -0.5, -0.5),  # E ZE → ΔD near zero at MPP
    (0.0, -0.5, -0.5, -0.5, -1.0),  # E PS
    (-0.5, -0.5, -1.0, -1.0, -1.0),  # E PB → ΔD mostly NB (decrease D)
)


def _memberships(x: float) -> list[float]:
    """Triangular membership of ``x`` across the five fuzzy sets."""
    return [max(0.0, 1.0 - abs(x - c) / _HALF_WIDTH) for c in _CENTERS]


class FuzzyLogic(MPPTAlgorithm):
    """Two-input fuzzy MPPT — a *local* tracker (not global MPPT).

    Inputs are the power-voltage slope ``E = ΔP/ΔV`` and its change
    ``dE = E − E_prev``, each normalized and fuzzified into five triangular
    sets (NB, NS, ZE, PS, PB). A 5×5 Mamdani rule base maps them to a duty
    step ``ΔD``, defuzzified by weighted average of output singletons.

    The behaviour is hill-climbing like P&O, but the step is *graduated*:
    far from the MPP (large ``|E|``) the step is large for fast convergence;
    near the MPP it shrinks, cutting steady-state oscillation. Because it
    only climbs the local gradient, it gets **trapped on a local maximum**
    under partial shading exactly like P&O — global MPPT needs an explicit
    scan stage on top.

    Sign convention matches the SEPIC (D↑ ⇒ V↓), identical to
    ``PerturbAndObserve``, so it is a drop-in replacement.

    Parameters
    ----------
    e_scale :
        Normalization for the slope ``ΔP/ΔV``. Larger ⇒ less aggressive.
    de_scale :
        Normalization for the change of slope.
    max_step :
        Duty change for a fully-saturated (±PB) rule output.
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        e_scale: float = 0.5,
        de_scale: float = 0.5,
        max_step: float = 0.01,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
    ) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if not (math.isfinite(max_step) and max_step > 0):
            raise ValueError(f"max_step must be a finite positive number; got {max_step=}")
        if e_scale <= 0 or de_scale <= 0:
            raise ValueError("e_scale and de_scale must be positive")
        self._duty = max(min_duty, min(max_duty, initial_duty))
        self._e_scale = e_scale
        self._de_scale = de_scale
        self._max_step = max_step
        self._min = min_duty
        self._max = max_duty
        self._last_v: float | None = None
        self._last_p: float | None = None
        self._last_e = 0.0

    def step(self, voltage: float, current: float) -> float:
        power = voltage * current

        if self._last_v is None or self._last_p is None:
            self._last_v = voltage
            self._last_p = power
            self._duty = self._clamp(self._duty + self._max_step)
            return self._duty

        dv = voltage - self._last_v
        dp = power - self._last_p
        e = dp / dv if abs(dv) > _EPSILON else 0.0
        de = e - self._last_e

        e_n = max(-1.0, min(1.0, e / self._e_scale))
        de_n = max(-1.0, min(1.0, de / self._de_scale))

        mu_e = _memberships(e_n)
        mu_de = _memberships(de_n)

        num = 0.0
        den = 0.0
        for i, me in enumerate(mu_e):
            if me == 0.0:
                continue
            for j, mde in enumerate(mu_de):
                if mde == 0.0:
                    continue
                w = me * mde
                num += w * _RULES[i][j]
                den += w

        dd_norm = num / den if den > 0.0 else 0.0
        self._duty = self._clamp(self._duty + dd_norm * self._max_step)

        self._last_v = voltage
        self._last_p = power
        self._last_e = e
        return self._duty

    def _clamp(self, duty: float) -> float:
        return max(self._min, min(self._max, duty))

    @property
    def duty(self) -> float:
        return self._duty
