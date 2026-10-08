"""Unit tests for `scripts/sepic_step_response.py`."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.sepic_step_response import (
    MAX_DUTY,
    Limits,
    Poller,
    Sample,
    SimulatedSepicStepSource,
    StepAborted,
    StepMetrics,
    calculate_step_metrics,
    export_csv,
    run_step_response_test,
)


class FakeSepicHardware:
    """Mock SEPIC source simulating hardware for safety and link tests."""

    def __init__(self, *, bad_frames: int = 0, fail_after: int | None = None) -> None:
        self.duty = 0.0
        self.writes: list[float] = []
        self.vout = 0.0
        self.consecutive_bad_frames = bad_frames
        self._reads = 0
        self._fail_after = fail_after

    def write(self, duty: float) -> None:
        self.duty = duty
        self.writes.append(duty)

    def read(self) -> tuple[float, float]:
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise RuntimeError("SPI link failure")
        self.vout = 12.0 * self.duty / (1.0 - self.duty) if self.duty < 0.99 else 0.0
        p_out = self.vout**2 / 10.0
        return 12.0, (p_out / 0.9) / 12.0 if self.duty > 0 else 0.0


LIMITS = Limits(i_in_max=1.0, v_in_max=30.0, v_out_max=25.0)


def test_calculate_step_metrics_settling_time_synthetic():
    """Verify settling time calculation with a known exponential curve."""
    # V(t) = 10.0 * (1 - exp(-t / 0.010)) -> tau = 10 ms.
    # 2% settling occurs at t = -ln(0.02) * tau ~= 3.912 * 10 ms ~= 39.1 ms.
    t_step = 1.0
    window_s = 0.2
    dt = 0.001
    samples: list[Sample] = []

    # 10 pre-step samples
    for i in range(10):
        t = t_step - 0.01 + i * dt
        samples.append(Sample(timestamp=t, duty=0.1, v_in=12.0, i_in=0.1, v_out=1.0))

    # 200 post-step samples
    import math

    for i in range(200):
        t = t_step + i * dt
        t_rel = t - t_step
        v = 1.0 + 9.0 * (1.0 - math.exp(-t_rel / 0.010))
        samples.append(Sample(timestamp=t, duty=0.3, v_in=12.0, i_in=0.3, v_out=v))

    metrics = calculate_step_metrics(
        samples,
        t_step=t_step,
        window_s=window_s,
        duty_initial=0.1,
        duty_target=0.3,
        step_idx=1,
        tolerance_pct=2.0,
    )

    assert metrics.v_out_final == pytest.approx(10.0, rel=0.01)
    assert metrics.settling_time_ms is not None
    # Expected ts is ~39 ms, tolerance ±2 ms due to 1 ms discretization
    assert metrics.settling_time_ms == pytest.approx(39.0, abs=2.5)
    assert metrics.ripple_pp_mv == pytest.approx(0.0, abs=5.0)


def test_calculate_step_metrics_unsettled_returns_none():
    """If the voltage never settles within the tolerance band, ts is None."""
    t_step = 0.0
    window_s = 0.1
    # Samples ramp continuously without settling
    samples = [
        Sample(timestamp=0.01 * i, duty=0.2, v_in=12.0, i_in=0.1, v_out=float(i))
        for i in range(11)
    ]
    metrics = calculate_step_metrics(
        samples,
        t_step=t_step,
        window_s=window_s,
        duty_initial=0.1,
        duty_target=0.2,
        tolerance_pct=2.0,
    )
    assert metrics.settling_time_ms is None


def test_calculate_step_metrics_already_within_band():
    """If all samples are already within tolerance, ts is 0.0 ms."""
    t_step = 1.0
    window_s = 0.1
    samples = [
        Sample(timestamp=1.0 + 0.01 * i, duty=0.2, v_in=12.0, i_in=0.1, v_out=5.0)
        for i in range(11)
    ]
    metrics = calculate_step_metrics(
        samples,
        t_step=t_step,
        window_s=window_s,
        duty_initial=0.2,
        duty_target=0.2,
        tolerance_pct=2.0,
    )
    assert metrics.settling_time_ms == 0.0


def test_poller_runs_and_zeroes_duty_on_exit():
    src = FakeSepicHardware()
    with Poller(src, LIMITS, poll_period_s=0.005) as poller:
        poller.set_duty(0.2)
        import time

        time.sleep(0.05)
        samples = poller.all_samples()
        assert len(samples) > 2
        assert samples[-1].duty == 0.2

    # Exit must reset duty to 0
    assert src.writes[-1] == 0.0


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        (Limits(i_in_max=0.05, v_in_max=30.0, v_out_max=25.0), "I in"),
        (Limits(i_in_max=1.0, v_in_max=10.0, v_out_max=25.0), "V in"),
        (Limits(i_in_max=1.0, v_in_max=30.0, v_out_max=2.0), "V out"),
    ],
)
def test_poller_trips_on_safety_limits(limits, reason):
    src = FakeSepicHardware()
    with Poller(src, limits, poll_period_s=0.005) as poller:
        poller.set_duty(0.3)
        import time

        time.sleep(0.05)
        assert poller.abort_reason() is not None
        assert reason in poller.abort_reason()

    assert src.writes[-1] == 0.0


def test_poller_trips_on_dead_link():
    src = FakeSepicHardware(bad_frames=50)
    with Poller(src, LIMITS, poll_period_s=0.005) as poller:
        import time

        time.sleep(0.05)
        assert poller.abort_reason() is not None
        assert "link down" in poller.abort_reason()


def test_poller_trips_on_source_exception():
    src = FakeSepicHardware(fail_after=3)
    with Poller(src, LIMITS, poll_period_s=0.005) as poller:
        poller.set_duty(0.1)
        import time

        time.sleep(0.05)
        assert poller.abort_reason() is not None
        assert "SPI link failure" in poller.abort_reason()


def test_run_step_response_test_simulated():
    src = SimulatedSepicStepSource(v_in=12.0, load_ohms=10.0, ripple_mv=20.0)
    with Poller(src, LIMITS, poll_period_s=0.003) as poller:
        results = run_step_response_test(
            poller,
            steps=[0.1, 0.25],
            settle_s=0.1,
            window_s=0.15,
            tolerance_pct=2.0,
        )

    assert len(results) == 1
    r = results[0]
    assert r.step_idx == 1
    assert r.duty_initial == 0.1
    assert r.duty_target == 0.25
    assert r.v_out_initial == pytest.approx(12.0 * 0.1 / 0.9, abs=0.2)
    assert r.v_out_final == pytest.approx(12.0 * 0.25 / 0.75, abs=0.2)
    assert r.ripple_pp_mv > 0.0
    assert r.settling_time_ms is not None
    assert 10.0 < r.settling_time_ms < 100.0


def test_export_csv(tmp_path: Path):
    samples = [
        Sample(timestamp=0.0, duty=0.1, v_in=12.0, i_in=0.1, v_out=1.3),
        Sample(timestamp=0.05, duty=0.3, v_in=12.0, i_in=0.3, v_out=5.1),
    ]
    metrics = StepMetrics(
        step_idx=1,
        duty_initial=0.1,
        duty_target=0.3,
        v_in_mean=12.0,
        v_out_initial=1.3,
        v_out_final=5.1,
        ripple_pp_mv=30.0,
        settling_time_ms=28.5,
        tolerance_pct=2.0,
        n_samples=2,
        samples=samples,
    )
    csv_file = tmp_path / "test_response.csv"
    export_csv([metrics], csv_file, load_ohms=10.0)

    assert csv_file.exists()
    with csv_file.open() as f:
        reader = list(csv.reader(f))
    assert reader[0] == [
        "step_idx",
        "duty_from",
        "duty_to",
        "t_rel_ms",
        "timestamp",
        "duty",
        "v_in",
        "i_in",
        "v_out",
        "load_ohms",
    ]
    assert len(reader) == 3  # Header + 2 samples


def test_run_step_response_requires_two_steps():
    src = FakeSepicHardware()
    with Poller(src, LIMITS) as poller:
        with pytest.raises(ValueError, match="At least 2"):
            run_step_response_test(poller, [0.1])
