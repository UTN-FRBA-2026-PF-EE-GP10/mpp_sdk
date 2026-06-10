"""Unit tests for the PowerChangeDetector restart trigger."""

import pytest

import mpp_sdk
from mpp_sdk.algorithms.restart import PowerChangeDetector

# ------------------------------------------------------------------
# Construction / validation
# ------------------------------------------------------------------


def test_invalid_threshold():
    with pytest.raises(ValueError):
        PowerChangeDetector(threshold=0.0)


def test_invalid_samples():
    with pytest.raises(ValueError):
        PowerChangeDetector(samples=0)


def test_invalid_smoothing():
    with pytest.raises(ValueError):
        PowerChangeDetector(smoothing=0.0)


# ------------------------------------------------------------------
# Trigger behaviour
# ------------------------------------------------------------------


def test_constant_power_never_triggers():
    det = PowerChangeDetector(threshold=0.2, samples=3)
    assert not any(det.update(10.0) for _ in range(500))


def test_small_ripple_never_triggers():
    det = PowerChangeDetector(threshold=0.2, samples=3)
    assert not any(det.update(10.0 + 0.5 * (-1) ** k) for k in range(500))


def test_single_spike_is_debounced():
    det = PowerChangeDetector(threshold=0.2, samples=3)
    for _ in range(10):
        det.update(10.0)
    assert not det.update(2.0)  # one bad sample — noise, not a change
    assert not any(det.update(10.0) for _ in range(10))


def test_sustained_drop_triggers_after_samples():
    det = PowerChangeDetector(threshold=0.2, samples=3)
    for _ in range(10):
        det.update(10.0)
    assert not det.update(5.0)
    assert not det.update(5.0)
    assert det.update(5.0)  # third consecutive out-of-band sample fires


def test_sustained_rise_triggers():
    det = PowerChangeDetector(threshold=0.2, samples=3)
    for _ in range(10):
        det.update(5.0)
    fired = [det.update(10.0) for _ in range(3)]
    assert fired == [False, False, True]


def test_slow_ramp_is_followed_without_trigger():
    # +1 % per step stays inside a 20 % band while the EMA reference follows,
    # so a ramp the local tracker can handle never causes a restart.
    det = PowerChangeDetector(threshold=0.2, samples=3, smoothing=0.5)
    p = 10.0
    for _ in range(200):
        assert not det.update(p)
        p *= 1.01


def test_rearms_after_firing():
    det = PowerChangeDetector(threshold=0.2, samples=2)
    for _ in range(5):
        det.update(10.0)
    assert [det.update(3.0) for _ in range(2)] == [False, True]
    # After firing it re-seeds from the next sample and can fire again.
    for _ in range(5):
        assert not det.update(3.0)
    assert [det.update(10.0) for _ in range(2)] == [False, True]


def test_reset_forgets_reference():
    det = PowerChangeDetector(threshold=0.2, samples=1)
    det.update(10.0)
    det.reset()
    assert not det.update(1.0)  # first sample after reset only seeds the reference


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_exported_from_algorithms_package():
    assert mpp_sdk.algorithms.PowerChangeDetector is PowerChangeDetector
