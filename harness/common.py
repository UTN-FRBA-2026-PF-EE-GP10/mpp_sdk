"""Shared roster, run loop and irradiance-condition builder for the harness.

Every ``compare_*`` / ``animate`` / ``snapshot`` script used to declare its
own copy of the algorithm roster (in one of three incompatible shapes), its
own ``read -> step -> write`` measurement loop, and its own
``build_conditions`` helper. This module is the single place those live:
adding an algorithm to the harness is now a one-line change to
:func:`algorithm_specs`.
"""

from collections.abc import Callable, Iterable
from typing import NamedTuple

import numpy as np

import mpp_sdk
from harness.panel_config import make_dynamic_source, make_static_source, shaded_string


class AlgorithmSpec(NamedTuple):
    """One roster entry: display label, plot color, and a controller factory."""

    label: str
    color: str
    make: Callable[[float], object]


def algorithm_specs(
    rescan_period: int | None = None,
    pso_particles: int = 5,
) -> list[AlgorithmSpec]:
    """The five registered MPPT algorithms, configured for one call site.

    ``rescan_period`` and ``pso_particles`` map onto today's call sites:

    - static / dynamic / animate / snapshot: defaults ``(None, 5)``.
    - cyclic / noise: deployed config ``(1000, 8)``.
    - bank: detector-only ``(None, 8)`` (no periodic backstop - see
      ``compare_bank.py`` for why).
    """

    def _scan_and_track(d: float) -> object:
        if rescan_period is None:
            return mpp_sdk.ScanAndTrack(initial_duty=d)
        return mpp_sdk.ScanAndTrack(initial_duty=d, rescan_period=rescan_period)

    def _pso(d: float) -> object:
        if rescan_period is None:
            return mpp_sdk.ParticleSwarm(initial_duty=d, n_particles=pso_particles)
        return mpp_sdk.ParticleSwarm(
            initial_duty=d, n_particles=pso_particles, rescan_period=rescan_period
        )

    return [
        AlgorithmSpec("P&O", "tab:blue", lambda d: mpp_sdk.PerturbAndObserve(initial_duty=d)),
        AlgorithmSpec(
            "InCond", "tab:red", lambda d: mpp_sdk.IncrementalConductance(initial_duty=d)
        ),
        AlgorithmSpec("Fuzzy", "tab:green", lambda d: mpp_sdk.FuzzyLogic(initial_duty=d)),
        AlgorithmSpec("Scan&Track", "tab:purple", _scan_and_track),
        AlgorithmSpec("PSO", "tab:orange", _pso),
    ]


def final_point(
    make_ctl, panel, *, n_steps: int = 2000, initial_duty: float = 0.5
) -> tuple[float, float]:
    """Settle one controller against a static (no-dynamics) source and return
    its final ``(V, P)`` operating point.

    Shared by every comparison script that reports a single settled point
    rather than a transient trace (``compare_static.py``,
    ``compare_measured.py``) - this is the "static" analogue of
    :func:`run_schedule`.
    """
    src = make_static_source(panel=panel, initial_duty=initial_duty)
    ctl = make_ctl(initial_duty)
    v = i = 0.0
    for _ in range(n_steps):
        v, i = src.read()
        src.write(ctl.step(v, i))
    return v, v * i


class FinalPointResult(NamedTuple):
    """One algorithm's settled operating point, as returned by
    :func:`plot_pv_with_final_points` for the caller's own table print."""

    label: str
    v: float
    p: float
    eta: float


