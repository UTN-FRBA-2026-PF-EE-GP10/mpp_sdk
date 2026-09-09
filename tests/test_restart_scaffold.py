"""Unit tests for the private validation/restart/handoff helpers shared by
ScanAndTrack and ParticleSwarm (mpp_sdk/algorithms/restart.py). These are
implementation details (leading-underscore, not part of the public API)
but are tested directly because they are exactly the kind of small,
easily-inverted logic (see restart.py's `_restart_due` docstring on the
short-circuit trap) that benefits from isolated coverage on top of the two
algorithms' own end-to-end test suites."""

import pytest

from mpp_sdk.algorithms import restart


def test_validate_duty_range_accepts_valid_range():
    restart._validate_duty_range(0.05, 0.95)  # must not raise


def test_validate_duty_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        restart._validate_duty_range(0.9, 0.1)


def test_validate_finite_positive_rejects_zero():
    with pytest.raises(ValueError) as exc:
        restart._validate_finite_positive("track_step", 0.0)
    assert str(exc.value) == "track_step must be a finite positive number; got track_step=0.0"


def test_validate_finite_positive_rejects_negative():
    with pytest.raises(ValueError):
        restart._validate_finite_positive("track_step", -0.01)


def test_validate_rescan_period_accepts_none():
    restart._validate_rescan_period(None)  # must not raise


def test_validate_rescan_period_rejects_zero():
    with pytest.raises(ValueError):
        restart._validate_rescan_period(0)


def test_make_restart_detector_none_threshold_gives_no_detector():
    assert restart._make_restart_detector(None, 3) is None


def test_make_restart_detector_builds_a_real_detector():
    detector = restart._make_restart_detector(0.2, 3)
    assert isinstance(detector, restart.PowerChangeDetector)


def test_restart_due_true_on_periodic_backstop_without_touching_detector():
    calls = []

    class _SpyDetector:
        def update(self, power):
            calls.append(power)
            return False

    # steps_since_restart (5) >= rescan_period (5): backstop fires. The
    # detector must NOT be consulted - this is the short-circuit this
    # function exists to preserve.
    assert restart._restart_due(_SpyDetector(), 5, 5, 12.3) is True
    assert calls == []


def test_restart_due_consults_the_detector_when_the_backstop_is_not_due():
    class _AlwaysFires:
        def update(self, power):
            return True

    assert restart._restart_due(_AlwaysFires(), 10, 3, 12.3) is True


def test_restart_due_false_when_neither_condition_holds():
    class _NeverFires:
        def update(self, power):
            return False

    assert restart._restart_due(_NeverFires(), 10, 3, 12.3) is False
    assert restart._restart_due(None, None, 3, 12.3) is False


def test_make_local_tracker_returns_a_seeded_perturb_and_observe():
    from mpp_sdk.algorithms.perturb_observe import PerturbAndObserve

    tracker = restart._make_local_tracker(0.42, 0.005, 0.05, 0.95)
    assert isinstance(tracker, PerturbAndObserve)
    assert tracker.duty == pytest.approx(0.42)
