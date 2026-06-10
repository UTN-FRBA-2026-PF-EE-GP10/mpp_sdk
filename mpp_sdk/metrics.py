"""Preliminary MPPT comparison metrics.

These operate on a recorded power trace ``P[k] = V_k · I_k`` produced by running
a controller against a source, plus the known reference MPP power. They are the
quantities the comparison harness and the paper report. The set is deliberately
small and will grow as the methodology firms up; see ``docs/rationale.md``.

Conventions
-----------
- ``power`` is a 1-D sequence of instantaneous power, one sample per control step.
- ``dt`` is the control period; pass it to get times in real units (ms, s),
  otherwise results are in *steps*.
- ``p_mpp`` is the reference maximum power (global MPP for the scenario).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "tracking_efficiency",
    "energy_efficiency",
    "final_efficiency",
    "settling_time",
    "steady_state_ripple",
    "overshoot",
    "trap_depth",
    "summarize",
    "METHODOLOGY_WARNING",
    "print_methodology_warning",
]

METHODOLOGY_WARNING = """\
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠  PRELIMINARY METRICS — THE COMPARISON IS NOT YET VALID  ⚠                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  These numbers do NOT yet measure tracking performance correctly. Treat them  ║
║  as a smoke test, not a result. More investigation is needed before any        ║
║  conclusion is drawn for the paper.                                            ║
║                                                                                ║
║  Known issues:                                                                  ║
║   • Measured from a FIXED start in STEADY conditions — this rewards luck in     ║
║     the initial operating point, not real tracking ability.                    ║
║   • Under arbitrary irradiance changes, some (possibly all) algorithms fail     ║
║     to re-acquire the MPP — this is not captured here.                          ║
║   • In full sun every algorithm should sit at ~100 % (ripple-limited and        ║
║     negligible), so this scenario does not discriminate between them.           ║
║                                                                                ║
║  A valid efficiency measurement must be DYNAMIC, over a cyclic irradiance       ║
║  profile, e.g.:  full sun → panel A shaded → full → panel B shaded →            ║
║  both shaded → full → (repeat).  Tracking efficiency = captured energy /        ║
║  ideal energy integrated over the whole profile.                               ║
║                                                                                ║
║  That measurement exists now: run `harness/compare_cyclic.py`, which scores     ║
║  each algorithm with `metrics.energy_efficiency` against the time-varying      ║
║  global MPP. Prefer its numbers over the ones printed here.                    ║
╚══════════════════════════════════════════════════════════════════════════════╝"""


def print_methodology_warning() -> None:
    """Print the big preliminary-metrics warning banner (see ``METHODOLOGY_WARNING``)."""
    print(METHODOLOGY_WARNING)


def _as_array(power: Sequence[float]) -> np.ndarray:
    a = np.asarray(power, dtype=float)
    if a.ndim != 1 or a.size == 0:
        raise ValueError("power must be a non-empty 1-D sequence")
    return a


def tracking_efficiency(power: Sequence[float], p_mpp: float) -> float:
    r"""Energy-based tracking efficiency over the whole trace.

    $$\eta = \frac{\langle P \rangle}{P_\text{mpp}}
           = \frac{1}{N P_\text{mpp}} \sum_{k} P_k.$$

    This is the headline MPPT metric: the fraction of the ideally-available
    energy the controller actually captured over the run (including the
    transient). ``1.0`` is perfect.
    """
    p = _as_array(power)
    if p_mpp <= 0:
        raise ValueError("p_mpp must be > 0")
    return float(p.mean() / p_mpp)


def energy_efficiency(power: Sequence[float], p_mpp: float | Sequence[float]) -> float:
    r"""Captured / ideal energy with a (possibly time-varying) MPP reference.

    $$\eta_E = \frac{\sum_k P_k}{\sum_k P_{\text{mpp},k}}.$$

    This is the valid dynamic measurement the methodology warning asks for:
    ``p_mpp`` may be an array giving the ideal (global-MPP) power at *every
    step* — e.g. a staircase following a cyclic shading profile — so the
    controller is graded on the energy it captured out of the energy that was
    actually available at each instant. With a scalar ``p_mpp`` it reduces to
    :func:`tracking_efficiency`.
    """
    p = _as_array(power)
    ref = np.broadcast_to(np.asarray(p_mpp, dtype=float), p.shape)
    if not np.all(ref > 0):
        raise ValueError("p_mpp must be > 0 everywhere")
    return float(p.sum() / ref.sum())


def final_efficiency(power: Sequence[float], p_mpp: float, last_n: int = 100) -> float:
    """Steady-state efficiency: mean of the last ``last_n`` samples over ``p_mpp``.

    Ignores the startup transient, so it reflects where the controller *settled*
    — close to 1.0 for a converged local tracker, lower for one trapped on a
    local maximum.
    """
    p = _as_array(power)
    if p_mpp <= 0:
        raise ValueError("p_mpp must be > 0")
    n = min(last_n, p.size)
    return float(p[-n:].mean() / p_mpp)


def settling_time(
    power: Sequence[float],
    p_mpp: float,
    dt: float = 1.0,
    band: float = 0.05,
) -> float | None:
    """Time to enter — and stay within — ``±band`` of the MPP.

    Returns the time (in units of ``dt``) of the first sample after which the
    whole trace remains inside ``[(1-band)·p_mpp, ∞)``. Returns ``None`` if the
    controller never settles within the band (e.g. trapped below it).
    """
    p = _as_array(power)
    if p_mpp <= 0:
        raise ValueError("p_mpp must be > 0")
    threshold = (1.0 - band) * p_mpp
    inside = p >= threshold
    if not inside.any():
        return None
    # Find the last time it was outside; settling is the sample right after.
    outside_idx = np.where(~inside)[0]
    if outside_idx.size == 0:
        return 0.0
    last_outside = int(outside_idx[-1])
    if last_outside == p.size - 1:
        return None  # still outside at the end → never settled
    return float((last_outside + 1) * dt)


def steady_state_ripple(power: Sequence[float], last_n: int = 100) -> float:
    """Peak-to-peak power oscillation over the last ``last_n`` samples [W]."""
    p = _as_array(power)
    n = min(last_n, p.size)
    tail = p[-n:]
    return float(tail.max() - tail.min())


def overshoot(power: Sequence[float], last_n: int = 100) -> float:
    """Relative overshoot of the peak power above the settled value.

    $$\\text{OS} = \\frac{\\max_k P_k - P_\\text{settled}}{P_\\text{settled}},$$

    where ``P_settled`` is the mean of the last ``last_n`` samples. ``0`` if the
    response is monotonic (no overshoot).
    """
    p = _as_array(power)
    n = min(last_n, p.size)
    settled = p[-n:].mean()
    if settled <= 0:
        return 0.0
    return float(max(0.0, p.max() - settled) / settled)


def trap_depth(power: Sequence[float], p_global: float, last_n: int = 100) -> float:
    """Settled power as a fraction of the *global* MPP.

    $$\\text{depth} = \\frac{P_\\text{settled}}{P_\\text{global}}.$$

    ``1.0`` means the global peak was found; ``< 1.0`` quantifies how deep a
    local-maximum trap the controller fell into under partial shading.
    """
    return final_efficiency(power, p_global, last_n=last_n)


def summarize(
    power: Sequence[float],
    p_mpp: float,
    dt: float = 1.0,
    last_n: int = 100,
    band: float = 0.05,
) -> dict[str, float | None]:
    """Convenience: all metrics in one dict, ready for a results table."""
    return {
        "tracking_efficiency": tracking_efficiency(power, p_mpp),
        "final_efficiency": final_efficiency(power, p_mpp, last_n),
        "settling_time": settling_time(power, p_mpp, dt, band),
        "steady_state_ripple": steady_state_ripple(power, last_n),
        "overshoot": overshoot(power, last_n),
    }
