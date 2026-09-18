"""FastAPI server: serves the built curve-tracer React frontend (`frontend/`,
see its README) and a JSON API backed by `SpiMcuSource` / `mpp_sdk.curves` /
`mpp_sdk.runs`.

Needs the `web` extra (`uv sync --extra web`) for `fastapi`/`uvicorn`, and
`hardware` for real SPI access - both optional so the base install stays
lean (AGENTS.md). A background thread calls `request_sweep()` and
`poll_sweep_progress()` in a loop and caches the latest result. Route
handlers just read the cache, so a slow SPI round trip never blocks a
page load. `spidev` is not documented thread-safe, so that same thread is
the only thing that ever touches `SpiMcuSource` - the start-sweep/
release-relay/runs-start routes hand their request off through a queue
instead of calling into it directly from a request-handling thread.

A live closed-loop MPPT run (`POST /api/runs/start`) executes on that same
thread, via `_run_live`/`run_control_loop` (`scripts/run_algorithm.py`) -
for the run's whole duration, normal curve-tracer polling is displaced,
not merely delayed, since a run and a sweep cannot share the one SPI link
at once. `GET /api/data` reports this (see `_run_live`) rather than
looking silently frozen. `SpiMcuSource.vout` is exposed live via
`GET /api/runs/live`, but deliberately not added to `RunSample`/the saved
`RunRecord` - that's a schema decision left for a separate change.

A *simulated* run (`POST /api/runs/start` with `"simulated": true`) never
touches `SpiMcuSource`/spidev, so it does not need the poll thread and runs
on its own dedicated thread instead (`_run_simulated`) - it drives a
`SimulatedSource` built over the operator's chosen reference curve
(`MeasuredPanel`) or, with none chosen, `IdealSingleDiode`. `_LiveRunCache`
still only ever holds one run's state at a time regardless of thread, so a
simulated and a hardware run can never overlap. The saved `RunRecord`
carries which kind actually ran (`RunRecord.source`, see
`mpp_sdk/runs/record.py`'s `RUN_SOURCES`) - stamped here, never accepted
from the request.

API routes are under `/api/` so they never collide with the frontend's
static assets, which are mounted at `/`.

Usage::

    python scripts/curve_tracer_server.py
    # or: mpp-sdk curve-tracer-web
    # then open http://<pi-host>:8000/ in a browser

    # --demo: simulated sweeps (curve_tracer_demo_source.py), no board or
    # spidev needed - runs on any machine, only needs the `web` extra:
    mpp-sdk curve-tracer-web --demo
"""

from __future__ import annotations

import argparse
import math
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from harness.common import AlgorithmSpec, algorithm_specs
from mpp_sdk import IdealSingleDiode, MeasuredPanel, SEPICConverter, SimulatedSource, TabulatedPanel
from mpp_sdk.curves import MEASUREMENT_KINDS, CurveRecord, PanelSetup
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc
from mpp_sdk.runs import RunRecord
from mpp_sdk.runs import library as run_library
from mpp_sdk.runs.record import RunSample
from mpp_sdk.runs.record import now_utc as runs_now_utc

# run_control_loop is the one control loop and abort path shared by the
# CLI (scripts/run_algorithm.py) and this server - a live run started from
# the web UI must not reimplement it. _BAD_FRAMES_LINK_DOWN is aliased
# because that module's own constant is tuned for this server's ~50 ms
# poll period, not a live run's much tighter control loop - see
# _RUN_BAD_FRAMES_LINK_DOWN below.
from scripts.run_algorithm import _BAD_FRAMES_LINK_DOWN as _RUN_BAD_FRAMES_LINK_DOWN
from scripts.run_algorithm import run_control_loop

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "fastapi is required for the curve-tracer server. "
        "Install it with: uv add 'mpp-sdk[web]' (or --extra web)"
    ) from exc

if TYPE_CHECKING:
    from mpp_sdk.io.spi_mcu import SweepProgress
    from mpp_sdk.io.sweep_source import SweepSource

_WEB_ROOT = Path(__file__).parent / "curve_tracer_web"

# Consecutive failed frames before the link is reported down. At the
# default poll period this is well under a second, fast enough to notice
# a cable pulled mid-session, while still riding out the odd corrupt
# frame that a busy link produces.
_BAD_FRAMES_LINK_DOWN = 8


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

    def set(self, points: list[tuple[float, float]] | None, link: str) -> None:
        with self._lock:
            if points is not None:
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
            else:
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


# Hard ceiling on how long a live run can drive the converter, regardless
# of what the operator asks for - the backstop against a run nobody
# remembered to stop (a closed browser tab, a dropped connection). Also
# the duration used when the operator doesn't specify one at all.
_MAX_RUN_DURATION_S = 600.0

# What a run lasts unless the operator says otherwise. Short on purpose:
# this drives a real converter, and a run is something you watch, so the
# default is the length of a look rather than the length of the backstop.
_DEFAULT_RUN_DURATION_S = 10.0

# Duty the algorithm is seeded with. It is not a cosmetic starting point -
# the local trackers hill-climb from here, so on a multi-peak curve it
# decides which maximum they settle on. Exposed so that can be explored
# rather than fixed at whatever the first run happened to use.
_DEFAULT_INITIAL_DUTY = 0.5

# Safety bounds a run is held to unless the operator narrows them. These
# are the board's documented limits - see run_algorithm.py. Served by
# GET /api/run-config so the page shows the values actually enforced.
_DEFAULT_V_MAX = 40.0
_DEFAULT_I_MAX = 1.0

# Live /api/runs/live polling only ever needs enough points to draw a
# chart, not the full record (that's what the saved RunRecord is for) -
# smaller than _DEFAULT_MAX_SAMPLES because this endpoint is polled
# repeatedly for the run's whole duration, not fetched once.
_DEFAULT_LIVE_MAX_SAMPLES = 500

# A simulated control-loop step is essentially free, so an unpaced loop
# would blow through thousands of samples before a poll of
# GET /api/runs/live could ever observe them - nothing to watch. This
# paces it to a cadence a person can actually follow; it is not tied to
# any real hardware timing.
_SIMULATED_RUN_PERIOD_S = 0.05

