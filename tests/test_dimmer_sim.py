"""The simulated dimmer follows the firmware's exposure rules.

The sequences mirror the Rust tests in firmware/dimmer-link/src/exposure.rs
(trip time, no automatic restart, an OFF before the cool-down is remembered).
"""

import re
from pathlib import Path

import pytest

from mpp_sdk.io.dimmer import MAX_LAMP_WINDOW_S
from mpp_sdk.io.dimmer_sim import EXPOSURE_MAX_ON_S, EXPOSURE_RESUME_S, SimulatedDimmer


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def dimmer(clock):
    return SimulatedDimmer(clock)


def _trip(dimmer, clock):
    """Lamp on with refreshed windows, no status read, until the trip. Returns at the trip."""
    dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    clock.advance(100.0)
    dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    clock.advance(20.0)


def test_constants_match_the_firmware():
    src = (Path(__file__).parent.parent / "firmware/dimmer-link/src/lib.rs").read_text()
    max_ms = int(re.search(r"EXPOSURE_MAX_ON_MS: u32 = ([\d_]+)", src).group(1).replace("_", ""))
    resume_ms = int(re.search(r"EXPOSURE_RESUME_MS: u32 = ([\d_]+)", src).group(1).replace("_", ""))
    assert max_ms == EXPOSURE_MAX_ON_S * 1000
    assert resume_ms == EXPOSURE_RESUME_S * 1000


def test_fresh_dimmer_is_off_with_full_budget(dimmer):
    status = dimmer.dimmer_status()
    assert status.link_ok and not status.tripped and status.budget_s == 120
    assert dimmer.dimmer_window_left_s() is None


def test_window_ends_at_its_deadline(dimmer, clock):
    dimmer.set_dimmer_power(0.5, max_on_s=10.0)
    assert dimmer.dimmer_window_left_s() == pytest.approx(10.0)
    clock.advance(9.99)
    assert dimmer.dimmer_window_left_s() is not None
    clock.advance(0.01)
    assert dimmer.dimmer_window_left_s() is None
    assert dimmer.dimmer_status().applied_alpha_deg is None


def test_budget_counts_down_while_on_and_up_while_off(dimmer, clock):
    dimmer.set_dimmer_power(1.0, max_on_s=60.0)
    clock.advance(10.5)
    assert dimmer.dimmer_status().budget_s == 109
    dimmer.dimmer_off()
    clock.advance(5.0)
    assert dimmer.dimmer_status().budget_s == 114


def test_window_longer_than_the_cap_is_refused(dimmer):
    with pytest.raises(ValueError):
        dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S + 1)


def test_trips_after_exactly_the_max_on_time(dimmer, clock):
    dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    clock.advance(MAX_LAMP_WINDOW_S - 0.01)
    assert not dimmer.dimmer_status().tripped
    clock.advance(0.01)
    assert dimmer.dimmer_status().tripped


def test_trip_status_shows_tripped_and_sends_the_acknowledgment_off(dimmer, clock):
    _trip(dimmer, clock)
    status = dimmer.dimmer_status()
    assert status.tripped and status.budget_s == 60
    assert dimmer.dimmer_window_left_s() is None  # the host sent OFF


def test_a_stream_of_on_commands_never_clears_the_latch(dimmer, clock):
    _trip(dimmer, clock)
    # The host keeps repeating its old "on" for far longer than the cool-down.
    for _ in range(30):
        clock.advance(10.0)
        dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    assert dimmer._tripped
    status = dimmer.dimmer_status()
    assert status.tripped and status.budget_s == 0  # cooled, waiting for OFF
    # That status read sent the acknowledgment OFF, so now it clears.
    assert not dimmer.dimmer_status().tripped


def test_a_tripped_lamp_resumes_only_after_cool_down_and_off(dimmer, clock):
    _trip(dimmer, clock)
    dimmer.dimmer_off()  # acknowledgment too early
    clock.advance(EXPOSURE_MAX_ON_S - EXPOSURE_RESUME_S - 1.0)
    assert dimmer.dimmer_status().tripped
    clock.advance(1.0)
    status = dimmer.dimmer_status()
    assert not status.tripped and status.budget_s == 60


def test_an_off_before_the_cool_down_ends_is_remembered(dimmer, clock):
    _trip(dimmer, clock)
    clock.advance(10.0)
    dimmer.dimmer_off()
    assert dimmer.dimmer_status().tripped
    # 50 s to go, then it clears by itself, with no new OFF.
    clock.advance(49.99)
    assert dimmer.dimmer_status().tripped
    clock.advance(0.01)
    assert not dimmer.dimmer_status().tripped


def test_an_off_before_the_trip_does_not_count(dimmer, clock):
    dimmer.dimmer_off()
    _trip(dimmer, clock)
    for _ in range(12):
        clock.advance(10.0)
        dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    # Cooled, but the only OFF came before the trip: still latched.
    assert dimmer._tripped


def test_the_deadline_off_after_the_trip_acknowledges(dimmer, clock):
    # The host's deadline OFF is an explicit OFF, as on the real dimmer.
    dimmer.set_dimmer_power(1.0, max_on_s=MAX_LAMP_WINDOW_S)
    clock.advance(MAX_LAMP_WINDOW_S + EXPOSURE_MAX_ON_S)
    assert not dimmer.dimmer_status().tripped


def test_repeated_short_windows_fill_the_bucket(dimmer, clock):
    for _ in range(12):
        dimmer.set_dimmer_power(1.0, max_on_s=10.0)
        clock.advance(10.0)
    assert dimmer.dimmer_status().tripped
