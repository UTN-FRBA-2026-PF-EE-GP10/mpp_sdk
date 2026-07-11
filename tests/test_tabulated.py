"""Unit tests for TabulatedPanel."""

import numpy as np
import pytest

import mpp_sdk
from mpp_sdk.models.tabulated import TabulatedPanel

# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_n_less_than_two_raises():
    with pytest.raises(ValueError):
        TabulatedPanel(mpp_sdk.IdealSingleDiode(), n=1)


# ------------------------------------------------------------------
# Endpoints preserved
# ------------------------------------------------------------------


def test_endpoints_match_wrapped_panel():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel)
    assert tab.open_circuit_voltage == pytest.approx(panel.open_circuit_voltage, abs=1e-9)
    assert tab.short_circuit_current == pytest.approx(panel.short_circuit_current, abs=1e-9)


# ------------------------------------------------------------------
# Interpolation accuracy
# ------------------------------------------------------------------


def test_interpolation_accuracy():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel, n=800)
    tolerance = 0.01 * panel.short_circuit_current
    for v in np.linspace(0.0, panel.open_circuit_voltage, 20):
        assert abs(tab.current(v) - panel.current(v)) < tolerance


# ------------------------------------------------------------------
# Scalar / array in-out
# ------------------------------------------------------------------


def test_scalar_in_scalar_out():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel)
    result = tab.current(5.0)
    assert isinstance(result, float)


def test_array_in_array_out():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel)
    voltages = np.array([0.0, 5.0, 10.0])
    result = tab.current(voltages)
    assert isinstance(result, np.ndarray)
    assert result.shape == voltages.shape


# ------------------------------------------------------------------
# Out-of-range fills
# ------------------------------------------------------------------


def test_below_range_returns_short_circuit_current():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel)
    assert tab.current(-1.0) == pytest.approx(panel.short_circuit_current)


def test_above_range_returns_zero():
    panel = mpp_sdk.IdealSingleDiode()
    tab = TabulatedPanel(panel)
    assert tab.current(panel.open_circuit_voltage + 1.0) == pytest.approx(0.0)
