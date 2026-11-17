"""Unit tests for AdaptivePerturbAndObserve."""

import pytest

import mpp_sdk
from mpp_sdk.algorithms.adaptive_perturb_observe import AdaptivePerturbAndObserve
from mpp_sdk.algorithms.perturb_observe import PerturbAndObserve


def _source(panel=None, initial_duty=0.1):
    return mpp_sdk.SimulatedSource(
        panel or mpp_sdk.IdealSingleDiode(),
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def _run(ctl, src, n):
    """Run ``n`` steps and return the duty trace."""
    duties = []
    for _ in range(n):
        v, i = src.read()
        d = ctl.step(v, i)
        src.write(d)
        duties.append(d)
    return duties


def _efficiency(src, panel):
    v, i = src.read()
    return (v * i) / panel.mpp()[2]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_duty": 0.9, "max_duty": 0.1},
        {"min_step": 0.0},
        {"min_step": float("nan")},
        {"min_step": 0.01, "max_step": 0.001},
        {"gain": -1.0},
    ],
)
def test_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        AdaptivePerturbAndObserve(**kwargs)


def test_first_step_moves_up_by_min_step():
    ctl = AdaptivePerturbAndObserve(initial_duty=0.5, min_step=0.001)
    assert ctl.step(14.0, 0.72) == pytest.approx(0.501)


def test_direction_matches_fixed_step_rule():
    ctl = AdaptivePerturbAndObserve(initial_duty=0.5)
    ctl.step(10.0, 1.0)
    before = ctl.duty
    ctl.step(11.0, 1.1)  # dv > 0, dp > 0: raise V, lower D
    assert ctl.duty < before
    before = ctl.duty
    ctl.step(10.0, 0.9)  # dv < 0, dp < 0: raise V, lower D
    assert ctl.duty < before


@pytest.mark.parametrize("initial_duty", [0.1, 0.9])
def test_converges_on_ideal_panel(initial_duty):
    panel = mpp_sdk.IdealSingleDiode()
    src = _source(panel, initial_duty)
    ctl = AdaptivePerturbAndObserve(initial_duty=initial_duty)
    _run(ctl, src, 1500)
    assert _efficiency(src, panel) > 0.99


def test_converges_on_pvlib_panel():
    pytest.importorskip("pvlib")
    panel = mpp_sdk.PvlibPanelModel.hissuma_psf10mono()
    src = _source(panel, 0.1)
    ctl = AdaptivePerturbAndObserve(initial_duty=0.1)
    _run(ctl, src, 1500)
    assert _efficiency(src, panel) > 0.98


def test_step_is_bounded():
    ctl = AdaptivePerturbAndObserve(min_step=0.001, max_step=0.01)
    src = _source(initial_duty=0.1)
    prev = ctl.duty
    for _ in range(600):
        v, i = src.read()
        d = ctl.step(v, i)
        src.write(d)
        assert 0.001 - 1e-12 <= ctl.last_step <= 0.01 + 1e-12
        assert abs(d - prev) <= 0.01 + 1e-12
        prev = d


def test_step_grows_far_from_mpp_and_shrinks_near_it():
    src = _source(initial_duty=0.1)
    ctl = AdaptivePerturbAndObserve(initial_duty=0.1, min_step=0.0005, max_step=0.01)
    far = []
    for _ in range(20):
        v, i = src.read()
        src.write(ctl.step(v, i))
        far.append(ctl.last_step)
    _run(ctl, src, 1500)
    assert max(far) > 4 * ctl.last_step
    assert ctl.last_step == pytest.approx(0.0005, abs=1e-4)


def test_smaller_ripple_than_fixed_step_at_equal_max_step():
    max_step = 0.01
    ripple = {}
    for name, ctl in (
        ("fixed", PerturbAndObserve(initial_duty=0.1, step_size=max_step)),
        ("adaptive", AdaptivePerturbAndObserve(initial_duty=0.1, max_step=max_step)),
    ):
        duties = _run(ctl, _source(initial_duty=0.1), 1500)[-200:]
        ripple[name] = max(duties) - min(duties)
    assert ripple["adaptive"] < 0.5 * ripple["fixed"]


def test_tracks_after_irradiance_step():
    pytest.importorskip("pvlib")
    panel = mpp_sdk.PvlibPanelModel.hissuma_psf10mono()
    src = _source(panel, 0.3)
    ctl = AdaptivePerturbAndObserve(initial_duty=0.3)
    _run(ctl, src, 1000)
    panel.irradiance = 400.0
    _run(ctl, src, 1500)
    assert _efficiency(src, panel) > 0.97


def test_duty_stays_within_bounds():
    ctl = AdaptivePerturbAndObserve(initial_duty=0.5, min_duty=0.2, max_duty=0.8)
    for d in _run(ctl, _source(initial_duty=0.5), 500):
        assert 0.2 <= d <= 0.8


def test_near_dark_noise_keeps_minimum_step():
    ctl = AdaptivePerturbAndObserve(initial_duty=0.5, min_step=0.001, max_step=0.05)
    ctl.step(1e-3, 1e-4)  # P = 1e-7 W
    before = ctl.duty
    ctl.step(1.01e-3, 1e-4)  # dP = 1e-9 W, far below the dead-band
    assert abs(ctl.duty - before) == pytest.approx(0.001)
    assert ctl.last_step == pytest.approx(0.001)


def test_interface():
    ctl = AdaptivePerturbAndObserve()
    assert isinstance(ctl, mpp_sdk.MPPTAlgorithm)
    assert mpp_sdk.AdaptivePerturbAndObserve is AdaptivePerturbAndObserve
    assert isinstance(ctl.step(14.0, 0.72), float)
    assert isinstance(ctl.step(13.9, 0.73), float)
