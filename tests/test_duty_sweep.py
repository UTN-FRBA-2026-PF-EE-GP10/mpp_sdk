"""`scripts/duty_sweep.py`: the step logic and its safety behaviour, against a
fake board (no spidev)."""

from __future__ import annotations

import threading
import time

import pytest

from scripts.duty_sweep import MAX_DUTY, Limits, Poller, SweepAborted, run_step


class FakeSepic:
    """5 V in, 10 Ohm out, 85 % efficient, ideal transfer ratio."""

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
            raise RuntimeError("SPI fault")
        self.vout = 5.0 * self.duty / (1.0 - self.duty)
        p_out = self.vout**2 / 10.0
        return 5.0, (p_out / 0.85) / 5.0


LIMITS = Limits(i_in_max=1.0, v_in_max=30.0, v_out_max=25.0)


def test_a_step_averages_the_readings_at_the_commanded_duty():
    src = FakeSepic()
    with Poller(src, LIMITS) as poller:
        r = run_step(poller, 0.25, hold_s=0.3, avg_s=0.15)
    assert r.duty == 0.25
    assert r.v_in == pytest.approx(5.0)
    assert r.v_out_adc == pytest.approx(5.0 * 0.25 / 0.75)
    assert r.n_samples > 0


def test_duty_returns_to_zero_when_the_sweep_ends():
    src = FakeSepic()
    with Poller(src, LIMITS) as poller:
        run_step(poller, 0.3, hold_s=0.2, avg_s=0.1)
    assert src.writes[-1] == 0.0


def test_the_meter_reading_is_recorded_next_to_the_adc():
    with Poller(FakeSepic(), LIMITS) as poller:
        r = run_step(poller, 0.2, hold_s=0.2, avg_s=0.1, meter=lambda d: 1.23)
    assert r.v_out_meter == 1.23


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        (Limits(i_in_max=0.2, v_in_max=30.0, v_out_max=25.0), "I in"),
        (Limits(i_in_max=1.0, v_in_max=4.0, v_out_max=25.0), "V in"),
        (Limits(i_in_max=1.0, v_in_max=30.0, v_out_max=3.0), "V out"),
    ],
)
def test_a_tripped_limit_aborts_and_zeroes_the_duty(limits, reason):
    src = FakeSepic()
    with pytest.raises(SweepAborted, match=reason), Poller(src, limits) as poller:
        run_step(poller, 0.45, hold_s=0.3, avg_s=0.1)
    assert src.writes[-1] == 0.0


def test_a_dead_link_aborts_the_sweep():
    src = FakeSepic(bad_frames=100)
    with pytest.raises(SweepAborted, match="link down"), Poller(src, LIMITS) as poller:
        run_step(poller, 0.1, hold_s=0.2, avg_s=0.1)
    assert src.writes[-1] == 0.0


def test_a_source_error_aborts_the_sweep_with_zero_duty():
    src = FakeSepic(fail_after=2)
    with pytest.raises(SweepAborted, match="SPI fault"), Poller(src, LIMITS) as poller:
        run_step(poller, 0.3, hold_s=0.3, avg_s=0.1)
    assert src.writes[-1] == 0.0


@pytest.mark.parametrize("duty", [-0.1, MAX_DUTY + 0.01, 0.5])
def test_a_duty_outside_the_cap_is_refused_before_anything_is_driven(duty):
    src = FakeSepic()
    with pytest.raises(ValueError), Poller(src, LIMITS) as poller:
        run_step(poller, duty, hold_s=0.1, avg_s=0.1)
    assert max(src.writes) == 0.0


def test_an_averaging_window_longer_than_the_hold_is_refused():
    """It would mix in the previous step's duty and report both as one."""
    src = FakeSepic()
    with pytest.raises(ValueError, match="avg_s"), Poller(src, LIMITS) as poller:
        run_step(poller, 0.2, hold_s=0.1, avg_s=1.0)
    assert max(src.writes) == 0.0


class WedgedSepic(FakeSepic):
    """An SPI transfer that never returns, from the 4th write on."""

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0
        self.release = threading.Event()

    def write(self, duty: float) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            super().write(duty)
            if len(self.writes) >= 4:
                self.release.wait(5.0)
        finally:
            self.in_flight -= 1


def test_exit_never_puts_a_second_transfer_on_a_wedged_link():
    src = WedgedSepic()
    try:
        with Poller(src, LIMITS) as poller:
            poller.set_duty(0.1)
            time.sleep(0.3)
        assert src.max_in_flight == 1
    finally:
        src.release.set()
