"""Unit tests for DemoSweepSource (curve_tracer_server.py --demo).

Pure stdlib, no hardware, no real time - a fake `clock` callable drives
the wall-clock-paced sweep deterministically.
"""

from scripts.curve_tracer_demo_source import _DEMO_POINT_INTERVAL_S, _DEMO_POINTS, DemoSweepSource


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ------------------------------------------------------------------
# Before any sweep
# ------------------------------------------------------------------


def test_no_sweep_yet_reports_nothing():
    src = DemoSweepSource(clock=_FakeClock())
    assert src.request_sweep() is None
    assert src.poll_sweep_progress() is None


# ------------------------------------------------------------------
# During a sweep
# ------------------------------------------------------------------


def test_progress_advances_with_elapsed_time():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()

    p0 = src.poll_sweep_progress()
    assert p0.index == 0
    assert p0.active is True
    assert p0.final_point is False

    clock.advance(_DEMO_POINT_INTERVAL_S * 5)
    p5 = src.poll_sweep_progress()
    assert p5.index == 5
    assert p5.active is True


def test_request_sweep_returns_none_while_running():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * 3)
    assert src.request_sweep() is None


def test_start_sweep_mid_sweep_is_ignored():
    """Matches mode_curve_tracer.rs: a trigger while a sweep is already
    running has no effect - it does not restart the curve. Checked through
    the public API: a restart would reset the elapsed-time anchor, so
    poll_sweep_progress() would report index 0 again instead of continuing
    from where it was."""
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * 3)
    progress_before = src.poll_sweep_progress()
    src.start_sweep()
    progress_after = src.poll_sweep_progress()
    assert progress_after == progress_before


# ------------------------------------------------------------------
# Sweep completion
# ------------------------------------------------------------------


def test_full_sweep_duration_completes_all_points():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * _DEMO_POINTS)

    progress = src.poll_sweep_progress()
    assert progress.index == _DEMO_POINTS - 1
    assert progress.active is False
    assert progress.final_point is True


def test_request_sweep_delivers_once_then_none():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * _DEMO_POINTS)

    points = src.request_sweep()
    assert len(points) == _DEMO_POINTS
    assert src.request_sweep() is None


def test_poll_sweep_progress_keeps_reporting_final_state_after_completion():
    """Peek, not consume - matches mode_curve_tracer::peek_progress()."""
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * _DEMO_POINTS)
    src.request_sweep()

    p1 = src.poll_sweep_progress()
    p2 = src.poll_sweep_progress()
    assert p1 == p2
    assert p1.active is False


def test_a_second_sweep_starts_fresh_after_completion():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * _DEMO_POINTS)
    src.request_sweep()

    src.start_sweep()
    progress = src.poll_sweep_progress()
    assert progress.index == 0
    assert progress.active is True


# ------------------------------------------------------------------
# Points shape
# ------------------------------------------------------------------


def test_points_are_descending_voltage_matching_a_real_sweep():
    clock = _FakeClock()
    src = DemoSweepSource(clock=clock)
    src.start_sweep()
    clock.advance(_DEMO_POINT_INTERVAL_S * _DEMO_POINTS)
    points = src.request_sweep()

    voltages = [v for v, _ in points]
    assert voltages == sorted(voltages, reverse=True)
    assert all(i >= 0.0 for _, i in points)


def test_context_manager_protocol():
    with DemoSweepSource() as src:
        assert src.poll_sweep_progress() is None
