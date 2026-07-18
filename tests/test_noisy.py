"""Unit tests for the NoisySource measurement-noise wrapper."""

import numpy as np
import pytest

import mpp_sdk
from mpp_sdk.io.noisy import NoisySource

# ------------------------------------------------------------------
# Construction / validation
# ------------------------------------------------------------------


def _clean_source(initial_duty: float = 0.5):
    return mpp_sdk.SimulatedSource(
        mpp_sdk.IdealSingleDiode(),
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def test_invalid_v_std():
    with pytest.raises(ValueError):
        NoisySource(_clean_source(), v_std=-0.1)


def test_invalid_i_std():
    with pytest.raises(ValueError):
        NoisySource(_clean_source(), i_std=float("nan"))


# ------------------------------------------------------------------
# Noise statistics
# ------------------------------------------------------------------


def test_zero_noise_is_transparent():
    clean = _clean_source()
    noisy = NoisySource(_clean_source())
    for _ in range(50):
        assert noisy.read() == clean.read()
        noisy.write(0.4)
        clean.write(0.4)


def test_noise_mean_and_std_match_configuration():
    src = NoisySource(_clean_source(), v_std=0.4, i_std=0.01, seed=7)
    v_true, i_true = src.source.read()
    samples = np.array([src.read() for _ in range(20000)])
    assert samples[:, 0].mean() == pytest.approx(v_true, abs=0.02)
    assert samples[:, 0].std() == pytest.approx(0.4, rel=0.05)
    assert samples[:, 1].mean() == pytest.approx(i_true, abs=5e-4)
    assert samples[:, 1].std() == pytest.approx(0.01, rel=0.05)


def test_reproducible_with_seed():
    a = NoisySource(_clean_source(), v_std=0.4, i_std=0.01, seed=42)
    b = NoisySource(_clean_source(), v_std=0.4, i_std=0.01, seed=42)
    assert [a.read() for _ in range(20)] == [b.read() for _ in range(20)]


def test_different_seeds_differ():
    a = NoisySource(_clean_source(), v_std=0.4, seed=1)
    b = NoisySource(_clean_source(), v_std=0.4, seed=2)
    assert a.read() != b.read()


# ------------------------------------------------------------------
# Passthrough behaviour
# ------------------------------------------------------------------


def test_write_passes_duty_through():
    src = NoisySource(_clean_source(initial_duty=0.5), v_std=0.4)
    src.write(0.3)
    assert src.duty == pytest.approx(src.source.duty)
    assert src.source.duty == pytest.approx(0.3)


def test_inner_source_is_reachable():
    inner = _clean_source()
    assert NoisySource(inner).source is inner


# ------------------------------------------------------------------
# Integration: an algorithm still tracks through moderate noise
# ------------------------------------------------------------------


def test_pno_still_tracks_under_moderate_noise():
    panel = mpp_sdk.IdealSingleDiode()
    src = NoisySource(_clean_source(), v_std=0.05, i_std=0.002, seed=0)
    ctl = mpp_sdk.PerturbAndObserve(initial_duty=0.5)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    # judge against the *clean* operating point, not the noisy reading
    v, i = src.source.read()
    assert (v * i) / panel.mpp()[2] > 0.9


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------


def test_is_signal_source():
    assert isinstance(NoisySource(_clean_source()), mpp_sdk.SignalSource)


def test_exported_from_top_level():
    assert mpp_sdk.NoisySource is NoisySource
