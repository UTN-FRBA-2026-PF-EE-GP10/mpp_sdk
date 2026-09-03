"""Unit tests for MeasuredPanel."""

import numpy as np
import pytest

from mpp_sdk.models.base import PanelModel
from mpp_sdk.models.measured import MeasuredPanel

# A hand-built, roughly single-diode-shaped sweep, measured order (Voc down
# to just past the knee).
_SWEEP = [
    (21.3, 0.006),
    (20.1, 0.105),
    (18.1, 0.195),
    (15.8, 0.208),
    (8.0, 0.215),
]

# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_needs_at_least_two_points():
    with pytest.raises(ValueError):
        MeasuredPanel.from_points([(21.3, 0.006)])


def test_ascending_and_descending_input_give_the_same_curve():
    forward = MeasuredPanel.from_points(_SWEEP)
    reversed_ = MeasuredPanel.from_points(list(reversed(_SWEEP)))
    for v in np.linspace(0.0, 21.3, 10):
        assert forward.current(v) == pytest.approx(reversed_.current(v))
    assert forward.open_circuit_voltage == pytest.approx(reversed_.open_circuit_voltage)


def test_duplicate_voltages_do_not_raise_and_are_averaged():
    points = [*_SWEEP, (18.1, 0.205)]  # repeats 18.1 with a different current
    panel = MeasuredPanel.from_points(points)
    # averaged: (0.195 + 0.205) / 2 = 0.2
    assert panel.current(18.1) == pytest.approx(0.2)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


def test_current_at_zero_equals_short_circuit_current():
    panel = MeasuredPanel.from_points(_SWEEP)
    assert panel.current(0.0) == pytest.approx(panel.short_circuit_current)


def test_current_past_voc_is_zero():
    panel = MeasuredPanel.from_points(_SWEEP)
    assert panel.current(panel.open_circuit_voltage + 5.0) == pytest.approx(0.0)


def test_extrapolate_false_uses_measured_max_voltage():
    panel = MeasuredPanel.from_points(_SWEEP, extrapolate=False)
    assert panel.open_circuit_voltage == pytest.approx(21.3)


def test_extrapolate_true_exceeds_measured_max_voltage():
    panel = MeasuredPanel.from_points(_SWEEP, extrapolate=True)
    assert panel.open_circuit_voltage > 21.3


# ------------------------------------------------------------------
# Scalar / array in-out
# ------------------------------------------------------------------


def test_scalar_in_scalar_out():
    panel = MeasuredPanel.from_points(_SWEEP)
    result = panel.current(10.0)
    assert isinstance(result, float)


def test_array_in_array_out():
    panel = MeasuredPanel.from_points(_SWEEP)
    voltages = np.array([0.0, 10.0, 20.0])
    result = panel.current(voltages)
    assert isinstance(result, np.ndarray)
    assert result.shape == voltages.shape


# ------------------------------------------------------------------
# PanelModel conformance
# ------------------------------------------------------------------


def test_is_a_panel_model():
    panel = MeasuredPanel.from_points(_SWEEP)
    assert isinstance(panel, PanelModel)


def test_inherited_power_iv_curve_mpp_all_work():
    panel = MeasuredPanel.from_points(_SWEEP)
    assert panel.power(10.0) == pytest.approx(10.0 * panel.current(10.0))
    v, i = panel.iv_curve(n=50)
    assert v.shape == (50,)
    assert i.shape == (50,)
    v_mpp, i_mpp, p_mpp = panel.mpp()
    assert p_mpp == pytest.approx(v_mpp * i_mpp)


def test_mpp_lands_on_the_obvious_peak():
    # A triangular P-V curve with an unmistakable peak at V=10.
    panel = MeasuredPanel.from_points([(0.0, 1.0), (10.0, 1.0), (20.0, 0.0)])
    v_mpp, _, _ = panel.mpp(n=2001)
    assert v_mpp == pytest.approx(10.0, abs=0.05)
