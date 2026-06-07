"""Smoke tests for PvString — series panels with bypass diodes.

Pins the count and rough location of local maxima on the P-V curve for
canonical shading patterns, per the AGENTS.md convention for array models.
"""

import numpy as np
import pytest

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel  # noqa: E402
from mpp_sdk.models.string import PvString  # noqa: E402


def _count_local_maxima(p: np.ndarray) -> int:
    """Number of interior local maxima in a power array (with a small margin)."""
    peak = p.max()
    margin = 0.02 * peak  # ignore ripple-scale wiggles
    count = 0
    for k in range(1, len(p) - 1):
        if p[k] >= p[k - 1] and p[k] > p[k + 1] and p[k] > margin:
            count += 1
    return count


def _string(g1, g2):
    return PvString(
        [
            PvlibPanelModel.hissuma_psf10mono(irradiance=g1),
            PvlibPanelModel.hissuma_psf10mono(irradiance=g2),
        ]
    )


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def test_empty_panels_raises():
    with pytest.raises(ValueError):
        PvString([])


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


def test_series_voc_is_sum_of_panel_vocs():
    string = _string(1000, 1000)
    p1 = PvlibPanelModel.hissuma_psf10mono(irradiance=1000)
    assert string.open_circuit_voltage == pytest.approx(2 * p1.open_circuit_voltage, rel=0.02)


def test_series_isc_matches_strongest_panel():
    string = _string(1000, 400)
    strong = PvlibPanelModel.hissuma_psf10mono(irradiance=1000)
    assert string.short_circuit_current == pytest.approx(strong.short_circuit_current, rel=0.02)


# ------------------------------------------------------------------
# P-V curve shape: full sun is unimodal, partial shade is bimodal
# ------------------------------------------------------------------


def test_full_sun_is_unimodal():
    string = _string(1000, 1000)
    v, i = string.iv_curve(n=400)
    assert _count_local_maxima(v * i) == 1


def test_partial_shade_has_two_peaks():
    string = _string(1000, 400)
    v, i = string.iv_curve(n=400)
    assert _count_local_maxima(v * i) == 2


def test_global_peak_is_the_higher_one_under_shade():
    string = _string(1000, 400)
    v, i = string.iv_curve(n=400)
    p = v * i
    v_mpp, _, p_mpp = string.mpp()
    # global MPP equals the highest sampled peak
    assert p_mpp == pytest.approx(p.max(), rel=0.02)
    # and it carries more power than the single fully-lit panel alone (~10 W)
    assert p_mpp > 9.0


def test_deeper_shade_lowers_global_mpp():
    light = _string(1000, 600)
    deep = _string(1000, 200)
    assert deep.mpp()[2] < light.mpp()[2]


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_current_accepts_array():
    string = _string(1000, 400)
    v = np.linspace(0, string.open_circuit_voltage, 50)
    i = string.current(v)
    assert i.shape == (50,)
    assert (i >= 0).all()
