"""Unit tests for the FuzzyLogic MPPT controller."""

import math

import pytest

import mpp_sdk
from mpp_sdk.algorithms.fuzzy import FuzzyLogic, _memberships

pvlib = pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel  # noqa: E402

# ------------------------------------------------------------------
# Construction / validation
# ------------------------------------------------------------------


def test_invalid_duty_bounds():
    with pytest.raises(ValueError):
        FuzzyLogic(min_duty=0.9, max_duty=0.1)


def test_invalid_max_step():
    with pytest.raises(ValueError):
        FuzzyLogic(max_step=-0.01)


def test_invalid_scales():
    with pytest.raises(ValueError):
        FuzzyLogic(e_scale=0.0)


def test_initial_duty_clamped():
    ctl = FuzzyLogic(initial_duty=2.0, min_duty=0.1, max_duty=0.9)
    assert ctl.duty == pytest.approx(0.9)


# ------------------------------------------------------------------
# Membership function sanity
# ------------------------------------------------------------------


def test_memberships_partition_of_unity_interior():
    # Triangular sets overlapping by half-width sum to 1 in the interior.
    for x in (-0.75, -0.3, 0.0, 0.4, 0.9):
        assert math.isclose(sum(_memberships(x)), 1.0, abs_tol=1e-9)


def test_memberships_peak_at_centre():
    mu = _memberships(0.0)  # ZE centre
    assert mu[2] == pytest.approx(1.0)
    assert mu[0] == 0.0 and mu[4] == 0.0


# ------------------------------------------------------------------
# Convergence against the realistic panel
# ------------------------------------------------------------------


def _source(initial_duty=0.5):
    panel = PvlibPanelModel.hissuma_psf10mono()
    return mpp_sdk.SimulatedSource(
        panel,
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    ), panel


def test_fuzzy_converges_within_two_percent():
    src, panel = _source()
    ctl = FuzzyLogic(initial_duty=src.duty)
    for _ in range(1500):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = panel.mpp()
    assert (v * i) / p_mpp > 0.98


def test_fuzzy_converges_from_high_duty():
    src, panel = _source(initial_duty=0.85)
    ctl = FuzzyLogic(initial_duty=0.85)
    for _ in range(1500):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = panel.mpp()
    assert (v * i) / p_mpp > 0.98


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_is_mppt_algorithm():
    assert isinstance(FuzzyLogic(), mpp_sdk.MPPTAlgorithm)


def test_step_returns_float_and_stays_in_bounds():
    ctl = FuzzyLogic()
    d = ctl.step(20.0, 0.7)
    assert isinstance(d, float)
    for _ in range(20):
        d = ctl.step(20.0, 0.7)
        assert 0.0 < d < 1.0


def test_exported_from_top_level():
    assert mpp_sdk.FuzzyLogic is FuzzyLogic