# A fixed operating point for a simulated run to track - not calibrated to
# any particular board, matching harness/panel_config.py's
# make_static_source default.
_SIMULATED_LOAD_RESISTANCE = 10.0

# Bounds on inline `curve_points` for a simulated run. A captured sweep is
# a few dozen points; the cap only stops an oversized body from building
# a huge table on the server.
_MAX_INLINE_CURVE_POINTS = 2000

# Points drawn for the built-in panel's reference curve when a simulated
# run has no chosen curve - enough for a smooth line on the live chart.
_BUILTIN_REFERENCE_POINTS = 60


@dataclass(frozen=True)
class _RunRequest:
    """One accepted `POST /api/runs/start` request, handed from a
    request-handling thread to the poll thread via `run_requests` - see
    `_LiveRunCache.try_start` for why the acceptance check itself can run
    on the request thread while the run itself cannot."""

    spec: AlgorithmSpec
    duration_s: float
    v_max: float
    i_max: float
    curve_ref: str | None
    label: str
    # Defaulted so a caller that does not care about the seed does not
    # have to state one; the route always passes it explicitly.
    initial_duty: float = _DEFAULT_INITIAL_DUTY
    # (volts, amps) sent in the request body for a simulated run - demo
    # mode's bundled curves are not in the server's library, so they come
    # inline instead of by `curve_ref`.
    curve_points: tuple[tuple[float, float], ...] | None = None