def plot_pv_with_final_points(
    ax,
    panel_factory: Callable[[], object],
    algorithms: Iterable[tuple[str, Callable[[float], object]]],
    colors,
    *,
    n_steps: int = 2000,
    initial_duty: float = 0.5,
    n_curve_points: int = 400,
    decimals: int = 2,
    mpp_label: str = "global MPP",
    legend_fontsize: int = 8,
) -> tuple[float, list[FinalPointResult]]:
    """Draw one P-V curve with the global MPP starred and every algorithm's
    settled final operating point marked - the shared plot body of
    `compare_static.py` and `compare_measured.py`.

    ``panel_factory`` is called once for the curve/MPP and once per
    algorithm (matching `final_point`'s signature) - **not** memoized here.
    Pass a factory that returns a fresh panel each call (as
    `compare_static.py`'s per-scenario ``panel_fn`` does) or one that
    always returns the same instance (``lambda: panel``, as
    `compare_measured.py` needs for a `MeasuredPanel` built once from a
    `CurveRecord`) depending on which behavior the call site needs - this
    function does not decide that for you.

    Sets everything about the axes except its title (callers' title calls
    differ in text and kwargs) and does not print or save anything -
    returns ``(p_mpp, results)`` so the caller can print its own table.
    """
    panel = panel_factory()
    v_curve, i_curve = panel.iv_curve(n=n_curve_points)
    p_curve = v_curve * i_curve
    v_mpp, _, p_mpp = panel.mpp()

    ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
    ax.plot(v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"{mpp_label} ({p_mpp:.{decimals}f} W)")

    results = []
    for (label, make_ctl), color in zip(algorithms, colors, strict=False):
        v_f, p_f = final_point(
            make_ctl, panel_factory(), n_steps=n_steps, initial_duty=initial_duty
        )
        eta = p_f / p_mpp if p_mpp else 0.0
        ax.plot(v_f, p_f, "o", color=color, ms=10, zorder=4, label=f"{label}: {p_f:.{decimals}f} W")
        results.append(FinalPointResult(label, v_f, p_f, eta))

    ax.set_xlabel("Voltage [V]")
    ax.set_ylabel("Power [W]")
    ax.legend(fontsize=legend_fontsize)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    return p_mpp, results


def build_conditions(irradiance_pairs: Iterable[tuple[float, float]]):
    """Tabulate each distinct irradiance pair once: ``{irr: (panel, p_mpp)}``."""
    conditions = {}
    for irr in irradiance_pairs:
        if irr not in conditions:
            panel = mpp_sdk.TabulatedPanel(shaded_string(irr))
            conditions[irr] = (panel, panel.mpp()[2])
    return conditions


def run_schedule(
    make_ctl,
    schedule,
    conditions,
    *,
    initial_duty: float,
    noise_v_std: float = 0.0,
    noise_i_std: float = 0.0,
    noise_seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Run one controller through a schedule; returns the TRUE ``(v, i, d)`` traces.

    Builds a fresh ``DynamicSimulatedSource`` from the first schedule entry's
    panel (``load_resistance=10.0``, control-period ``dt``), swaps the panel
    at every schedule step (``irr, n_steps, _``) via ``set_panel``, and steps
    the controller for ``n_steps``. ``initial_duty`` seeds both the source and
    the controller - callers vary it per scenario (e.g. ``compare_bank``'s
    "shade trap" starts at 0.15).

    When ``noise_v_std`` / ``noise_i_std`` are nonzero, the controller sees a
    ``NoisySource``-wrapped reading while the returned arrays record the true
    (noise-free) plant values - exactly as ``compare_noise.py`` did.
    ``NoisySource.read()`` is idempotent between writes (it caches its noisy
    sample, drawn once per ``write()``), so duty is written through the
    wrapper (``(noisy or inner).write(d)``) rather than through ``inner``
    directly - that's what advances the noise stream for the next step.
    """
    inner = make_dynamic_source(
        panel=conditions[schedule[0][0]][0],
        load_resistance=10.0,
        initial_duty=initial_duty,
        tabulate=False,
    )
    noisy = None
    if noise_v_std or noise_i_std:
        noisy = mpp_sdk.NoisySource(inner, v_std=noise_v_std, i_std=noise_i_std, seed=noise_seed)

    ctl = make_ctl(initial_duty)
    n_total = sum(n for _, n, _ in schedule)
    vs, is_, ds = np.empty(n_total), np.empty(n_total), np.empty(n_total)
    k = 0
    for irr, n_steps, _ in schedule:
        inner.set_panel(conditions[irr][0])
        for _ in range(n_steps):
            v_true, i_true = inner.read()
            v_ctl, i_ctl = noisy.read() if noisy is not None else (v_true, i_true)
            d = ctl.step(v_ctl, i_ctl)
            (noisy or inner).write(d)
            vs[k], is_[k], ds[k] = v_true, i_true, d
            k += 1
    return vs, is_, ds


__all__ = ["AlgorithmSpec", "algorithm_specs", "build_conditions", "final_point", "run_schedule"]
