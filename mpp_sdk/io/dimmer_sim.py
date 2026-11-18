"""Simulated lamp dimmer for the server's --demo mode and for tests.

It offers the lamp methods of ``SpiMcuSource`` (set, off, status, window left)
and applies the same rules as the dimmer firmware (``firmware/dimmer-link/src/
exposure.rs``): a host window with a deadline, and a leaky bucket of commanded
on time. The bucket trips at ``EXPOSURE_MAX_ON_S``, cools 1:1 while the lamp is
off, and a trip clears only when it is cooled to ``EXPOSURE_RESUME_S`` AND the
host sent an explicit OFF after the trip. The clock is injectable, so tests
run the rules with no waiting.

No thread: the state is advanced lazily, to the clock, on every call.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from .dimmer import (
    ALPHA_OFF_DEG,
    DEFAULT_LAMP_WINDOW_S,
    WIRE_ALPHA_OFF,
    DimmerStatus,
    alpha_for_power,
    alpha_to_wire,
    validate_max_on_s,
)

# Mirror dimmer-link's EXPOSURE_MAX_ON_MS / EXPOSURE_RESUME_MS (a test compares).
EXPOSURE_MAX_ON_S = 120.0
EXPOSURE_RESUME_S = 60.0
_U8_MAX = 255


class SimulatedDimmer:
    """Same lamp API and exposure rules as the real dimmer, driven by a clock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._last = clock()
        self._heat_s = 0.0
        self._tripped = False
        self._off_seen = False
        # What the host asked for (its keepalive state), and its deadline.
        self._host_alpha: float | None = None
        self._deadline: float | None = None

    # -- rules ---------------------------------------------------------------

    def _lamp_on(self) -> bool:
        """The dimmer's commanded state: the host wants on and no trip is latched."""
        return self._host_alpha is not None and not self._tripped

    def _off_command(self) -> None:
        if self._tripped:
            self._off_seen = True
            self._try_clear()

    def _try_clear(self) -> None:
        if self._tripped and self._off_seen and self._heat_s <= EXPOSURE_RESUME_S:
            self._tripped = False
            self._off_seen = False

    def _advance(self) -> None:
        """Run the bucket from the last call to now, splitting at the deadline and the trip."""
        now = self._clock()
        while self._last < now:
            end = now
            deadline_hit = False
            if (
                self._host_alpha is not None
                and self._deadline is not None
                and self._last < self._deadline <= now
            ):
                end = self._deadline
                deadline_hit = True
            on = self._lamp_on()
            trip_hit = False
            if on:
                time_to_trip = EXPOSURE_MAX_ON_S - self._heat_s
                if self._last + time_to_trip <= end:
                    end = self._last + time_to_trip
                    trip_hit = True
                    deadline_hit = deadline_hit and end == self._deadline
                self._heat_s = min(EXPOSURE_MAX_ON_S, self._heat_s + (end - self._last))
            else:
                self._heat_s = max(0.0, self._heat_s - (end - self._last))
            self._last = end
            if trip_hit:
                self._tripped = True
                self._off_seen = False
            if deadline_hit:
                # The host keepalive sends OFF at its deadline. That OFF counts as
                # explicit, as on the real dimmer.
                self._host_alpha = None
                self._deadline = None
                self._off_command()
            self._try_clear()

    # -- the lamp API of SpiMcuSource ------------------------------------------

    def set_dimmer_alpha(
        self, alpha_deg: float, *, max_on_s: float = DEFAULT_LAMP_WINDOW_S
    ) -> None:
        window = validate_max_on_s(max_on_s)
        wire = alpha_to_wire(alpha_deg)
        if wire == WIRE_ALPHA_OFF:
            self.dimmer_off()
            return
        with self._lock:
            self._advance()
            # A tripped dimmer refuses silently; the host still believes "on",
            # as with the real link, until a status read acknowledges the trip.
            self._host_alpha = wire / 100.0
            self._deadline = self._clock() + window

    def set_dimmer_power(self, fraction: float, *, max_on_s: float = DEFAULT_LAMP_WINDOW_S) -> None:
        self.set_dimmer_alpha(alpha_for_power(fraction), max_on_s=max_on_s)

    def dimmer_off(self) -> None:
        with self._lock:
            self._advance()
            self._host_alpha = None
            self._deadline = None
            self._off_command()

    def dimmer_window_left_s(self) -> float | None:
        with self._lock:
            self._advance()
            if self._host_alpha is None or self._deadline is None:
                return None
            return max(0.0, self._deadline - self._clock())

    def dimmer_status(self) -> DimmerStatus:
        with self._lock:
            self._advance()
            status = self._status()
            if status.tripped and self._host_alpha is not None:
                # Same as SpiMcuSource: the acknowledgment OFF after a trip. The
                # status returned is the one read before it, as on the real link.
                self.dimmer_off()
            return status

    def _status(self) -> DimmerStatus:
        if self._tripped:
            budget = math.ceil(max(0.0, self._heat_s - EXPOSURE_RESUME_S))
        else:
            budget = math.floor(EXPOSURE_MAX_ON_S - self._heat_s)
        alpha = self._host_alpha if self._host_alpha is not None else ALPHA_OFF_DEG
        on = self._lamp_on()
        return DimmerStatus(
            link_ok=True,
            mains=True,
            locked=True,
            timed_out=False,
            set_alpha_deg=alpha if on else ALPHA_OFF_DEG,
            applied_alpha_deg=alpha if on else None,
            age_s=0.0,
            tripped=self._tripped,
            budget_s=min(_U8_MAX, budget),
        )

    def close(self) -> None:
        self.dimmer_off()