class _LiveRunCache:
    """Live state of the one closed-loop run that can be in progress at a
    time - shared between the poll thread (which executes the run via
    `_run_live` and appends one sample per control step through
    `add_sample`) and request-handling threads (which start/stop it and
    poll `snapshot`). Samples accumulate here in full; `snapshot`
    downsamples on read (`_downsample_samples`, same helper the saved-run
    endpoint uses) so a run's per-step rate never has to be throttled to
    match how often a page can usefully redraw - the full series still
    reaches the saved `RunRecord` untouched.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "idle"  # idle | running | done
        self._algorithm: str | None = None
        self._label = ""
        self._curve_ref: str | None = None
        self._samples: list[RunSample] = []
        self._vout: float | None = None
        self._aborted = False
        self._abort_reason: str | None = None
        self._saved_run_id: str | None = None
        self._simulated = False
        self._reference_points: tuple[tuple[float, float], ...] = ()

    def stop_if_running(self, stop_event: threading.Event) -> bool:
        """Atomically check-and-set: `stop_event.set()` happens under the
        same lock as the running check, so a run that finishes and a new
        one that claims the slot (`try_start`) in the gap between the two
        can never make a stop land on the wrong run. Returns whether a run
        was found running."""
        with self._lock:
            if self._status != "running":
                return False
            stop_event.set()
            return True

    def try_start(
        self,
        *,
        algorithm: str,
        label: str,
        curve_ref: str | None,
        simulated: bool = False,
        reference_points: tuple[tuple[float, float], ...] = (),
    ) -> bool:
        """Claim the single run slot, resetting all live state - returns
        False, leaving everything untouched, if a run is already in
        progress. This only ever touches this cache, never a source
        (that happens later, in `_run_live`/`_run_simulated`), so it is
        safe to call directly from a request-handling thread - it is what
        lets `POST /api/runs/start` reject a second concurrent request
        immediately rather than racing two runs onto the queue, and is
        also what keeps a simulated and a hardware run from ever
        overlapping even though they execute on different threads (see
        the module docstring).
        """
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._algorithm = algorithm
            self._label = label
            self._curve_ref = curve_ref
            self._samples = []
            self._vout = None
            self._aborted = False
            self._abort_reason = None
            self._saved_run_id = None
            self._simulated = simulated
            self._reference_points = reference_points
            return True

    def add_sample(self, sample: RunSample, vout: float | None) -> None:
        with self._lock:
            self._samples.append(sample)
            self._vout = vout

    def finish(self, *, aborted: bool, reason: str | None, saved_run_id: str | None) -> None:
        with self._lock:
            self._status = "done"
            self._aborted = aborted
            self._abort_reason = reason
            self._saved_run_id = saved_run_id

    def snapshot(self, max_samples: int) -> dict:
        with self._lock:
            status = self._status
            algorithm = self._algorithm
            label = self._label
            curve_ref = self._curve_ref
            samples = list(self._samples)
            vout = self._vout
            aborted = self._aborted
            abort_reason = self._abort_reason
            saved_run_id = self._saved_run_id
            simulated = self._simulated
            reference_points = self._reference_points

        # Downsampling (and the resulting stride math) doesn't need the
        # lock - it only reads the local copy taken above.
        picked, downsampled = _downsample_samples(tuple(samples), max_samples)
        last = samples[-1] if samples else None
        return {
            "status": status,
            "algorithm": algorithm,
            "label": label,
            "curve_ref": curve_ref,
            "n_samples": len(samples),
            "downsampled": downsampled,
            "samples": [s.to_dict() for s in picked],
            "voltage": last.voltage if last else None,
            "current": last.current if last else None,
            "duty": last.duty if last else None,
            "vout": vout,
            "aborted": aborted,
            "abort_reason": abort_reason,
            "saved_run_id": saved_run_id,
            # Which kind of run is in flight (or just finished) - see
            # RUN_SOURCES in mpp_sdk/runs/record.py. Never "unknown" here:
            # a live run always knows which source it started against.
            "source": "simulated" if simulated else "hardware",
            # The static curve the run tracks, for the grey reference line.
            # Sent by the server rather than looked up by the page, so demo
            # mode's inline curves and the built-in panel draw too.
            "reference_points": [{"v": v, "i": i} for v, i in reference_points],
        }


def _execute_run(
    src,
    run_cache: _LiveRunCache,
    request: _RunRequest,
    stop_event: threading.Event,
    *,
    source: str,
    period_s: float = 0.0,
    max_consecutive_bad_frames: int = _RUN_BAD_FRAMES_LINK_DOWN,
) -> None:
    """Run `request` against `src` to completion and save the result -
    shared by `_run_live` (hardware, on the poll thread) and
    `_run_simulated` (its own thread). `source` is stamped onto the saved
    `RunRecord` (see `RUN_SOURCES` in `mpp_sdk/runs/record.py`) - the
    caller decides it, never the request body, so a run can't misreport
    what actually drove it.

    Reuses `run_control_loop` (`scripts/run_algorithm.py`) unchanged - one
    control loop and one abort path for the CLI and every caller here.
    """
    algorithm = request.spec.make(request.initial_duty)
    # Passed into run_control_loop as its own `samples` list (rather than
    # letting it build one internally) so this survives an exception
    # raised mid-run: `samples` below still holds it, even though the
    # call that raised never gets to return it normally.
    collected: list[RunSample] = []

    def on_sample(sample: RunSample) -> None:
        # Runs synchronously on the calling thread, right after the
        # write() that produced this telemetry - reading src.vout here
        # needs no extra synchronization. Absent on SimulatedSource, so
        # getattr's default keeps a simulated run's `vout` as None rather
        # than raising.
        run_cache.add_sample(sample, vout=getattr(src, "vout", None))

    def save_and_finish(samples: tuple[RunSample, ...], aborted: bool, reason: str | None) -> None:
        record = RunRecord(
            captured_at=runs_now_utc(),
            label=request.label,
            algorithm=request.spec.label,
            samples=samples,
            curve_ref=request.curve_ref,
            aborted=aborted,
            notes=reason or "",
            source=source,
        )
        try:
            path = run_library.save(record)
        except OSError as exc:
            run_cache.finish(
                aborted=aborted,
                reason=f"{reason or 'completed'}; failed to save: {exc}",
                saved_run_id=None,
            )
            return
        run_cache.finish(aborted=aborted, reason=reason, saved_run_id=path.stem)

    try:
        samples, aborted, reason = run_control_loop(
            src,
            algorithm,
            duration_s=request.duration_s,
            initial_duty=request.initial_duty,
            v_max=request.v_max,
            i_max=request.i_max,
            should_stop=stop_event.is_set,
            max_consecutive_bad_frames=max_consecutive_bad_frames,
            on_sample=on_sample,
            period_s=period_s,
            samples=collected,
        )
    except Exception as exc:
        # run_control_loop's own `finally` has already driven duty to zero
        # even here (see its docstring) - this only keeps an unexpected
        # failure (a broken algorithm.step(), a hard SPI fault) from
        # killing the thread that owns the source, which for a hardware
        # run would silently end every future sweep and run for the
        # process's life. `collected` still holds whatever was recorded
        # before the failure - worth saving rather than discarding a run
        # that may have run for most of its duration before crashing.
        reason = f"error: {exc}"
        if collected:
            save_and_finish(tuple(collected), True, reason)
        else:
            run_cache.finish(aborted=True, reason=reason, saved_run_id=None)
        return

    save_and_finish(tuple(samples), aborted, reason)


def _run_live(
    src,
    cache: _SweepCache,
    run_cache: _LiveRunCache,
    request: _RunRequest,
    stop_event: threading.Event,
) -> None:
    """Execute one live closed-loop run to completion, on the poll thread -
    the only thread that may ever touch `src` (see the module docstring).
    This blocks `_poll_loop`'s normal sweep polling for the run's whole
    duration: a live run and curve-tracer polling are mutually exclusive
    on one SPI link, so that displacement is deliberate, not an accidental
    stall - `cache.set` below makes it visible to anyone still polling
    `/api/data` rather than leaving it looking silently frozen.
    """
    cache.set(None, "paused: a live MPPT run is in progress")
    # The curve-tracer relay may still be engaged from an earlier sweep
    # (never released automatically - see SpiMcuSource.release_relay) or
    # from But1 on the bench. Left engaged, the panel stays on the
    # tracer's bleed path and the firmware holds the SEPIC gate at 0 for
    # as long as the relay is on, so a run would drive nothing while
    # looking like it completed normally. Safe to call even when the
    # relay is already released. getattr guards a fake/simulated source,
    # which has no relay to release.
    release_relay = getattr(src, "release_relay", None)
    if release_relay is not None:
        release_relay()
    _execute_run(
        src,
        run_cache,
        request,
        stop_event,
        source="hardware",
        max_consecutive_bad_frames=_RUN_BAD_FRAMES_LINK_DOWN,
    )


def _builtin_panel() -> IdealSingleDiode:
    # IdealSingleDiode's own defaults (photocurrent=8.0, 60 cells) model
    # a much bigger module than this bench - Isc/Voc land well outside
    # _DEFAULT_I_MAX/_DEFAULT_V_MAX, so a no-curve run would trip the
    # overcurrent abort on its very first sample. These two params are
    # sized to roughly match a single Hissuma PSF10MONO (Isc=0.79A,
    # Voc=17V - see harness/panel_config.py) so the fallback stays a
    # sane default instead of an immediate, confusing abort.
    return IdealSingleDiode(photocurrent=0.79, cells_in_series=36)


def _builtin_reference_points() -> tuple[tuple[float, float], ...]:
    """The built-in panel's I-V curve, sampled from 0 V to just past Voc."""
    panel = _builtin_panel()
    voltages = np.linspace(0.0, 30.0, _BUILTIN_REFERENCE_POINTS)
    currents = np.asarray(panel.current(voltages), dtype=float)
    return tuple((float(v), float(i)) for v, i in zip(voltages, currents, strict=True) if i > 0)


