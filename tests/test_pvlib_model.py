"""Unit tests for PvlibPanelModel.

Skipped automatically when the ``pvlib`` optional dependency is absent.
"""

import math

import pytest

pvlib = pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel  # noqa: E402


@pytest.fixture
def panel():
    return PvlibPanelModel.hissuma_psf10mono()


# ------------------------------------------------------------------
# I-V endpoints
# ------------------------------------------------------------------


def test_short_circuit_current_near_isc(panel):
    """I(0) must be within 1 % of the datasheet Isc."""
    assert math.isclose(panel.current(0.0), panel.short_circuit_current, rel_tol=0.01)


def test_open_circuit_current_near_zero(panel):
    """I(Voc) must be effectively zero."""
    assert panel.current(panel.open_circuit_voltage) < 1e-3


def test_voc_within_5pct_of_datasheet(panel):
    assert math.isclose(panel.open_circuit_voltage, 17.0, rel_tol=0.05)


def test_isc_within_5pct_of_datasheet(panel):
    assert math.isclose(panel.short_circuit_current, 0.79, rel_tol=0.05)


# ------------------------------------------------------------------
# MPP
# ------------------------------------------------------------------


def test_mpp_inside_iv_envelope(panel):
    v_mpp, i_mpp, p_mpp = panel.mpp()
    assert 0.0 < v_mpp < panel.open_circuit_voltage
    assert 0.0 < i_mpp < panel.short_circuit_current
    assert p_mpp > 0.0


def test_mpp_power_within_10pct_of_datasheet(panel):
    _, _, p_mpp = panel.mpp()
    assert math.isclose(p_mpp, 10.0, rel_tol=0.10)


def test_mpp_voltage_within_10pct_of_datasheet(panel):
    v_mpp, _, _ = panel.mpp()
    assert math.isclose(v_mpp, 14.0, rel_tol=0.10)


# ------------------------------------------------------------------
# Temperature dependence
# ------------------------------------------------------------------


def test_voc_decreases_with_temperature():
    cold = PvlibPanelModel.hissuma_psf10mono(temperature=15.0)
    hot = PvlibPanelModel.hissuma_psf10mono(temperature=55.0)
    assert cold.open_circuit_voltage > hot.open_circuit_voltage


def test_isc_increases_with_temperature():
    cold = PvlibPanelModel.hissuma_psf10mono(temperature=15.0)
    hot = PvlibPanelModel.hissuma_psf10mono(temperature=55.0)
    assert cold.short_circuit_current < hot.short_circuit_current


# ------------------------------------------------------------------
# Irradiance dependence
# ------------------------------------------------------------------


def test_isc_scales_with_irradiance():
    low = PvlibPanelModel.hissuma_psf10mono(irradiance=500.0)
    high = PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0)
    assert math.isclose(low.short_circuit_current, high.short_circuit_current / 2, rel_tol=0.05)


def test_power_drops_at_low_irradiance():
    stc = PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0)
    low = PvlibPanelModel.hissuma_psf10mono(irradiance=300.0)
    _, _, p_stc = stc.mpp()
    _, _, p_low = low.mpp()
    assert p_low < p_stc


# ------------------------------------------------------------------
# Array interface
# ------------------------------------------------------------------


def test_current_accepts_numpy_array(panel):
    import numpy as np

    v = np.linspace(0, panel.open_circuit_voltage, 50)
    i = panel.current(v)
    assert i.shape == (50,)
    assert (i >= 0).all()


def test_iv_curve_is_monotonically_decreasing(panel):
    v, i = panel.iv_curve(n=200)
    assert all(a >= b for a, b in zip(i, i[1:], strict=False))
