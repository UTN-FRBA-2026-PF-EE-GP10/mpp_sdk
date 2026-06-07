"""Unit tests for the preliminary MPPT metrics."""

import numpy as np
import pytest

from mpp_sdk import metrics

# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def test_empty_power_raises():
    with pytest.raises(ValueError):
        metrics.tracking_efficiency([], 10.0)


def test_nonpositive_pmpp_raises():
    with pytest.raises(ValueError):
        metrics.tracking_efficiency([1.0, 2.0], 0.0)


# ------------------------------------------------------------------
# tracking / final efficiency
# ------------------------------------------------------------------


def test_tracking_efficiency_perfect():
    p = [10.0] * 50
    assert metrics.tracking_efficiency(p, 10.0) == pytest.approx(1.0)


def test_tracking_efficiency_includes_transient():
    # ramps 0→10 then holds 10; mean < 10 so η < 1
    p = list(np.linspace(0, 10, 50)) + [10.0] * 50
    eta = metrics.tracking_efficiency(p, 10.0)
    assert 0.5 < eta < 1.0


def test_final_efficiency_ignores_transient():
    p = [0.0] * 100 + [9.9] * 100
    assert metrics.final_efficiency(p, 10.0, last_n=100) == pytest.approx(0.99)


# ------------------------------------------------------------------
# settling time
# ------------------------------------------------------------------


def test_settling_time_basic():
    # outside band for 30 steps, then inside forever
    p = [5.0] * 30 + [9.8] * 70
    t = metrics.settling_time(p, 10.0, dt=1.0, band=0.05)
    assert t == pytest.approx(30.0)


def test_settling_time_respects_dt():
    p = [5.0] * 30 + [9.8] * 70
    t = metrics.settling_time(p, 10.0, dt=0.001, band=0.05)
    assert t == pytest.approx(0.030)


def test_settling_time_never_settles():
    p = [5.0] * 100  # trapped below band
    assert metrics.settling_time(p, 10.0) is None


def test_settling_time_immediate():
    p = [10.0] * 50
    assert metrics.settling_time(p, 10.0) == pytest.approx(0.0)


def test_settling_time_none_if_outside_at_end():
    p = [9.9] * 50 + [5.0]  # drops out on the last sample
    assert metrics.settling_time(p, 10.0) is None


# ------------------------------------------------------------------
# ripple / overshoot / trap depth
# ------------------------------------------------------------------


def test_steady_state_ripple():
    p = [0.0] * 50 + [9.0, 11.0] * 25  # ±1 around 10 in the tail
    assert metrics.steady_state_ripple(p, last_n=50) == pytest.approx(2.0)


def test_overshoot_present():
    p = [0.0, 12.0] + [10.0] * 100  # spikes to 12, settles at 10
    assert metrics.overshoot(p, last_n=100) == pytest.approx(0.2, abs=1e-3)


def test_overshoot_absent_when_monotonic():
    p = list(np.linspace(0, 10, 100))
    assert metrics.overshoot(p, last_n=10) == pytest.approx(0.0, abs=0.2)


def test_trap_depth_global_found():
    p = [9.95] * 100
    assert metrics.trap_depth(p, 10.0) == pytest.approx(0.995)


def test_trap_depth_trapped():
    p = [8.0] * 100  # stuck on local peak at 80% of global
    assert metrics.trap_depth(p, 10.0) == pytest.approx(0.8)


# ------------------------------------------------------------------
# summarize
# ------------------------------------------------------------------


def test_summarize_keys():
    p = [0.0] * 20 + [10.0] * 80
    out = metrics.summarize(p, 10.0)
    assert set(out) == {
        "tracking_efficiency",
        "final_efficiency",
        "settling_time",
        "steady_state_ripple",
        "overshoot",
    }