def _make_simulated_source(
    curve_ref: str | None, curve_points: tuple[tuple[float, float], ...] | None = None
) -> SimulatedSource:
    """Build the panel a simulated run drives against: `MeasuredPanel` over
    the operator's chosen reference curve when one is given - the run then
    hunts the MPP of a curve actually measured on this bench, and the live
    view plots it against that same curve - or `IdealSingleDiode` when
    none is, so a simulated run always works, including against an empty
    curve library. Either way the panel is wrapped in `TabulatedPanel`:
    cheap for `IdealSingleDiode`'s already-closed-form `current()`, and
    `MeasuredPanel`'s own docstring recommends it for a long-running
    simulation.
    """
    if curve_points is not None:
        panel = MeasuredPanel(
            CurveRecord(
                captured_at=now_utc(),
                label="inline",
                measurement="other",
                panels=(),
                points=curve_points,
            )
        )
    elif curve_ref is not None:
        record = curve_library.load(_curve_path(curve_ref))
        panel = MeasuredPanel(record)
    else:
        panel = _builtin_panel()
    return SimulatedSource(
        panel=TabulatedPanel(panel),
        converter=SEPICConverter(),
        load_resistance=_SIMULATED_LOAD_RESISTANCE,
    )


def _run_simulated(
    run_cache: _LiveRunCache, request: _RunRequest, stop_event: threading.Event
) -> None:
    """Execute one live closed-loop run against a `SimulatedSource`, on its
    own dedicated thread. A simulated run never touches `SpiMcuSource`/
    spidev, so unlike `_run_live` it has no reason to wait for (or
    displace) the poll thread that owns the real board - `_LiveRunCache.
    try_start` already claimed the one run slot before this thread was
    even started, so this can never run alongside a hardware run.
    """
    try:
        src = _make_simulated_source(request.curve_ref, request.curve_points)
    except Exception as exc:
        run_cache.finish(aborted=True, reason=f"error: {exc}", saved_run_id=None)
        return
    _execute_run(
        src,
        run_cache,
        request,
        stop_event,
        source="simulated",
        period_s=_SIMULATED_RUN_PERIOD_S,
    )


def _poll_loop(
    cache: _SweepCache,
    commands: queue.Queue[str],
    bus: int,
    device: int,
    speed_hz: int,
    period_s: float,
    *,
    demo: bool = False,
    run_requests: queue.Queue[_RunRequest] | None = None,
    run_cache: _LiveRunCache | None = None,
    stop_event: threading.Event | None = None,
    shutdown_event: threading.Event | None = None,
) -> None:
    """Poll the board until `shutdown_event` is set. That event is
    deliberately separate from `stop_event`, which ends one live run: a
    run's Stop button must never also end the polling this thread exists
    to do."""
    if demo:
        # Implements mpp_sdk.io.sweep_source.SweepSource. Imported only
        # here, never mpp_sdk.io.spi_mcu, so demo mode needs neither
        # `spidev` nor a board.
        from scripts.curve_tracer_demo_source import DemoSweepSource

        source_cm: SweepSource = DemoSweepSource()
        cache.set_simulated(True)

        # Demo mode reports one link state regardless of whether a result
        # is ready this iteration - "ok" vs "waiting for sweep" is a real
        # link's two states, not meaningful for a source that never fails
        # to link in the first place.
        def link_for(result: object, src: object) -> str:
            return "demo"

        def fetch_sweep(src: SweepSource) -> list[tuple[float, float]] | None:
            return src.request_sweep()
    else:
        from mpp_sdk.io.spi_mcu import SpiMcuSource

        source_cm: SweepSource = SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz)

        def link_for(result: object, src: SpiMcuSource) -> str:
            # SPI has no presence detection, so a missing board does not
            # raise - MISO just floats and every frame fails its checksum
            # while the source keeps serving last-good telemetry. Without
            # this the page would report a healthy link with nothing
            # attached. A handful of failures in a row is the signal: one
            # bad frame is ordinary line noise, a sustained run is not.
            if src.consecutive_bad_frames >= _BAD_FRAMES_LINK_DOWN:
                return "error: no valid frames from the board - is it connected and powered?"
            return "ok" if result is not None else "waiting for sweep"

        def fetch_sweep(src: SpiMcuSource) -> list[tuple[float, float]] | None:
            return src.request_sweep()

    with source_cm as src:
        while shutdown_event is None or not shutdown_event.is_set():
            # A live run displaces normal polling entirely for its whole
            # duration (see _run_live's docstring) - checked first and,
            # unlike `commands` below, not capped to one per iteration:
            # there is only ever one run in flight (POST /api/runs/start
            # refuses a second one via _LiveRunCache.try_start), so there
            # is nothing to desync by draining it eagerly. In --demo mode
            # this queue never receives anything: that route rejects a
            # start request before it ever reaches here (no board to run
            # against), so this is simply never true there.
            if run_requests is not None and not run_requests.empty():
                request = run_requests.get_nowait()
                _run_live(src, cache, run_cache, request, stop_event)
                continue

            # At most one queued command per iteration, not a drain loop:
            # the firmware's TRACER_COMMAND signal is single-slot ("latest
            # wins"), so two commands sent back-to-back with no SPI round
            # trip in between risk the second silently overwriting the
            # first before it is consumed. This bounds each command to
            # about one `request_sweep()` cycle apart.
            if not commands.empty():
                cmd = commands.get_nowait()
                try:
                    if cmd == "start_sweep":
                        src.start_sweep()
                        cache.set_demo_source(False)
                    elif cmd.startswith("demo_sweep_"):
                        src.start_demo_sweep(bright=cmd.endswith("bright"))
                        cache.set_demo_source(True)
                    elif cmd == "release_relay":
                        src.release_relay()
                except RuntimeError as exc:
                    # A transient SPI fault must not kill this thread, or
                    # every future command and sweep result silently stops
                    # working with no visible error. Still falls through
                    # to the request_sweep() poll and the sleep below,
                    # rather than looping tightly on a persistent fault.
                    cache.set_command_error(f"{cmd} failed: {exc}")
                else:
                    cache.set_command_error(None)
            # Progress first, and it decides whether the bulk fetch below
            # runs at all. Never raises (see its docstring): a dropped or
            # corrupted progress poll is reported as None, not an error.
            cache.set_progress(src.poll_sweep_progress())
            sweeping = cache.snapshot().active

            # Mid-sweep there is no result to collect, and asking costs the
            # live draw: request_sweep() holds the link for up to 20 x 50 ms
            # per call, which starved progress polling down to about four
            # samples across a six-second sweep - the page sat on a few
            # points and then jumped to the finished curve. Skipping it
            # while a sweep runs turns that into one sample per point.
            #
            # It cannot simply be made non-blocking instead: the bulk-dump
            # handshake has to complete inside a single request_sweep()
            # call, because the gap between calls exceeds the firmware's
            # frame timeout and an armed result is dropped when that fires
            # (see --poll-period-s on why the gap has to stay that large).
            if not sweeping:
                try:
                    result = fetch_sweep(src)
                except RuntimeError as exc:
                    cache.set(None, f"error: {exc}")
                else:
                    cache.set(result, link_for(result, src))

            time.sleep(period_s)


