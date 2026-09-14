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
release-relay routes hand their request off through a queue instead of
calling into it directly from a request-handling thread.

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
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from mpp_sdk.curves import MEASUREMENT_KINDS, CurveRecord, PanelSetup
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc
from mpp_sdk.runs import library as run_library
from mpp_sdk.runs.record import RunSample

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


def _poll_loop(
    cache: _SweepCache,
    commands: queue.Queue[str],
    bus: int,
    device: int,
    speed_hz: int,
    period_s: float,
    *,
    demo: bool = False,
) -> None:
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
        def link_for(result: object) -> str:
            return "demo"

        def fetch_sweep(src: SweepSource) -> list[tuple[float, float]] | None:
            return src.request_sweep()
    else:
        from mpp_sdk.io.spi_mcu import SpiMcuSource

        source_cm: SweepSource = SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz)

        def link_for(result: object) -> str:
            return "ok" if result is not None else "waiting for sweep"

        def fetch_sweep(src: SpiMcuSource) -> list[tuple[float, float]] | None:
            return src.request_sweep()

    with source_cm as src:
        while True:
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
                    cache.set(result, link_for(result))

            time.sleep(period_s)


class _PanelSetupIn(BaseModel):
    id: str
    tilt_deg: float


class _SaveCurveRequest(BaseModel):
    label: str = ""
    measurement: str = "other"
    panels: list[_PanelSetupIn] = []
    notes: str = ""


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


def create_app(cache: _SweepCache, commands: queue.Queue[str]) -> FastAPI:
    """Build the FastAPI app against a given cache/command queue - a
    parameter rather than a module global so tests can construct one
    against a fake cache with no hardware and no running poll thread."""
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
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

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
        kwargs={"demo": args.demo},
        daemon=True,
    )
    poll_thread.start()

    app = create_app(cache, commands)
    mode = " [DEMO MODE - simulated sweeps, no hardware]" if args.demo else ""
    print(f"Serving curve-tracer UI on http://{args.host}:{args.port}/{mode} (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
