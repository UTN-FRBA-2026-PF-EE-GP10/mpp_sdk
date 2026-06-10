"""Unit tests for the ParticleSwarm global MPPT controller."""

import pytest

import mpp_sdk
from mpp_sdk.algorithms.particle_swarm import ParticleSwarm

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel  # noqa: E402
from mpp_sdk.models.string import PvString  # noqa: E402

# ------------------------------------------------------------------
# Construction / validation
# ------------------------------------------------------------------


def test_invalid_duty_bounds():
    with pytest.raises(ValueError):
        ParticleSwarm(min_duty=0.9, max_duty=0.1)


def test_too_few_particles():
    with pytest.raises(ValueError):
        ParticleSwarm(n_particles=1)


def test_invalid_max_iterations():
    with pytest.raises(ValueError):
        ParticleSwarm(max_iterations=0)


def test_invalid_rescan_period():
    with pytest.raises(ValueError):
        ParticleSwarm(rescan_period=0)


def test_starts_optimizing():
    assert ParticleSwarm().optimizing


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _shaded_string():
    return PvString(
        [
            PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0),
            PvlibPanelModel.hissuma_psf10mono(irradiance=400.0),
        ]
    )


def _run(panel, ctl, steps):
    src = mpp_sdk.SimulatedSource(
        panel, mpp_sdk.SEPICConverter(), load_resistance=10.0, initial_duty=ctl.duty
    )
    v = i = 0.0
    for _ in range(steps):
        v, i = src.read()
        src.write(ctl.step(v, i))
    return v, i


# ------------------------------------------------------------------
# Global MPP search
# ------------------------------------------------------------------


def test_reaches_global_mpp_under_shade():
    panel = _shaded_string()
    _, _, p_global = panel.mpp()
    v, i = _run(panel, ParticleSwarm(n_particles=6, max_iterations=5), 800)
    assert (v * i) / p_global > 0.97


def test_beats_pno_when_pno_is_trapped():
    panel = _shaded_string()
    _, _, p_global = panel.mpp()
    v_p, i_p = _run(panel, mpp_sdk.PerturbAndObserve(initial_duty=0.1, step_size=0.004), 800)
    v_s, i_s = _run(panel, ParticleSwarm(initial_duty=0.1, n_particles=6, max_iterations=5), 800)
    eta_pno = (v_p * i_p) / p_global
    eta_pso = (v_s * i_s) / p_global
    assert eta_pso > 0.97
    assert eta_pso > eta_pno


def test_reaches_mpp_full_sun():
    panel = PvlibPanelModel.hissuma_psf10mono()
    _, _, p_mpp = panel.mpp()
    v, i = _run(panel, ParticleSwarm(n_particles=5, max_iterations=4), 600)
    assert (v * i) / p_mpp > 0.98


def test_switches_to_tracking():
    ctl = ParticleSwarm(n_particles=4, max_iterations=2)
    panel = PvlibPanelModel.hissuma_psf10mono()
    src = mpp_sdk.SimulatedSource(panel, mpp_sdk.SEPICConverter(), load_resistance=10.0)
    for _ in range(20):  # > n_particles * max_iterations
        v, i = src.read()
        src.write(ctl.step(v, i))
    assert not ctl.optimizing


def test_reproducible_with_seed():
    panel = _shaded_string()
    a = _run(panel, ParticleSwarm(seed=42), 300)
    b = _run(_shaded_string(), ParticleSwarm(seed=42), 300)
    assert a == pytest.approx(b)


# ------------------------------------------------------------------
# Re-acquisition after a shading change (change-detection restart)
# ------------------------------------------------------------------


def _full_string():
    return PvString(
        [
            PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0),
            PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0),
        ]
    )


def _run_dynamic(src, ctl, steps):
    """Drive the dynamic source; return whether the swarm was seen optimizing."""
    optimized = False
    for _ in range(steps):
        v, i = src.read()
        src.write(ctl.step(v, i))
        optimized = optimized or ctl.optimizing
    return optimized


def _make_dynamic(panel, initial_duty):
    return mpp_sdk.DynamicSimulatedSource(
        panel=mpp_sdk.TabulatedPanel(panel),
        converter=mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def test_reacquires_global_mpp_after_shading_change():
    # 8 particles: the first (coarse-scan) iteration must be fine enough to
    # locate the global basin despite the capacitor lag on each fitness
    # sample — at 6 particles the re-acquisition succeeds for only ~60 % of
    # seeds on this rig.
    shaded = mpp_sdk.TabulatedPanel(_shaded_string())
    ctl = ParticleSwarm(n_particles=8, max_iterations=5)
    src = _make_dynamic(_full_string(), ctl.duty)
    _run_dynamic(src, ctl, 600)
    assert not ctl.optimizing  # converged on the full-sun MPP

    src.set_panel(shaded)
    restarted = _run_dynamic(src, ctl, 800)
    assert restarted  # the power change re-seeded the swarm
    v, i = src.read()
    assert (v * i) / shaded.mpp()[2] > 0.95


def test_periodic_rescan_reoptimizes():
    ctl = ParticleSwarm(n_particles=4, max_iterations=2, restart_threshold=None, rescan_period=50)
    panel = PvlibPanelModel.hissuma_psf10mono()
    src = mpp_sdk.SimulatedSource(panel, mpp_sdk.SEPICConverter(), load_resistance=10.0)
    for _ in range(20):  # > n_particles * max_iterations — converge and hand off
        v, i = src.read()
        src.write(ctl.step(v, i))
    assert not ctl.optimizing
    reoptimized = False
    for _ in range(60):  # > rescan_period tracking steps
        v, i = src.read()
        src.write(ctl.step(v, i))
        reoptimized = reoptimized or ctl.optimizing
    assert reoptimized  # the periodic backstop re-ran the search unprompted


def test_restart_disabled_never_reoptimizes():
    ctl = ParticleSwarm(n_particles=6, max_iterations=5, restart_threshold=None)
    src = _make_dynamic(_full_string(), ctl.duty)
    _run_dynamic(src, ctl, 600)
    assert not ctl.optimizing

    src.set_panel(mpp_sdk.TabulatedPanel(_shaded_string()))
    restarted = _run_dynamic(src, ctl, 800)
    assert not restarted  # the old behaviour: plain P&O after convergence


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_is_mppt_algorithm():
    assert isinstance(ParticleSwarm(), mpp_sdk.MPPTAlgorithm)


def test_exported_from_top_level():
    assert mpp_sdk.ParticleSwarm is ParticleSwarm