class _PanelSetupIn(BaseModel):
    id: str
    tilt_deg: float


class _SaveCurveRequest(BaseModel):
    label: str = ""
    measurement: str = "other"
    panels: list[_PanelSetupIn] = []
    notes: str = ""


class _StartRunRequest(BaseModel):
    """Body of `POST /api/runs/start`. Volts and amps throughout, like
    `GET /api/runs/{id}` and unlike `GET /api/data`'s milliamps - `v_max`/
    `i_max` default to the board's documented limits, the same defaults
    `scripts/run_algorithm.py --v-max/--i-max` use.

    `simulated` defaults to False - an omitted field must keep meaning
    what it always has (drive the real board), not silently switch to a
    simulated source. Set it True to run against `SimulatedSource`
    instead; that request is honoured even in `--demo` mode, where it is
    the only kind of run available at all (see `post_start_run`)."""

    algorithm: str
    duration_s: float | None = None
    initial_duty: float = _DEFAULT_INITIAL_DUTY
    v_max: float = _DEFAULT_V_MAX
    i_max: float = _DEFAULT_I_MAX
    curve_ref: str | None = None
    # (volts, amps) pairs; simulated runs only, instead of `curve_ref`.
    curve_points: list[tuple[float, float]] | None = None
    label: str = ""
    simulated: bool = False


# A run's URL id is its filename stem (library.save's naming scheme), never
# a filesystem path - accepting a path directly in the URL would let a
# client read or delete anything the server process can reach. The
# character set matches what `library._slug` plus the `{captured_at}`
# timestamp can ever produce; in particular it excludes "/", so a path
# segment can never smuggle in a directory component.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Same scheme, same reasoning, for curves - mpp_sdk/curves/library.py's
# save() names files identically to the run library's.
_CURVE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# The player animates the whole series in a browser on a Pi-served page.
# Unbounded, a long run (a multi-minute capture can be hundreds of
# thousands of samples) is a multi-megabyte response and tens of thousands
# of chart points redrawn per animation frame - that does not degrade
# gracefully, it freezes the tab. This is only the default; a caller that
# passes max_samples=0 still gets the full series, for export/analysis.
_DEFAULT_MAX_SAMPLES = 2000


