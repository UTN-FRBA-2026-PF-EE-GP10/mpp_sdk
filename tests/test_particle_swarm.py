"""Unit tests for the ParticleSwarm global MPPT controller."""

import pytest

import mpp_sdk
from mpp_sdk.algorithms.particle_swarm import ParticleSwarm

pvlib = pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

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
# Interface
# ------------------------------------------------------------------


def test_is_mppt_algorithm():
    assert isinstance(ParticleSwarm(), mpp_sdk.MPPTAlgorithm)


def test_exported_from_top_level():
    assert mpp_sdk.ParticleSwarm is ParticleSwarm
