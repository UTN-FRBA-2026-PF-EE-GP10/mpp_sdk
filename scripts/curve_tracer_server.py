"""FastAPI server: serves the built curve-tracer React frontend (`frontend/`,
see its README) and a JSON API backed by `SpiMcuSource` / `mpp_sdk.curves`.

Needs the `web` extra (`uv sync --extra web`) for `fastapi`/`uvicorn`, and
`hardware` for real SPI access - both optional so the base install stays
lean (AGENTS.md). A background thread calls `request_sweep()` /
`poll_sweep_progress()` in a loop and caches the latest result; route
handlers just read the cache, so a slow SPI round-trip never blocks a page
load. `spidev` isn't documented thread-safe, so that same thread is the
only thing that ever touches `SpiMcuSource` - the start-sweep/release-relay
routes hand their request off through a queue instead of calling into it
directly from a request-handling thread.

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
from typing import TYPE_CHECKING

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

_WEB_ROOT = Path(__file__).parent / "curve_tracer_web"


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

    def set(self, points: list[tuple[float, float]] | None, link: str) -> None:
        with self._lock:
            if points is not None:
                self._points = points
                self._seq += 1
            self._link = link

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
                # if this point's index isn't past the highest one we've
                # already recorded - indices only increase within a sweep,
                # so seeing one at or below our high-water mark means the
                # previous sweep's tail got skipped and this is the next
                # sweep's own early point. Checking index == 0 alone isn't
                # enough: poll_sweep_progress() is lossy and each
                # _poll_loop iteration can easily take longer than the
                # firmware needs to capture several points, so a new
                # sweep's very first point is often missed entirely - that
                # would otherwise leave the previous sweep's leftover
                # points bleeding into this one's `partial`.
                if not self._active or not self._partial or progress.index < max(self._partial):
                    self._partial = {}
                self._partial[progress.index] = (progress.voltage, progress.current)
            self._active = progress.active

    def snapshot(
        self,
    ) -> tuple[list[tuple[float, float]], str, int, list[tuple[float, float]], bool]:
        with self._lock:
            partial = [self._partial[idx] for idx in sorted(self._partial)]
            return list(self._points), self._link, self._seq, partial, self._active


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
        # Duck-typed against SpiMcuSource (start_sweep/release_relay/
        # request_sweep/poll_sweep_progress + context manager) - imported
        # only here, and never mpp_sdk.io.spi_mcu, so demo mode needs
        # neither `spidev` nor a board.
        from scripts.curve_tracer_demo_source import DemoSweepSource

        source_cm = DemoSweepSource()

        # Demo mode reports one link state regardless of whether a result
        # is ready this iteration - "ok" vs "waiting for sweep" is a real
        # link's two states, not a meaningful distinction for a source that
        # never fails to link in the first place.
        def link_for(result: object) -> str:
            return "demo"
    else:
        from mpp_sdk.io.spi_mcu import SpiMcuSource

        source_cm = SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz)

        def link_for(result: object) -> str:
            return "ok" if result is not None else "waiting for sweep"

    with source_cm as src:
        while True:
            # At most one queued command per iteration, not a drain loop -
            # the firmware's TRACER_COMMAND signal is single-slot
            # ("latest wins"), so sending two commands back-to-back with
            # no SPI round trip in between risks the second silently
            # overwriting the first before it's consumed. This bounds
            # each command to about one `request_sweep()` cycle apart.
            if not commands.empty():
                cmd = commands.get_nowait()
                try:
                    if cmd == "start_sweep":
                        src.start_sweep()
                    elif cmd == "release_relay":
                        src.release_relay()
                except RuntimeError as exc:
                    # Same failure mode as request_sweep() below - a
                    # transient SPI fault must not kill this thread, or
                    # every future command and sweep result silently stops
                    # working with no visible error. Still falls through
                    # to the request_sweep() poll and the sleep below,
                    # rather than looping tightly on a persistent fault.
                    cache.set(None, f"error: {exc}")
            try:
                result = src.request_sweep()
            except RuntimeError as exc:
                cache.set(None, f"error: {exc}")
            else:
                cache.set(result, link_for(result))

            # Independent of the bulk-read fetch above - a failure there
            # must not stop live progress from still being reported this
            # same iteration. Never raises (see its docstring): a dropped
            # or corrupted progress poll is reported as None, not an error.
            cache.set_progress(src.poll_sweep_progress())

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
        points, link, seq, partial, active = cache.snapshot()
        return {
            "points": [{"x": v, "y": i * 1000.0} for v, i in points],
            "partial": [{"x": v, "y": i * 1000.0} for v, i in partial],
            "active": active,
            "link": link,
            "seq": seq,
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
        points, _link, _seq, _partial, _active = cache.snapshot()
        if not points:
            raise HTTPException(status_code=409, detail="no sweep captured yet")
        record = CurveRecord(
            captured_at=now_utc(),
            label=body.label,
            measurement=body.measurement,
            panels=tuple(PanelSetup(id=p.id, tilt_deg=p.tilt_deg) for p in body.panels),
            points=tuple(points),
            notes=body.notes,
        )
        path = curve_library.save(record)
        return {"path": str(path)}

    @app.post("/api/start-sweep", status_code=204)
    def post_start_sweep() -> None:
        commands.put_nowait("start_sweep")

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
        default=0.3,
        help="delay between request_sweep() calls (each already polls internally) - "
        "also bounds how long a queued Start Sweep/Release Relay command waits",
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
