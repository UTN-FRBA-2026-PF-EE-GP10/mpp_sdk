"""Characterization tests for harness/common.py (roster, conditions, run loop).

These tests pin *today's* behavior of the shared harness plumbing that
compare_static/dynamic/cyclic/bank/noise, animate and snapshot all route
through. They do not modify harness/common.py - a failure here means either
the test's expectation is wrong or a real regression was found; either way,
report it rather than adjusting the module.
"""

import pytest

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

import mpp_sdk  # noqa: E402
from harness.common import algorithm_specs, build_conditions, run_schedule  # noqa: E402

# ------------------------------------------------------------------
# algorithm_specs
# ------------------------------------------------------------------


def test_roster_labels_and_order():
    specs = algorithm_specs()
    assert [s.label for s in specs] == ["P&O", "InCond", "Fuzzy", "Scan&Track", "PSO"]
    for spec in specs:
        algo = spec.make(0.5)
        assert isinstance(algo, mpp_sdk.MPPTAlgorithm)
        d = algo.step(1.0, 0.1)
        assert isinstance(d, float)


def test_roster_rescan_plumbing():
    specs_none = algorithm_specs(rescan_period=None)
    specs_periodic = algorithm_specs(rescan_period=7)

    scan_none = next(s for s in specs_none if s.label == "Scan&Track").make(0.5)
    scan_periodic = next(s for s in specs_periodic if s.label == "Scan&Track").make(0.5)

    # Run both through their scan phase (same duties commanded either way,
    # since rescan_period only affects post-scan behavior) with a constant
    # (V, I) reading, then far enough past scan completion for the periodic
    # variant's rescan_period to have elapsed.
    for _ in range(200):
        scan_none.step(20.0, 0.5)
        scan_periodic.step(20.0, 0.5)

    assert scan_none.scanning is False
    assert scan_periodic.scanning is True


# ------------------------------------------------------------------
# build_conditions
# ------------------------------------------------------------------


def test_build_conditions_dedupes():
    conditions = build_conditions([(1000.0, 1000.0), (1000.0, 1000.0), (800.0, 800.0)])
    assert len(conditions) == 2
    for panel, p_mpp in conditions.values():
        assert p_mpp > 0
        assert panel.mpp()[2] == pytest.approx(p_mpp)


# ------------------------------------------------------------------
# run_schedule
# ------------------------------------------------------------------


class _FixedDutyController:
    """Stub MPPTAlgorithm: always commands the same duty, regardless of (V, I)."""

    def __init__(self, duty: float) -> None:
        self._duty = duty

    def step(self, voltage: float, current: float) -> float:
        return self._duty


def test_run_schedule_shapes_and_panel_swap():
    conditions = build_conditions([(1000.0, 1000.0), (200.0, 200.0)])
    schedule = [
        ((1000.0, 1000.0), 50, "full sun"),
        ((200.0, 200.0), 50, "shaded"),
    ]

    vs, is_, ds = run_schedule(
        lambda d: _FixedDutyController(d),
        schedule,
        conditions,
        initial_duty=0.5,
    )

    assert vs.shape == (100,)
    assert is_.shape == (100,)
    assert ds.shape == (100,)

    p_full_sun = (vs[:50] * is_[:50]).mean()
    p_shaded = (vs[50:] * is_[50:]).mean()
    assert p_full_sun > p_shaded  # set_panel actually swapped conditions


def test_run_schedule_noise_isolation():
    conditions = build_conditions([(1000.0, 1000.0)])
    schedule = [((1000.0, 1000.0), 100, "full sun")]

    vs_clean, is_clean, ds_clean = run_schedule(
        lambda d: _FixedDutyController(d),
        schedule,
        conditions,
        initial_duty=0.5,
    )
    vs_noisy, is_noisy, ds_noisy = run_schedule(
        lambda d: _FixedDutyController(d),
        schedule,
        conditions,
        initial_duty=0.5,
        noise_v_std=0.5,
        noise_i_std=0.05,
        noise_seed=0,
    )

    # A fixed-duty controller never reacts to what it reads, so the plant
    # trajectory - and the TRUE traces run_schedule returns - must be
    # identical whether or not the controller's copy is noisy.
    assert vs_clean == pytest.approx(vs_noisy)
    assert is_clean == pytest.approx(is_noisy)
    assert ds_clean == pytest.approx(ds_noisy)
