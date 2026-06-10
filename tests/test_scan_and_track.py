"""Unit tests for the ScanAndTrack global MPPT controller."""

import pytest

import mpp_sdk
from mpp_sdk.algorithms.scan_and_track import ScanAndTrack

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel  # noqa: E402
from mpp_sdk.models.string import PvString  # noqa: E402

# ------------------------------------------------------------------
# Construction / validation
# ------------------------------------------------------------------


def test_invalid_duty_bounds():
    with pytest.raises(ValueError):
        ScanAndTrack(min_duty=0.9, max_duty=0.1)


def test_invalid_scan_step():
    with pytest.raises(ValueError):
        ScanAndTrack(scan_step=0.0)


def test_invalid_rescan_period():
    with pytest.raises(ValueError):
        ScanAndTrack(rescan_period=0)


def test_starts_in_scan_phase():
    assert ScanAndTrack().scanning


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _shaded_string():
    panels = [
        PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0),
        PvlibPanelModel.hissuma_psf10mono(irradiance=400.0),
    ]
    return PvString(panels)


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
# Global MPP under partial shading — the whole point
# ------------------------------------------------------------------


def test_reaches_global_mpp_under_shade():
    panel = _shaded_string()
    _, _, p_global = panel.mpp()
    v, i = _run(panel, ScanAndTrack(initial_duty=0.5), 800)
    assert (v * i) / p_global > 0.97


def test_scan_and_track_beats_pno_when_pno_is_trapped():
    """From the Voc side under shade, P&O traps on the local peak; scan does not."""
    panel = _shaded_string()
    _, _, p_global = panel.mpp()

    v_p, i_p = _run(panel, mpp_sdk.PerturbAndObserve(initial_duty=0.1, step_size=0.004), 800)
    v_s, i_s = _run(panel, ScanAndTrack(initial_duty=0.1), 800)

    eta_pno = (v_p * i_p) / p_global
    eta_scan = (v_s * i_s) / p_global
    assert eta_scan > 0.97
    assert eta_scan > eta_pno  # scan escapes the trap P&O falls into


# ------------------------------------------------------------------
# Full sun — must still converge and then track quietly
# ------------------------------------------------------------------


def test_reaches_mpp_full_sun():
    panel = PvlibPanelModel.hissuma_psf10mono()
    _, _, p_mpp = panel.mpp()
    v, i = _run(panel, ScanAndTrack(initial_duty=0.5), 600)
    assert (v * i) / p_mpp > 0.98


def test_switches_to_track_after_scan():
    ctl = ScanAndTrack(scan_step=0.1)
    panel = PvlibPanelModel.hissuma_psf10mono()
    src = mpp_sdk.SimulatedSource(panel, mpp_sdk.SEPICConverter(), load_resistance=10.0)
    # enough steps to finish the ~10-point scan
    for _ in range(20):
        v, i = src.read()
        src.write(ctl.step(v, i))
    assert not ctl.scanning


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
    """Drive the dynamic source; return whether a (re)scan was seen running."""
    scanned = False
    for _ in range(steps):
        v, i = src.read()
        src.write(ctl.step(v, i))
        scanned = scanned or ctl.scanning
    return scanned


def _make_dynamic(panel, initial_duty):
    return mpp_sdk.DynamicSimulatedSource(
        panel=mpp_sdk.TabulatedPanel(panel),
        converter=mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def test_reacquires_global_mpp_after_shading_change():
    shaded = mpp_sdk.TabulatedPanel(_shaded_string())
    ctl = ScanAndTrack(initial_duty=0.5)
    src = _make_dynamic(_full_string(), ctl.duty)
    _run_dynamic(src, ctl, 600)
    assert not ctl.scanning  # converged on the full-sun MPP

    src.set_panel(shaded)
    rescanned = _run_dynamic(src, ctl, 800)
    assert rescanned  # the power change triggered a fresh scan
    v, i = src.read()
    assert (v * i) / shaded.mpp()[2] > 0.95


def test_restart_disabled_never_rescans():
    ctl = ScanAndTrack(initial_duty=0.5, restart_threshold=None)
    src = _make_dynamic(_full_string(), ctl.duty)
    _run_dynamic(src, ctl, 600)
    assert not ctl.scanning

    src.set_panel(mpp_sdk.TabulatedPanel(_shaded_string()))
    rescanned = _run_dynamic(src, ctl, 800)
    assert not rescanned  # the old behaviour: track-only after the first scan


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_is_mppt_algorithm():
    assert isinstance(ScanAndTrack(), mpp_sdk.MPPTAlgorithm)


def test_exported_from_top_level():
    assert mpp_sdk.ScanAndTrack is ScanAndTrack
