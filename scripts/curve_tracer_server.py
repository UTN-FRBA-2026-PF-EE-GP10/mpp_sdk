"""FastAPI server: serves the built curve-tracer React frontend (`frontend/`,
see its README) and a JSON API backed by `SpiMcuSource` / `mpp_sdk.curves`.

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
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from mpp_sdk.curves import MEASUREMENT_KINDS, CurveRecord, PanelSetup
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc

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
        # Whether the sweep now being drawn came from the firmware's
        # stored curves rather than a real panel. Set when a demo sweep is
        # commanded, cleared when a real one is - so the page can mark a
        # replayed curve as such and nobody mistakes one for a
        # measurement.
        self._demo_source = False
        # Set once at startup by _poll_loop when running --demo, where no
        # board is involved at all. Distinct from _demo_source, which means
        # a real board replaying a curve it has stored.
        self._simulated = False

    def set(self, points: list[tuple[float, float]] | None, link: str) -> None:
        with self._lock:
            if points is not None:
                self._points = points
                self._seq += 1
            self._link = link

    def set_demo_source(self, demo: bool) -> None:
        with self._lock:
            self._demo_source = demo

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
                demo_source=self._demo_source,
                source=(
                    "simulated"
                    if self._simulated
                    else "firmware-replay"
                    if self._demo_source
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
                        "path": str(path),
                        "captured_at": r.captured_at.isoformat(),
                        "label": r.label,
                        "measurement": r.measurement,
                        "panels": [p.to_dict() for p in r.panels],
                        "n_points": len(r.points),
                        "source": r.source,
                        "voc": r.open_circuit_voltage,
                        "isc": r.short_circuit_current,
                        "p_mpp": r.mpp()[2],
                    }
                )
            except ValueError as exc:
                entries.append({"path": str(path), "error": str(exc)})
        return entries

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
