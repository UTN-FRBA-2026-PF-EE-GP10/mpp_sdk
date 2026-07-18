"""Unit tests for SimulatedSource and DynamicSimulatedSource."""

import pytest

import mpp_sdk

# ------------------------------------------------------------------
# SimulatedSource
# ------------------------------------------------------------------


def _make_source(initial_duty=0.5):
    return mpp_sdk.SimulatedSource(
        mpp_sdk.IdealSingleDiode(),
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
    )


def test_load_resistance_zero_raises():
    with pytest.raises(ValueError):
        mpp_sdk.SimulatedSource(
            mpp_sdk.IdealSingleDiode(),
            mpp_sdk.SEPICConverter(),
            load_resistance=0,
        )


def test_operating_point_solves_the_circuit():
    src = _make_source(initial_duty=0.5)
    conv = mpp_sdk.SEPICConverter()
    v, i = src.read()
    r_eff = conv.reflected_resistance(0.5, 10.0)
    assert abs(i - v / r_eff) < 1e-6


def test_higher_duty_yields_lower_voltage():
    src_low = _make_source(initial_duty=0.3)
    src_high = _make_source(initial_duty=0.3)
    src_high.write(0.7)
    v_low, _ = src_low.read()
    v_high, _ = src_high.read()
    assert v_high < v_low


def test_read_is_idempotent():
    src = _make_source(initial_duty=0.5)
    v1, i1 = src.read()
    v2, i2 = src.read()
    assert v1 == v2
    assert i1 == i2


def test_write_clamps_to_converter_max_duty():
    src = _make_source(initial_duty=0.5)
    src.write(2.0)
    assert src.duty == pytest.approx(0.95)


# ------------------------------------------------------------------
# DynamicSimulatedSource
# ------------------------------------------------------------------


def _make_dynamic_source(**kwargs):
    return mpp_sdk.DynamicSimulatedSource(
        mpp_sdk.IdealSingleDiode(),
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        **kwargs,
    )


def test_dynamic_capacitance_zero_raises():
    with pytest.raises(ValueError):
        _make_dynamic_source(capacitance=0)


def test_dynamic_dt_zero_raises():
    with pytest.raises(ValueError):
        _make_dynamic_source(dt=0)


def test_dynamic_substeps_zero_raises():
    with pytest.raises(ValueError):
        _make_dynamic_source(substeps=0)


def test_dynamic_initial_state_is_open_circuit():
    panel = mpp_sdk.IdealSingleDiode()
    src = mpp_sdk.DynamicSimulatedSource(
        panel,
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
    )
    v, i = src.read()
    assert v == pytest.approx(panel.open_circuit_voltage)
    assert i == pytest.approx(0.0, abs=1e-6)


def test_dynamic_slews_toward_static_solution():
    static_src = _make_source(initial_duty=0.5)
    v_static, _ = static_src.read()

    src_one = _make_dynamic_source(initial_duty=0.5)
    src_one.write(0.5)
    v_1, _ = src_one.read()

    src_many = _make_dynamic_source(initial_duty=0.5)
    for _ in range(200):
        src_many.write(0.5)
    v_200, _ = src_many.read()

    assert abs(v_1 - v_static) > abs(v_200 - v_static)


def test_dynamic_set_panel_clamps_to_new_voc():
    src = _make_dynamic_source(initial_duty=0.5)
    for _ in range(200):
        src.write(0.5)

    low_voc_panel = mpp_sdk.IdealSingleDiode(cells_in_series=30)
    v_before, _ = src.read()
    assert low_voc_panel.open_circuit_voltage < v_before

    src.set_panel(low_voc_panel)
    v_after, _ = src.read()
    assert v_after <= low_voc_panel.open_circuit_voltage


def test_dynamic_source_stable_at_high_duty():
    """Explicit Euler diverges (0/Voc flip-flop) for D >~ 0.91 at these
    defaults; the exponential-Euler step must stay bounded and settle."""
    panel = mpp_sdk.IdealSingleDiode()
    voc = panel.open_circuit_voltage
    src = _make_dynamic_source(capacitance=100e-6, dt=1e-3, substeps=50, initial_duty=0.95)

    voltages = []
    for _ in range(100):
        src.write(0.95)
        v, _ = src.read()
        assert 0.0 < v < voc
        voltages.append(v)

    # Once settled, consecutive readings should not oscillate by a large
    # fraction of Voc (that flip-flop is exactly the divergence symptom).
    tail = voltages[-20:]
    for a, b in zip(tail, tail[1:], strict=False):
        assert abs(a - b) < 0.01 * voc


def test_dynamic_source_settles_to_load_line():
    """At steady state, I_panel(V) must equal V/R_eff (load-line intersection)."""
    panel = mpp_sdk.IdealSingleDiode()
    converter = mpp_sdk.SEPICConverter()
    load_resistance = 10.0
    duty = 0.5
    src = mpp_sdk.DynamicSimulatedSource(
        panel,
        converter,
        load_resistance=load_resistance,
        capacitance=100e-6,
        dt=1e-3,
        substeps=50,
        initial_duty=duty,
    )
    for _ in range(500):
        src.write(duty)
    v, i = src.read()

    r_eff = converter.reflected_resistance(duty, load_resistance)
    voc = panel.open_circuit_voltage
    assert abs(i - v / r_eff) * r_eff < 1e-3 * voc
