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
from harness.panel_config import make_dynamic_source, shaded_string


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
    (noise-free) plant values - exactly as ``compare_noise.py`` did. The true
    reading is always taken first (``inner.read()``) and the noisy one second
    (``noisy.read()``), matching the original read order so the noise RNG
    stream stays identical run to run.
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
            inner.write(d)
            vs[k], is_[k], ds[k] = v_true, i_true, d
            k += 1
    return vs, is_, ds


__all__ = ["AlgorithmSpec", "algorithm_specs", "build_conditions", "run_schedule"]
