"""Unit tests for SingleDiodeWithLosses."""

import numpy as np
import pytest

from mpp_sdk import IdealSingleDiode, SingleDiodeWithLosses


def test_limit_case_matches_ideal():
    lossy = SingleDiodeWithLosses(series_resistance=0.0, shunt_resistance=np.inf)
    ideal = IdealSingleDiode()
    v = np.linspace(0.0, ideal.open_circuit_voltage * 1.05, 200)
    assert lossy.current(v) == pytest.approx(ideal.current(v), abs=1e-9)
    assert lossy.open_circuit_voltage == pytest.approx(ideal.open_circuit_voltage, abs=1e-9)


def test_mpp_pinned():
    panel = SingleDiodeWithLosses()
    v_mp, i_mp, p_mp = panel.mpp()
    assert v_mp == pytest.approx(37.5, abs=0.3)
    assert i_mp == pytest.approx(7.45, abs=0.1)
    assert p_mp == pytest.approx(279.7, abs=2.0)
    ideal_p = IdealSingleDiode().mpp()[2]
    assert p_mp < ideal_p


def test_residual_is_zero_at_solution():
    panel = SingleDiodeWithLosses()
    v = np.linspace(0.0, 35.0, 50)
    i = panel.current(v)
    f, _ = panel._residual(i, v, panel.module_thermal_voltage, 1.0 / panel.shunt_resistance)
    mask = i > 0
    assert np.all(np.abs(f[mask]) < 1e-9)


def test_monotonic_decreasing():
    panel = SingleDiodeWithLosses()
    v = np.linspace(0.0, panel.open_circuit_voltage * 1.1, 500)
    assert np.all(np.diff(panel.current(v)) <= 1e-12)


def test_short_circuit_and_open_circuit():
    panel = SingleDiodeWithLosses()
    assert panel.current(0.0) == pytest.approx(panel.photocurrent, rel=0.01)
    assert panel.short_circuit_current == pytest.approx(panel.current(0.0))
    assert panel.current(panel.open_circuit_voltage) == pytest.approx(0.0, abs=1e-6)


def test_scalar_and_array():
    panel = SingleDiodeWithLosses()
    assert isinstance(panel.current(20.0), float)
    arr = panel.current(np.array([10.0, 20.0, 30.0]))
    assert arr.shape == (3,)
    assert arr[1] == pytest.approx(panel.current(20.0))
    assert panel.current(np.zeros((2, 3))).shape == (2, 3)


@pytest.mark.parametrize("v", [-100.0, -1.0, 100.0, 1e4, 1e8])
def test_extreme_voltage_converges(v):
    i = SingleDiodeWithLosses().current(v)
    assert np.isfinite(i)
    assert i >= 0.0
    if v > 50:
        assert i == 0.0


def test_extreme_resistances_converge():
    panel = SingleDiodeWithLosses(series_resistance=20.0, shunt_resistance=5.0)
    i = panel.current(np.linspace(0.0, 40.0, 100))
    assert np.all(np.isfinite(i))


def test_irradiance_and_temperature_are_mutable():
    panel = SingleDiodeWithLosses()
    p_full = panel.mpp()[2]
    voc_cold = panel.open_circuit_voltage
    panel.irradiance = 500.0
    assert panel.short_circuit_current == pytest.approx(4.0, rel=0.01)
    assert panel.mpp()[2] < p_full
    panel.irradiance = 1000.0
    panel.temperature = 60.0
    assert panel.open_circuit_voltage != pytest.approx(voc_cold)  # I_0 is fixed, only V_t moves


# ------------------------------------------------------------------
# Accuracy against an independent root finder
# ------------------------------------------------------------------


def _reference_current(panel, v):
    """Root of the implicit equation by scipy brentq, clamped at 0 like the model."""
    brentq = pytest.importorskip("scipy.optimize").brentq
    a = panel.module_thermal_voltage
    g = 1.0 / panel.shunt_resistance
    iph = panel.photocurrent * panel.irradiance / 1000.0

    def f(i):
        x = v + i * panel.series_resistance
        return iph - panel.saturation_current * np.expm1(min(x / a, 700.0)) - x * g - i

    hi = iph + 1.0 + max(-v, 0.0) * g
    if f(0.0) <= 0.0:
        return 0.0
    return brentq(f, 0.0, hi, xtol=1e-14, rtol=1e-14, maxiter=500)


def test_random_parameters_match_reference():
    rng = np.random.default_rng(1234)
    for _ in range(300):
        panel = SingleDiodeWithLosses(
            photocurrent=rng.uniform(0.5, 10.0),
            saturation_current=10 ** rng.uniform(-11, -7),
            ideality_factor=rng.uniform(1.0, 2.0),
            cells_in_series=int(rng.integers(10, 80)),
            series_resistance=rng.uniform(0.0, 20.0),
            shunt_resistance=10 ** rng.uniform(0.5, 3.5),
            irradiance=rng.uniform(100.0, 1100.0),
            temperature=rng.uniform(0.0, 70.0),
        )
        voc = panel.open_circuit_voltage
        v = np.concatenate([rng.uniform(-2.0, 1.5 * voc, 8), [-2.0, 0.0, voc, 1.5 * voc]])
        got = panel.current(v)
        want = np.array([_reference_current(panel, x) for x in v])
        assert got == pytest.approx(want, abs=1e-9)


def test_stiff_large_series_resistance_reverse_voltage():
    panel = SingleDiodeWithLosses(series_resistance=10.8, shunt_resistance=8.9)
    for v in (-2.0, -1.0, -0.1):
        assert panel.current(v) == pytest.approx(_reference_current(panel, v), abs=1e-9)


def test_stiff_large_series_resistance_near_voc():
    panel = SingleDiodeWithLosses(series_resistance=20.0, shunt_resistance=3.0)
    voc = panel.open_circuit_voltage
    v = voc * np.array([0.9, 0.99, 1.0, 1.01, 1.2])
    want = [_reference_current(panel, x) for x in v]
    assert panel.current(v) == pytest.approx(want, abs=1e-9)


def test_newton_crawl_case_needs_bisection():
    # x / a is about 1500 at the first guess, so plain Newton loses one
    # thermal voltage per step and cannot finish inside the iteration cap.
    panel = SingleDiodeWithLosses(
        photocurrent=10.0,
        ideality_factor=1.0,
        cells_in_series=10,
        series_resistance=20.0,
        shunt_resistance=1.0,
    )
    for v in (-10.0, -5.0, -1.0, 0.5):
        assert panel.current(v) == pytest.approx(_reference_current(panel, v), abs=1e-9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shunt_resistance": 0.0},
        {"shunt_resistance": -5.0},
        {"shunt_resistance": float("nan")},
        {"series_resistance": -0.1},
        {"series_resistance": float("nan")},
        {"series_resistance": float("inf")},
    ],
)
def test_invalid_resistance_raises(kwargs):
    with pytest.raises(ValueError):
        SingleDiodeWithLosses(**kwargs)


@pytest.mark.parametrize("v", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_voltage_raises(v):
    with pytest.raises(ValueError):
        SingleDiodeWithLosses().current(v)
