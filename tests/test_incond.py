"""Unit tests for IncrementalConductance."""

import math

import pytest

import mpp_sdk
from mpp_sdk.algorithms.incremental_conductance import IncrementalConductance

# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_invalid_duty_bounds():
    with pytest.raises(ValueError):
        IncrementalConductance(min_duty=0.9, max_duty=0.1)


def test_invalid_step_size():
    with pytest.raises(ValueError):
        IncrementalConductance(step_size=-0.01)


def test_initial_duty_clamped():
    ctl = IncrementalConductance(initial_duty=2.0, min_duty=0.1, max_duty=0.9)
    assert ctl.duty == pytest.approx(0.9)


# ------------------------------------------------------------------
# Convergence against SimulatedSource
# ------------------------------------------------------------------


def _make_source(initial_duty=0.1):
    return mpp_sdk.SimulatedSource(
        mpp_sdk.IdealSingleDiode(),
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def test_incond_converges_within_one_percent_of_mpp():
    src = _make_source()
    ctl = IncrementalConductance(initial_duty=src.duty, step_size=0.005)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = mpp_sdk.IdealSingleDiode().mpp()
    assert (v * i) / p_mpp > 0.99


def test_incond_converges_from_high_duty():
    src = _make_source(initial_duty=0.9)
    ctl = IncrementalConductance(initial_duty=0.9, step_size=0.005)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = mpp_sdk.IdealSingleDiode().mpp()
    assert (v * i) / p_mpp > 0.99


# ------------------------------------------------------------------
# Steady-state oscillation is bounded
# ------------------------------------------------------------------


def test_steady_state_oscillation_below_2pct():
    """After convergence, power must stay within 2 % of MPP."""
    src = _make_source()
    ctl = IncrementalConductance(initial_duty=src.duty, step_size=0.005)
    # warm-up
    for _ in range(600):
        v, i = src.read()
        src.write(ctl.step(v, i))
    _, _, p_mpp = mpp_sdk.IdealSingleDiode().mpp()
    # measure oscillation over 100 steps
    powers = []
    for _ in range(100):
        v, i = src.read()
        src.write(ctl.step(v, i))
        powers.append(v * i)
    assert min(powers) / p_mpp > 0.98


# ------------------------------------------------------------------
# Drop-in replacement for P&O (same interface)
# ------------------------------------------------------------------


def test_incond_is_mppt_algorithm():
    assert isinstance(IncrementalConductance(), mpp_sdk.MPPTAlgorithm)


def test_incond_same_interface_as_pno():
    """InCond and P&O must be interchangeable from the caller's perspective."""
    for ctl_cls in [mpp_sdk.PerturbAndObserve, IncrementalConductance]:
        src2 = _make_source()
        ctl = ctl_cls(initial_duty=src2.duty, step_size=0.005)
        for _ in range(10):
            v, i = src2.read()
            d = ctl.step(v, i)
            assert 0.0 < d < 1.0
            src2.write(d)


# ------------------------------------------------------------------
# Top-level re-export
# ------------------------------------------------------------------


def test_incond_exported_from_top_level():
    assert mpp_sdk.IncrementalConductance is IncrementalConductance


def test_step_returns_float():
    ctl = IncrementalConductance()
    result = ctl.step(14.0, 0.72)
    assert isinstance(result, float)
    result2 = ctl.step(13.9, 0.73)
    assert isinstance(result2, float)


def test_duty_property_matches_last_step():
    ctl = IncrementalConductance(initial_duty=0.5)
    d = ctl.step(14.0, 0.72)
    assert math.isclose(ctl.duty, d)
