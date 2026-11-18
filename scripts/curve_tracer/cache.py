"""Thread-safe state shared by the poll thread and request threads."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, NamedTuple

from mpp_sdk.curves.record import now_utc
from scripts.curve_tracer.limits import _SWEEP_PENDING_TIMEOUT_S

if TYPE_CHECKING:
    from mpp_sdk.io.spi_mcu import SweepProgress


class _Snapshot(NamedTuple):
    """One consistent read of `_SweepCache`, taken under its lock. Named
    rather than a bare tuple so a new field doesn't silently shift every
    caller's positional unpacking."""

    points: list[tuple[float, float]]
    link: str
    seq: int
    partial: list[tuple[float, float]]
    active: bool
    command_error: str | None
    demo_source: bool
    # Which CURVE_SOURCES value a save taken right now should record.
    source: str


class _SweepCache:
    """Shared between the poll thread and request-handling threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._points: list[tuple[float, float]] = []
        self._link = "no data yet"
        # Bumped per fetched sweep so the page can tell "a new sweep
        # landed" from "same sweep, polled again". The point count can't
        # do that job - every completed sweep returns the same 20 points.
        self._seq = 0
        # Keyed by point index rather than a plain list: poll_sweep_progress()
        # is lossy by design (a missed poll just means a gap, not a retry),
        # so points can arrive with holes - sorting by index at snapshot
        # time keeps `partial` in sweep order regardless.
        self._partial: dict[int, tuple[float, float]] = {}
        self._active = False
        # Set by a failed start_sweep()/release_relay(), cleared by the
        # next attempt that succeeds. Kept separate from `_link`: a
        # command can fail on a transient glitch while the very next
        # request_sweep() call (same poll iteration) succeeds, and `set()`
        # would otherwise overwrite the error before any client ever sees
        # it - this field survives that overwrite instead.
        self._command_error: str | None = None
        # What kind of sweep was most recently commanded to the firmware -
        # updated the instant a command is dispatched, before any SPI
        # round trip happens. This is provenance for the PENDING sweep,
        # not for the data currently in `_points`: auto_range() alone can
        # take seconds, and during that window the old sweep's points are
        # still what's on screen. See `_data_demo_source` below.
        self._pending_demo_source = False
        # What kind of sweep produced the points currently held in
        # `_points`. Updated only inside `set()`, at the exact moment a
        # completed sweep's points land in the cache - so GET /api/data
        # and a save always describe the data actually on screen, never a
        # command that hasn't produced a result yet.
        self._data_demo_source = False
        # Set once at startup by _poll_loop when running --demo, where no
        # board is involved at all. Distinct from _data_demo_source, which
        # means a real board replaying a curve it has stored.
        self._simulated = False
        # A sweep was commanded and has not visibly ended yet. A sweep
        # shows as `active` only at its first progress frame, which comes
        # after auto-range (one to three seconds). A run accepted in that
        # gap queues its relay release behind the sweep, and records duty
        # the firmware never applies. Monotonic time of the command, or
        # None when no sweep is pending.
        self._sweep_pending_since: float | None = None
        self._pending_seen_active = False

    def mark_sweep_pending(self) -> None:
        """Call when a sweep command is queued, before it reaches the firmware."""
        with self._lock:
            self._sweep_pending_since = time.monotonic()
            self._pending_seen_active = False

    def sweep_pending(self) -> bool:
        """True from `mark_sweep_pending` until the sweep ends: its result
        lands, it goes active then inactive, or `_SWEEP_PENDING_TIMEOUT_S`
        passes (a dark-panel sweep aborts before any active frame)."""
        with self._lock:
            if self._sweep_pending_since is None:
                return False
            if time.monotonic() - self._sweep_pending_since > _SWEEP_PENDING_TIMEOUT_S:
                self._sweep_pending_since = None
                return False
            return True

    def set(self, points: list[tuple[float, float]] | None, link: str) -> None:
        with self._lock:
            if points is not None:
                self._sweep_pending_since = None
                self._points = points
                self._seq += 1
                # The pending command's provenance becomes the data's
                # provenance only now, together with the points it
                # produced - never earlier, or a save taken while this
                # sweep was still running would describe a command that
                # hadn't finished rather than the (older) data on screen.
                self._data_demo_source = self._pending_demo_source
            self._link = link

    def set_demo_source(self, demo: bool) -> None:
        """Record which kind of sweep was just commanded to the firmware.
        Only the PENDING command's provenance - `set()` above transfers it
        onto `_data_demo_source` once that sweep's points actually arrive."""
        with self._lock:
            self._pending_demo_source = demo

    def set_simulated(self, simulated: bool) -> None:
        with self._lock:
            self._simulated = simulated

    def set_command_error(self, error: str | None) -> None:
        """Record the outcome of the last start_sweep()/release_relay()
        attempt - `None` on success, a message on failure. Call with
        `None` on every success so a stale failure does not linger past
        a retry that worked."""
        with self._lock:
            self._command_error = error

    def set_progress(self, progress: SweepProgress | None) -> None:
        """Update the in-progress-sweep view from one
        `SpiMcuSource.poll_sweep_progress()` result. `None` (a lossy poll
        miss, or no sweep has ever run) leaves `partial`/`active` as they
        were - see that method's docstring."""
        if progress is None:
            return
        with self._lock:
            if progress.active:
                # A new sweep started if we weren't already mid-sweep, or
                # if this point's index is below the highest one we
                # already recorded. Indices only increase within a sweep,
                # so an index below our high-water mark means the previous
                # sweep's tail got skipped and this is the next sweep's
                # own early point. Checking index == 0 alone is not
                # enough: poll_sweep_progress() is lossy, and a new
                # sweep's very first point is often missed entirely -
                # otherwise the previous sweep's leftover points would
                # bleed into this one's `partial`.
                if not self._active or not self._partial or progress.index < max(self._partial):
                    self._partial = {}
                self._partial[progress.index] = (progress.voltage, progress.current)
                self._pending_seen_active = True
            else:
                # Only an inactive frame that follows an active one ends a
                # pending sweep. Before the new sweep starts, the poll can
                # still return the previous sweep's last inactive frame.
                if self._pending_seen_active:
                    self._sweep_pending_since = None
                    self._pending_seen_active = False
                # `partial` only means anything mid-sweep. A sweep that
                # aborts with zero points (e.g. a dark/disconnected panel)
                # publishes only this one inactive update, with no prior
                # active=True call to trigger the reset above - without
                # this, a previous unrelated sweep's partial would linger
                # and be served as if it belonged to this (empty) one.
                self._partial = {}
            self._active = progress.active

    def snapshot(self) -> _Snapshot:
        with self._lock:
            partial = [self._partial[idx] for idx in sorted(self._partial)]
            return _Snapshot(
                points=list(self._points),
                link=self._link,
                seq=self._seq,
                partial=partial,
                active=self._active,
                command_error=self._command_error,
                demo_source=self._data_demo_source,
                source=(
                    "simulated"
                    if self._simulated
                    else "firmware-replay"
                    if self._data_demo_source
                    else "hardware"
                ),
            )


class _ConfigCache:
    """Thread-safe cache of the Pico dynamic configuration state and defaults."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, object] = {
            "vin_range": "low",
            "vout_range": "low",
            "ron_mohm": 6,
            "max31865": False,
            "i_max_ma": 1000,
            "v_max_mv": 40000,
            "psu_enabled": False,
            "psu_open_loop": False,
            "psu_vout_target_mv": 5000,
            "psu_fixed_duty": 0.5,
        }
        self._last_applied_at: str | None = None
        self._last_error: str | None = None

    def update(self, changes: dict[str, object], error: str | None = None) -> None:
        with self._lock:
            for k, v in changes.items():
                if v is not None and k in self._state:
                    self._state[k] = v
            self._last_applied_at = now_utc()
            self._last_error = error

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "config": dict(self._state),
                "defaults": {
                    "vin_range": "low",
                    "vout_range": "low",
                    "ron_mohm": 6,
                    "max31865": False,
                    "i_max_ma": 1000,
                    "v_max_mv": 40000,
                    "psu_enabled": False,
                    "psu_open_loop": False,
                    "psu_vout_target_mv": 5000,
                    "psu_fixed_duty": 0.5,
                },
                "last_applied_at": self._last_applied_at,
                "last_error": self._last_error,
            }