def _run_path(run_id: str) -> Path:
    """Resolve a URL-supplied run id to a file inside the run library
    directory, or raise the appropriate HTTPException. Always validates
    against the current library directory rather than trusting the id's
    shape alone - belt and braces alongside the regex above."""
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    directory = run_library.default_dir()
    path = (directory / f"{run_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid run id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return path


def _curve_path(curve_id: str) -> Path:
    """Resolve a URL-supplied curve id to a file inside the curve library
    directory, or raise the appropriate HTTPException - same validated-id,
    directory-containment pattern as `_run_path` above (never a filesystem
    path taken directly from the URL)."""
    if not _CURVE_ID_RE.fullmatch(curve_id):
        raise HTTPException(status_code=400, detail="invalid curve id")
    directory = curve_library.default_dir()
    path = (directory / f"{curve_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid curve id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="curve not found")
    return path


def _downsample_samples(
    samples: tuple[RunSample, ...], max_samples: int
) -> tuple[list[RunSample], bool]:
    """Stride `samples` down to roughly `max_samples` points for
    GET /api/runs/{id} - see `_DEFAULT_MAX_SAMPLES` for why. `max_samples
    <= 0` means "no cap, return everything".

    Striding is deliberately the simple choice for now: picking every
    Nth sample can hide a brief excursion that falls between the kept
    points, and an MPPT trace's short overshoot is exactly the
    interesting kind of excursion to lose. A future version may want
    min/max-per-bucket downsampling instead.

    The first and last sample are always kept even though they may not
    fall on the stride - a trajectory that silently loses its own
    endpoints is misleading."""
    n = len(samples)
    if max_samples <= 0 or n <= max_samples:
        return list(samples), False
    stride = math.ceil(n / max(max_samples, 2))
    picked = list(samples[::stride])
    if picked[-1] is not samples[-1]:
        picked.append(samples[-1])
    return picked, True


def create_app(
    cache: _SweepCache,
    commands: queue.Queue[str],
    *,
    demo: bool = False,
    run_cache: _LiveRunCache | None = None,
    run_requests: queue.Queue[_RunRequest] | None = None,
    stop_event: threading.Event | None = None,
) -> FastAPI:
    """Build the FastAPI app against given cache/command objects - taken
    as parameters rather than module globals so tests can construct one
    against a fake cache with no hardware and no running poll thread.

    `demo` must reflect whether the poll thread this app's routes talk to
    was started with `--demo` (`DemoSweepSource`, which has no
    `read`/`write`) - `POST /api/runs/start` refuses to queue a run at all
    when it's True, rather than letting one fail partway on a source that
    cannot drive anything. `run_cache`/`run_requests`/`stop_event` default
    to fresh instances so existing callers (including every test that
    predates live runs) keep working unchanged; a real server passes the
    same instances given to `_poll_loop` so a request thread's start/stop
    actually reaches the run executing there.
    """
    run_cache = run_cache if run_cache is not None else _LiveRunCache()
    run_requests = run_requests if run_requests is not None else queue.Queue()
    stop_event = stop_event if stop_event is not None else threading.Event()
    specs = {s.label.lower(): s for s in algorithm_specs()}

    app = FastAPI(title="curve-tracer")

    @app.get("/api/data")
    def get_data() -> dict:
        snap = cache.snapshot()
        return {
            "points": [{"x": v, "y": i * 1000.0} for v, i in snap.points],
            "partial": [{"x": v, "y": i * 1000.0} for v, i in snap.partial],
            "active": snap.active,
            "link": snap.link,
            "seq": snap.seq,
            "command_error": snap.command_error,
            "demo_source": snap.demo_source,
        }

    @app.get("/api/measurement-kinds")
    def get_measurement_kinds() -> list[str]:
        return list(MEASUREMENT_KINDS)

    @app.get("/api/run-config")
    def get_run_config() -> dict:
        """Everything the run setup form needs before it can offer a run:
        the algorithm labels `POST /api/runs/start` accepts (matched
        case-insensitively there), and the bounds it will enforce.

        Served rather than left for the page to hardcode because all of it
        is enforced here. A duration silently clamped to a backstop the
        operator was never shown, or limits displayed as 40 V / 1 A while
        the server holds a run to something else, would be worse than not
        showing them at all - the numbers on screen have to be the numbers
        that bind."""
        return {
            "algorithms": [s.label for s in algorithm_specs()],
            "max_duration_s": _MAX_RUN_DURATION_S,
            "default_duration_s": _DEFAULT_RUN_DURATION_S,
            "default_initial_duty": _DEFAULT_INITIAL_DUTY,
            "default_v_max": _DEFAULT_V_MAX,
            "default_i_max": _DEFAULT_I_MAX,
        }

    @app.get("/api/curves")
    def get_curves() -> list[dict]:
        directory = curve_library.default_dir()
        paths = sorted(directory.glob("*.json")) if directory.exists() else []
        entries = []
        for path in paths:
            # Curve files are hand-edited by operators (see library.load's
            # docstring), so a single malformed or empty-points file must
            # not take the whole listing down - report it and move on.
            try:
                r = curve_library.load(path)
                entries.append(
                    {
                        "id": path.stem,
                        "path": str(path),
                        "captured_at": r.captured_at.isoformat(),
                        "label": r.label,
                        "measurement": r.measurement,
                        "panels": [p.to_dict() for p in r.panels],
                        "notes": r.notes,
                        "n_points": len(r.points),
                        "source": r.source,
                        "voc": r.open_circuit_voltage,
                        "isc": r.short_circuit_current,
                        "p_mpp": r.mpp()[2],
                        # Amps, matching voc/isc/p_mpp above and the
                        # on-disk record (CurveRecord.to_dict) - GET
                        # /api/data is the only route that speaks
                        # milliamps, for the live-capture UI's own reasons.
                        "points": [{"v": v, "i": i} for v, i in r.points],
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    @app.delete("/api/curves/{curve_id}", status_code=204)
    def delete_curve(curve_id: str) -> None:
        curve_library.delete(_curve_path(curve_id))

    @app.post("/api/save-curve")
    def post_save_curve(body: _SaveCurveRequest) -> dict:
        snap = cache.snapshot()
        if not snap.points:
            raise HTTPException(status_code=409, detail="no sweep captured yet")
        record = CurveRecord(
            captured_at=now_utc(),
            label=body.label,
            measurement=body.measurement,
            panels=tuple(PanelSetup(id=p.id, tilt_deg=p.tilt_deg) for p in body.panels),
            points=tuple(snap.points),
            notes=body.notes,
            # Recorded by the server, never taken from the request: the
            # page cannot be trusted to know (or to admit) that the curve
            # on screen was replayed rather than measured.
            source=snap.source,
        )
        path = curve_library.save(record)
        return {"path": str(path)}

    @app.get("/api/runs")
    def get_runs() -> list[dict]:
        """List saved runs, summary only - no samples. A run can be tens
        or hundreds of thousands of samples (scripts/run_algorithm.py
        records one per control-loop step), so a listing that embedded
        them would be far too large for a page that only needs to show
        what's available."""
        directory = run_library.default_dir()
        paths = sorted(directory.glob("*.json")) if directory.exists() else []
        entries = []
        for path in paths:
            # Run files, like curve files, are hand-editable JSON - a
            # single malformed one must not take the whole listing down
            # (see get_curves above for the same pattern).
            try:
                r = run_library.load(path)
                duration_s = r.samples[-1].t - r.samples[0].t if len(r.samples) >= 2 else 0.0
                entries.append(
                    {
                        "id": path.stem,
                        "path": str(path),
                        "captured_at": r.captured_at.isoformat(),
                        "label": r.label,
                        "algorithm": r.algorithm,
                        "n_samples": len(r.samples),
                        "duration_s": duration_s,
                        "aborted": r.aborted,
                        "curve_ref": r.curve_ref,
                        "notes": r.notes,
                        "source": r.source,
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    @app.post("/api/runs/start")
    def post_start_run(body: _StartRunRequest) -> dict:
        """Start a live closed-loop run - on the real board by default, or
        against a `SimulatedSource` with `"simulated": true`. Refuses
        rather than queuing a doomed request: no board at all (`--demo`,
        and `simulated` was not set), an unknown algorithm, a `curve_ref`
        that doesn't exist, a run already in progress (only one at a
        time, of either kind - see `_LiveRunCache`), or (hardware runs
        only) a curve-tracer sweep still active on the one SPI link a run
        would need.

        `duration_s` omitted, or over `_MAX_RUN_DURATION_S`, is clamped to
        that backstop rather than rejected - a forgotten run must not be
        able to drive the converter indefinitely just because the caller
        asked for "no limit" or a very large number. Applies to a
        simulated run too, even though nothing physical is at risk there -
        one runaway loop should not be able to occupy the single run slot
        forever either.

        `v_max`/`i_max` above the board's documented limits
        (`_DEFAULT_V_MAX`/`_DEFAULT_I_MAX`) are clamped down to them, the
        same way an over-long duration is clamped: an operator may narrow
        these safety bounds, never widen them past the board's limits. A
        non-positive value is rejected outright rather than clamped - it
        isn't a limit at all.
        """
        if demo and not body.simulated:
            raise HTTPException(
                status_code=409,
                detail="no board attached in --demo mode: a live run needs real hardware "
                "(pass simulated=true to run against a simulated source instead)",
            )
        # A hardware run and curve-tracer sweep polling cannot share the
        # one SPI link (see the module docstring) - refuse up front rather
        # than let a run queue behind a sweep and appear to "complete"
        # while the firmware actually held the gate at 0 throughout,
        # displaced by the sweep the whole time. A simulated run never
        # touches the link, so it is unaffected.
        if not body.simulated and cache.snapshot().active:
            raise HTTPException(
                status_code=409,
                detail="a curve-tracer sweep is in progress - wait for it to finish "
                "before starting a run",
            )
        # JSON's NaN/Infinity literals parse straight into these float
        # fields - reject them up front with math.isfinite, before any of
        # the checks below, since a non-finite value can silently defeat
        # them (e.g. `nan <= 0` is False, so a NaN v_max would sail past
        # the non-positive check and disable the overvoltage abort for
        # the run's whole duration).
        for field_name, value in (
            ("v_max", body.v_max),
            ("i_max", body.i_max),
            ("initial_duty", body.initial_duty),
            *(() if body.duration_s is None else (("duration_s", body.duration_s),)),
        ):
            if not math.isfinite(value):
                raise HTTPException(status_code=400, detail=f"{field_name} must be finite")
        spec = specs.get(body.algorithm.lower())
        if spec is None:
            raise HTTPException(status_code=400, detail=f"unknown algorithm {body.algorithm!r}")
        curve_ref = body.curve_ref or None
        curve_points: tuple[tuple[float, float], ...] | None = None
        if body.curve_points is not None:
            # A hardware run tracks the real panel, so an inline curve could
            # only ever be a misleading picture next to it.
            if not body.simulated:
                raise HTTPException(
                    status_code=400, detail="curve_points is only accepted for a simulated run"
                )
            if curve_ref is not None:
                raise HTTPException(
                    status_code=400, detail="pass curve_ref or curve_points, not both"
                )
            curve_points = tuple((float(v), float(i)) for v, i in body.curve_points)
            if not 2 <= len(curve_points) <= _MAX_INLINE_CURVE_POINTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"curve_points needs 2 to {_MAX_INLINE_CURVE_POINTS} points",
                )
            if not all(math.isfinite(v) and math.isfinite(i) for v, i in curve_points):
                raise HTTPException(status_code=400, detail="curve_points must be finite")
            try:
                MeasuredPanel(
                    CurveRecord(
                        captured_at=now_utc(),
                        label="inline",
                        measurement="other",
                        panels=(),
                        points=curve_points,
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            reference_points = curve_points
        elif curve_ref is not None:
            # raises 400/404 if it doesn't check out
            reference_points = curve_library.load(_curve_path(curve_ref)).points
        elif body.simulated:
            reference_points = _builtin_reference_points()
        else:
            reference_points = ()
        # A seed outside (0, 1) is not a duty cycle. Rejected rather than
        # clamped: silently moving an operator's chosen starting point
        # would change which maximum a hill-climber converges on without
        # saying so.
        if not 0.0 < body.initial_duty < 1.0:
            raise HTTPException(
                status_code=400, detail="initial_duty must be between 0 and 1 (exclusive)"
            )

        if body.duration_s is None:
            duration_s = _DEFAULT_RUN_DURATION_S
        else:
            if body.duration_s <= 0:
                raise HTTPException(status_code=400, detail="duration_s must be positive")
            duration_s = min(body.duration_s, _MAX_RUN_DURATION_S)
        # An operator may only narrow v_max/i_max, never widen them past the
        # board's documented limits - those are the only thing that aborts a
        # continuous drive on overvoltage/overcurrent (run_algorithm.py's own
        # module docstring); the firmware has no on-target cutoff for this
        # case. Non-positive is rejected outright rather than clamped: a
        # v_max of 0 isn't a limit, it's an immediate abort mislabeled as one.
        if body.v_max <= 0:
            raise HTTPException(status_code=400, detail="v_max must be positive")
        if body.i_max <= 0:
            raise HTTPException(status_code=400, detail="i_max must be positive")
        v_max = min(body.v_max, _DEFAULT_V_MAX)
        i_max = min(body.i_max, _DEFAULT_I_MAX)
        label = body.label.strip() or spec.label

        if not run_cache.try_start(
            algorithm=spec.label,
            label=label,
            curve_ref=curve_ref,
            simulated=body.simulated,
            reference_points=reference_points,
        ):
            raise HTTPException(status_code=409, detail="a run is already in progress")
        stop_event.clear()
        request = _RunRequest(
            spec=spec,
            duration_s=duration_s,
            initial_duty=body.initial_duty,
            v_max=v_max,
            i_max=i_max,
            curve_ref=curve_ref,
            label=label,
            curve_points=curve_points,
        )
        if body.simulated:
            # Never touches spidev, so it does not need to wait for the
            # poll thread that owns the real board - see the module
            # docstring. try_start above already claimed the one run slot,
            # so this can never end up running alongside a hardware run.
            threading.Thread(
                target=_run_simulated, args=(run_cache, request, stop_event), daemon=True
            ).start()
        else:
            run_requests.put_nowait(request)
        return {
            "status": "running",
            "algorithm": spec.label,
            "label": label,
            "duration_s": duration_s,
        }

    @app.post("/api/runs/stop", status_code=204)
    def post_stop_run() -> None:
        # Checked and set atomically under run_cache's own lock
        # (stop_if_running), not as two separate steps - otherwise a run
        # that finishes and a new one that claims the slot in the gap
        # between the check and the set would take a stop meant for the
        # old run instead.
        if not run_cache.stop_if_running(stop_event):
            raise HTTPException(status_code=409, detail="no run in progress")

    @app.get("/api/runs/live")
    def get_live_run(max_samples: int = _DEFAULT_LIVE_MAX_SAMPLES) -> dict:
        """Poll the run in progress (or the most recently finished one,
        until the next one starts) - `status` is `"idle"` (nothing has run
        yet), `"running"`, or `"done"`. `vout` is the converter output
        voltage from the most recent sample only (`RunSample` itself never
        carries it - see the module docstring on why); `voltage`/
        `current`/`duty` are that same latest sample's input-side reading,
        for a page that wants a live readout without decoding `samples`.

        Registered ahead of `GET /api/runs/{run_id}` below: routes match
        in registration order, and "live" would otherwise be swallowed as
        a (nonexistent) run id by that path-parameter route.
        """
        return run_cache.snapshot(max_samples)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, max_samples: int = _DEFAULT_MAX_SAMPLES) -> dict:
        """One run including its samples, in volts and amps (same
        convention as GET /api/curves, unlike GET /api/data's milliamps).

        `max_samples` bounds how many samples come back (default
        `_DEFAULT_MAX_SAMPLES`; 0 or negative means "no cap, send
        everything" - export/analysis need the full series). Over the
        cap, samples are strided down; `n_samples` is always the true
        on-disk count and `downsampled` says whether striding happened,
        so a client can tell it isn't seeing the whole trace."""
        path = _run_path(run_id)
        try:
            r = run_library.load(path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        samples, downsampled = _downsample_samples(r.samples, max_samples)
        return {
            "id": run_id,
            "path": str(path),
            "captured_at": r.captured_at.isoformat(),
            "label": r.label,
            "algorithm": r.algorithm,
            "curve_ref": r.curve_ref,
            "aborted": r.aborted,
            "notes": r.notes,
            "source": r.source,
            "n_samples": len(r.samples),
            "downsampled": downsampled,
            "samples": [s.to_dict() for s in samples],
        }

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str) -> None:
        run_library.delete(_run_path(run_id))

    @app.post("/api/start-sweep", status_code=204)
    def post_start_sweep() -> None:
        commands.put_nowait("start_sweep")

    @app.post("/api/start-demo-sweep", status_code=204)
    def post_start_demo_sweep(bright: bool = False) -> None:
        """Replay a curve stored in the firmware over real SPI - lets the
        whole loop be worked on with no panel and no lamp. Distinct from
        the server's own --demo flag, which never touches the board."""
        commands.put_nowait("demo_sweep_bright" if bright else "demo_sweep_dim")

    @app.post("/api/release-relay", status_code=204)
    def post_release_relay() -> None:
        commands.put_nowait("release_relay")

    if _WEB_ROOT.exists():
        # Mounted last: FastAPI/Starlette match routes in registration
        # order, so the decorated /api/* routes above always win over this
        # catch-all. `html=True` serves index.html at "/"; the frontend has
        # no client-side router, so there's no unknown-path fallback to
        # provide - anything else under here 404s normally.
        app.mount("/", StaticFiles(directory=_WEB_ROOT, html=True), name="frontend")

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--spi-speed-hz", type=int, default=200_000)
    parser.add_argument(
        "--poll-period-s",
        type=float,
        default=0.05,
        help="delay between poll-loop iterations - sets how finely the live sweep is "
        "sampled, and bounds how long a queued Start Sweep/Release Relay command waits. "
        "Keep it BELOW the firmware's 100 ms frame timeout. A gap longer than that "
        "times the Pico's exchange out, and the recovery it runs (aborting the TX DMA, "
        "then resyncing the PIO state machine) leaves the slave unable to serve the "
        "next real frame cleanly - it drives a byte or two and goes quiet. Measured on "
        "the bench at 200 kHz: a 0.5-2 s cadence corrupted roughly half of all frames, "
        "a 0.05 s cadence was clean over 37 consecutive frames",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="use a simulated sweep source instead of SpiMcuSource - no board, no spidev, "
        "runs on any machine. For trying out the frontend away from the bench.",
    )
    args = parser.parse_args()

    cache = _SweepCache()
    commands: queue.Queue[str] = queue.Queue()
    run_cache = _LiveRunCache()
    run_requests: queue.Queue[_RunRequest] = queue.Queue()
    stop_event = threading.Event()
    shutdown_event = threading.Event()
    poll_thread = threading.Thread(
        target=_poll_loop,
        args=(
            cache,
            commands,
            args.spi_bus,
            args.spi_device,
            args.spi_speed_hz,
            args.poll_period_s,
        ),
        kwargs={
            "demo": args.demo,
            "run_requests": run_requests,
            "run_cache": run_cache,
            "stop_event": stop_event,
            "shutdown_event": shutdown_event,
        },
        daemon=True,
    )
    poll_thread.start()

    app = create_app(
        cache,
        commands,
        demo=args.demo,
        run_cache=run_cache,
        run_requests=run_requests,
        stop_event=stop_event,
    )
    mode = " [DEMO MODE - simulated sweeps, no hardware]" if args.demo else ""
    print(f"Serving curve-tracer UI on http://{args.host}:{args.port}/{mode} (Ctrl+C to stop)")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        # uvicorn.run returns once SIGINT/SIGTERM stops it, but poll_thread
        # is a daemon and would otherwise just be abandoned mid-run - its
        # run_control_loop `finally` (the one thing that zeroes duty) would
        # never get to run, and the firmware only zeroes it on its own
        # after ~500 ms of SPI silence. Setting stop_event and giving the
        # thread a short window to notice lets a live run exit through its
        # own zero-duty path before the process actually exits.
        # Order matters: stop_event first, so a run in flight ends
        # through run_control_loop's own zero-duty path rather than being
        # abandoned at whatever duty it was driving; shutdown_event then
        # ends the polling itself. Without this the daemon thread is just
        # dropped wherever it stands, and the firmware only zeroes duty on
        # its own after about 500 ms of SPI silence.
        stop_event.set()
        shutdown_event.set()
        poll_thread.join(timeout=3.0)


if __name__ == "__main__":
    main()
