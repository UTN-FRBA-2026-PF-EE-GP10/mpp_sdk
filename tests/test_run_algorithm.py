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

    def tick():
        clock.advance(0.1)
        return clock()

    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=1.0,  # source's V at duty=0.5 (seed) is 10.0 - immediately over
        i_max=100.0,
        initial_duty=0.5,
        clock=tick,
        sleep=lambda _: None,
    )
    assert aborted is True
    assert reason == "overvoltage"
    assert samples == []
    assert source._duty == 0.0  # driven to zero, not left at the offending duty


def _ticking_clock(step=0.1):
    """Advances on every call, so a loop whose abort is missing still ends
    at its duration and fails an assertion rather than hanging."""
    clock = _FakeClock()

    def tick():
        clock.advance(step)
        return clock()

    return tick


class _FakeSourceWithVout(_FakeSource):
    """Adds the converter output SpiMcuSource exposes: a light load makes
    it climb with duty while the panel side stays well inside its limits."""

    @property
    def vout(self):
        return 60.0 * self._duty


def test_safety_abort_on_output_overvoltage_stops_and_zeroes_duty():
    source = _FakeSourceWithVout()
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=100.0,
        i_max=100.0,
        v_out_max=25.0,  # V out at the 0.5 seed is 30 V
        initial_duty=0.5,
        clock=_ticking_clock(),
        sleep=lambda _: None,
    )
    assert aborted is True
    assert reason == "output-overvoltage"
    assert samples == []
    assert source._duty == 0.0


def test_output_limit_never_trips_on_a_source_without_vout():
    """A simulated source has no converter output to read."""
    clock = _FakeClock()
    _, aborted, reason = run_control_loop(
        _FakeSource(),
        _FixedDutyAlgorithm(0.5),
        duration_s=0.0,
        v_max=100.0,
        i_max=100.0,
        v_out_max=0.001,
        clock=clock,
        sleep=lambda _: None,
    )
    assert (aborted, reason) == (False, None)


def test_safety_abort_on_overcurrent():
    source = _FakeSource()
    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.9),
        duration_s=10.0,
        v_max=100.0,
        i_max=0.05,  # source's I at duty=0.9 (seed) is 0.18 - over
        initial_duty=0.9,
        clock=_ticking_clock(),
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


class _ScriptedSource(_FakeSource):
    """Returns the plant's reading, except on the read() numbers in `bad`,
    which return `bad_reading` instead - a garbage frame from the link."""

    def __init__(self, bad, bad_reading):
        super().__init__()
        self._bad = set(bad)
        self._bad_reading = bad_reading
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.reads in self._bad:
            return self._bad_reading
        return super().read()


class _RecordingAlgorithm:
    def __init__(self, duty):
        self._duty = duty
        self.seen: list[tuple[float, float]] = []

    def step(self, voltage, current):
        self.seen.append((voltage, current))
        return self._duty


def test_a_short_burst_of_bad_readings_is_ignored_and_never_reaches_the_algorithm():
    source = _ScriptedSource(bad={3, 4}, bad_reading=(50.0, 6.0))
    algorithm = _RecordingAlgorithm(0.5)
    samples, aborted, reason = run_control_loop(
        source,
        algorithm,
        duration_s=1.0,
        v_max=40.0,
        i_max=1.0,
        initial_duty=0.5,
        clock=_ticking_clock(step=0.01),
        sleep=lambda _: None,
    )
    assert (aborted, reason) == (False, None)
    assert all(v <= 40.0 and i <= 1.0 for v, i in algorithm.seen)
    assert all(s.voltage <= 40.0 and s.current <= 1.0 for s in samples)


def test_a_long_run_of_bad_readings_aborts_only_once_the_window_has_passed():
    """Every read after the first few is over the limit. With a fast clock
    the 5 readings in a row pass long before 50 ms do, so the run must
    keep going until the streak spans the window."""
    source = _ScriptedSource(bad=range(3, 10_000), bad_reading=(20.0, 6.0))
    clock = _FakeClock()
    calls = []

    def tick():
        clock.advance(0.001)
        calls.append(clock())
        return clock()

    samples, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=40.0,
        i_max=1.0,
        initial_duty=0.5,
        clock=tick,
        sleep=lambda _: None,
    )
    assert (aborted, reason) == (True, "overcurrent")
    # 2 clock calls per step at 1 ms each: the streak must span at least 50 ms.
    assert source.reads > 5 + 20
    assert source._duty == 0.0


def test_bad_readings_split_by_a_good_one_do_not_add_up():
    bad = [n for n in range(3, 400) if n % 4]  # 3 bad, 1 good, 3 bad ...
    source = _ScriptedSource(bad=bad, bad_reading=(20.0, 6.0))
    _, aborted, reason = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=0.3,
        v_max=40.0,
        i_max=1.0,
        initial_duty=0.5,
        clock=_ticking_clock(step=0.001),
        sleep=lambda _: None,
    )
    assert (aborted, reason) == (False, None)
