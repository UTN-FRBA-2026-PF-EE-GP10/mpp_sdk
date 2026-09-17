"""Tests for `scripts.run_algorithm.run_control_loop` only - not `main()`,
not the sweep/save half (both need real hardware). A minimal in-test fake
source is enough since this function only calls `.read()`/`.write()` (and,
for the link-down abort, reads `.consecutive_bad_frames` if present),
nothing curve-tracer-specific.
"""

import pytest

from scripts.run_algorithm import run_control_loop


class _FakeSource:
    """Minimal SignalSource fake: read() returns whatever write() last
    received, run through a trivial linear plant (V drops as duty rises) -
    just enough for run_control_loop's own logic to be exercised, not a
    physically accurate model. Records every write() call so a test can
    check duty was zeroed at the very end, not just mid-run."""

    def __init__(self):
        self._duty = 0.0
        self.writes: list[float] = []

    def write(self, duty):
        self._duty = duty
        self.writes.append(duty)

    def read(self):
        v = 20.0 * (1.0 - self._duty)
        i = 0.2 * self._duty
        return v, i


class _FakeSourceWithBadFrames(_FakeSource):
    """Same plant, plus a `consecutive_bad_frames` counter a test can push
    up to simulate a disconnected board (see SpiMcuSource's real one)."""

    def __init__(self):
        super().__init__()
        self.consecutive_bad_frames = 0


class _RaisingFirstWriteSource(_FakeSource):
    """`write()` raises on its first call (the seed) and works normally
    after that - checks the zero-duty guarantee survives a seed write
    that fails, not just a mid-loop one."""

    def write(self, duty):
        super().write(duty)
        if len(self.writes) == 1:
            raise RuntimeError("seed write failed")


class _FixedDutyAlgorithm:
    def __init__(self, duty):
        self._duty = duty

    def step(self, voltage, current):
        return self._duty


class _RaisingAlgorithm:
    """Raises on its second step() call - simulates an algorithm bug or
    any other exception mid-run, to check the loop still zeroes duty."""

    def __init__(self):
        self.calls = 0

    def step(self, voltage, current):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("boom")
        return 0.3


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
    samples, aborted, reason = run_control_loop(
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
    # the seed write() must still have happened - confirmed via the write
    # log (the very last write, the unconditional end-of-run zero, would
    # otherwise hide it from the final-state assertion alone).
    assert source.writes[0] == 0.5
    assert samples == []
    assert aborted is False
    assert reason is None


def test_records_one_sample_per_step():
    source = _FakeSource()
    clock = _FakeClock()

    def sleep(dt):
        clock.advance(dt)

    samples, aborted, reason = run_control_loop(
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
    assert reason is None
    assert all(s.duty == 0.25 for s in samples)


def test_normal_completion_still_zeroes_duty():
    """Only the CLI's `with SpiMcuSource() as src:` block zeroes duty on
    ordinary teardown - a caller that keeps the source open across many
    runs (the web server) gets no such teardown per run, so the loop
    itself must guarantee this on every exit path, not just an abort."""
    source = _FakeSource()
    clock = _FakeClock()
    run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=0.3,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=lambda dt: clock.advance(dt),
        period_s=0.1,
    )
    assert source._duty == 0.0
    assert source.writes[-1] == 0.0


def test_a_raising_seed_write_still_gets_a_zero_duty_write_attempted():
    """The seed write happens inside the try now, not before it - so a
    seed that raises must still reach the `finally`'s zero-duty write,
    not skip it entirely."""
    source = _RaisingFirstWriteSource()
    clock = _FakeClock()
    with pytest.raises(RuntimeError, match="seed write failed"):
        run_control_loop(
            source,
            _FixedDutyAlgorithm(0.3),
            duration_s=10.0,
            v_max=100.0,
            i_max=100.0,
            clock=clock,
            sleep=lambda _: None,
        )
    assert len(source.writes) == 2
    assert source.writes == [0.5, 0.0]  # default initial_duty seed, then the zero-duty guarantee


def test_samples_argument_is_populated_in_place_even_when_the_loop_raises():
    """A caller-owned `samples` list must keep whatever was recorded
    before an exception propagates, so a mid-run crash doesn't lose data
    the caller already has a handle on."""
    source = _FakeSource()
    clock = _FakeClock()
    collected: list = []
    with pytest.raises(RuntimeError, match="boom"):
        run_control_loop(
            source,
            _RaisingAlgorithm(),
            duration_s=10.0,
            v_max=100.0,
            i_max=100.0,
            clock=clock,
            sleep=lambda dt: clock.advance(dt),
            period_s=0.01,
            samples=collected,
        )
    # _RaisingAlgorithm raises on its second step() call, so exactly one
    # sample was recorded before the failure.
    assert len(collected) == 1
    assert source._duty == 0.0


def test_safety_abort_on_overvoltage_stops_and_zeroes_duty():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted, reason = run_control_loop(
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
    assert reason == "overvoltage"
    assert samples == []
    assert source._duty == 0.0  # driven to zero, not left at the offending duty


def test_safety_abort_on_overcurrent():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted, reason = run_control_loop(
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
    assert reason == "overcurrent"
    assert source._duty == 0.0


def test_link_down_aborts_when_bad_frames_stays_high():
    source = _FakeSourceWithBadFrames()
    source.consecutive_bad_frames = 5
    clock = _FakeClock()
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=100.0,
        i_max=100.0,
        initial_duty=0.5,
        clock=clock,
        sleep=lambda _: None,
        max_consecutive_bad_frames=5,
    )
    assert aborted is True
    assert reason == "link-down"
    assert samples == []
    assert source._duty == 0.0


def test_a_fake_source_with_no_bad_frames_attribute_never_trips_link_down():
    """A source with no `consecutive_bad_frames` at all (like the plain
    _FakeSource above, or a simulated source) must never trip this abort -
    getattr(..., 0) has to default to "healthy", not "down"."""
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=0.05,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=lambda dt: clock.advance(dt),
        period_s=0.01,
        max_consecutive_bad_frames=1,
    )
    assert aborted is False
    assert reason is None
    assert len(samples) > 0


def test_should_stop_aborts_the_run_and_zeroes_duty():
    clock = _FakeClock()
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) >= 3  # stop on the third check, mid-run

    source = _FakeSource()
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=10.0,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=lambda dt: clock.advance(dt),
        period_s=0.01,
        should_stop=should_stop,
    )
    assert aborted is True
    assert reason == "stopped"
    assert len(samples) == 2  # two steps recorded before the third check fires
    assert source._duty == 0.0


def test_duty_is_zeroed_even_when_algorithm_raises():
    source = _FakeSource()
    clock = _FakeClock()
    with pytest.raises(RuntimeError, match="boom"):
        run_control_loop(
            source,
            _RaisingAlgorithm(),
            duration_s=10.0,
            v_max=100.0,
            i_max=100.0,
            clock=clock,
            sleep=lambda dt: clock.advance(dt),
            period_s=0.01,
        )
    assert source._duty == 0.0
    assert source.writes[-1] == 0.0


def test_on_sample_is_called_once_per_recorded_sample():
    source = _FakeSource()
    clock = _FakeClock()
    seen = []
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=0.3,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=lambda dt: clock.advance(dt),
        period_s=0.1,
        on_sample=seen.append,
    )
    assert seen == samples
