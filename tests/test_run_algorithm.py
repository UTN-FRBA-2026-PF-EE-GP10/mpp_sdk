"""Tests for `scripts.run_algorithm.run_control_loop` only - not `main()`,
not the sweep/save half (both need real hardware). A minimal in-test fake
source is enough since this function only calls `.read()`/`.write()`,
nothing curve-tracer-specific.
"""

from scripts.run_algorithm import run_control_loop


class _FakeSource:
    """Minimal SignalSource fake: read() returns whatever write() last
    received, run through a trivial linear plant (V drops as duty rises) -
    just enough for run_control_loop's own logic to be exercised, not a
    physically accurate model."""

    def __init__(self):
        self._duty = 0.0

    def write(self, duty):
        self._duty = duty

    def read(self):
        v = 20.0 * (1.0 - self._duty)
        i = 0.2 * self._duty
        return v, i


class _FixedDutyAlgorithm:
    def __init__(self, duty):
        self._duty = duty

    def step(self, voltage, current):
        return self._duty


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_seeds_with_initial_duty_before_first_read():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.3),
        duration_s=0.0,
        v_max=100.0,
        i_max=100.0,
        initial_duty=0.5,
        clock=clock,
        sleep=lambda _: None,
    )
    # duration_s=0.0 means the while-condition is false immediately, but
    # the seed write() must still have happened - confirmed indirectly via
    # the fake source's internal state.
    assert source._duty == 0.5
    assert samples == []
    assert aborted is False


def test_records_one_sample_per_step():
    source = _FakeSource()
    clock = _FakeClock()

    def sleep(dt):
        clock.advance(dt)

    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=0.3,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=sleep,
        period_s=0.1,
    )
    assert len(samples) == 3  # t=0, 0.1, 0.2 - loop exits once clock - start >= 0.3
    assert aborted is False
    assert all(s.duty == 0.25 for s in samples)


def test_safety_abort_on_overvoltage_stops_and_zeroes_duty():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=1.0,  # source's V at duty=0.5 (seed) is 10.0 - immediately over
        i_max=100.0,
        initial_duty=0.5,
        clock=clock,
        sleep=lambda _: None,
    )
    assert aborted is True
    assert samples == []
    assert source._duty == 0.0  # driven to zero, not left at the offending duty


def test_safety_abort_on_overcurrent():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.9),
        duration_s=10.0,
        v_max=100.0,
        i_max=0.05,  # source's I at duty=0.9 (seed) is 0.18 - over
        initial_duty=0.9,
        clock=clock,
        sleep=lambda _: None,
    )
    assert aborted is True
    assert source._duty == 0.0
