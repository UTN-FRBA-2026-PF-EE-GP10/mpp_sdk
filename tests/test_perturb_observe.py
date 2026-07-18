"""Unit tests for PerturbAndObserve."""

import math

import pytest

import mpp_sdk
from mpp_sdk.algorithms.perturb_observe import PerturbAndObserve

# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_invalid_duty_bounds():
    with pytest.raises(ValueError):
        PerturbAndObserve(min_duty=0.9, max_duty=0.1)


def test_invalid_step_size_negative():
    with pytest.raises(ValueError):
        PerturbAndObserve(step_size=-0.01)


def test_invalid_step_size_nan():
    with pytest.raises(ValueError):
        PerturbAndObserve(step_size=float("nan"))


def test_initial_duty_clamped():
    ctl = PerturbAndObserve(initial_duty=2.0, min_duty=0.1, max_duty=0.9)
    assert ctl.duty == pytest.approx(0.9)


# ------------------------------------------------------------------
# First step
# ------------------------------------------------------------------


def test_first_step_moves_up_by_step_size():
    ctl = PerturbAndObserve(initial_duty=0.5)
    d = ctl.step(14.0, 0.72)
    assert d == pytest.approx(0.505)
    assert ctl.duty == pytest.approx(0.505)


# ------------------------------------------------------------------
# Decision table
# ------------------------------------------------------------------


def _primed(**kwargs):
    """A P&O controller after its priming (first) step, ready for a decision step."""
    ctl = PerturbAndObserve(initial_duty=0.5, step_size=0.01, **kwargs)
    ctl.step(10.0, 1.0)  # priming step: sets _last_v/_last_p, duty -> 0.51
    return ctl


def test_dp_positive_dv_positive_decreases_duty():
    ctl = _primed()
    before = ctl.duty
    ctl.step(11.0, 1.1)  # dv > 0, dp > 0
    assert ctl.duty == pytest.approx(before - 0.01)


def test_dp_positive_dv_negative_increases_duty():
    ctl = _primed()
    before = ctl.duty
    ctl.step(9.0, 1.2)  # dv < 0, dp > 0
    assert ctl.duty == pytest.approx(before + 0.01)


def test_dp_negative_dv_positive_increases_duty():
    ctl = _primed()
    before = ctl.duty
    ctl.step(11.0, 0.5)  # dv > 0, dp < 0
    assert ctl.duty == pytest.approx(before + 0.01)


def test_dp_zero_holds_duty():
    ctl = _primed()
    before = ctl.duty
    ctl.step(11.0, 10.0 / 11.0)  # power unchanged: 10.0 * 1.0 == 11.0 * (10/11)
    assert ctl.duty == pytest.approx(before)


# ------------------------------------------------------------------
# Clamping
# ------------------------------------------------------------------


def test_duty_never_exceeds_bounds_on_repeated_increase():
    ctl = PerturbAndObserve(initial_duty=0.5, step_size=0.01, min_duty=0.05, max_duty=0.95)
    ctl.step(10.0, 1.0)  # priming
    # Repeated dv<0, dp>0 decisions push duty up every time.
    v, p = 9.0, 1.2
    for _ in range(200):
        ctl.step(v, p)
        v -= 0.01
        p += 0.01
        assert 0.05 <= ctl.duty <= 0.95
    assert ctl.duty == pytest.approx(0.95)


def test_duty_never_exceeds_bounds_on_repeated_decrease():
    ctl = PerturbAndObserve(initial_duty=0.5, step_size=0.01, min_duty=0.05, max_duty=0.95)
    ctl.step(10.0, 1.0)  # priming
    # Repeated dv>0, dp>0 decisions push duty down every time.
    v, p = 11.0, 1.1
    for _ in range(200):
        ctl.step(v, p)
        v += 0.01
        p += 0.01
        assert 0.05 <= ctl.duty <= 0.95
    assert ctl.duty == pytest.approx(0.05)


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


def test_pno_converges_from_low_duty():
    src = _make_source(initial_duty=0.1)
    ctl = PerturbAndObserve(initial_duty=src.duty, step_size=0.005)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = mpp_sdk.IdealSingleDiode().mpp()
    assert (v * i) / p_mpp > 0.99


def test_pno_converges_from_high_duty():
    src = _make_source(initial_duty=0.9)
    ctl = PerturbAndObserve(initial_duty=src.duty, step_size=0.005)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = mpp_sdk.IdealSingleDiode().mpp()
    assert (v * i) / p_mpp > 0.99


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_pno_is_mppt_algorithm():
    assert isinstance(PerturbAndObserve(), mpp_sdk.MPPTAlgorithm)


def test_pno_exported_from_top_level():
    assert mpp_sdk.PerturbAndObserve is PerturbAndObserve


def test_step_returns_float():
    ctl = PerturbAndObserve()
    result = ctl.step(14.0, 0.72)
    assert isinstance(result, float)
    result2 = ctl.step(13.9, 0.73)
    assert isinstance(result2, float)


def test_duty_property_matches_last_step():
    ctl = PerturbAndObserve(initial_duty=0.5)
    d = ctl.step(14.0, 0.72)
    assert math.isclose(ctl.duty, d)
