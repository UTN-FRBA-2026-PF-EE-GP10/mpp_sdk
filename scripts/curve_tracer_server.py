"""Minimal HTTP server: serves the curve-tracer web UI and a `/data` JSON
endpoint backed by `SpiMcuSource.request_sweep()`.

Standard-library only (`http.server`) - this is meant to run on the same
Raspberry Pi that already talks to the RP2040 over SPI, so no extra
dependency is worth adding just to view an I-V curve in a browser. The
static page under `curve_tracer_web/` is adapted from
https://github.com/fborello-lambda/solar_panel_curve_tracer's `spiffs/`
(MIT licensed) - same dark-theme Chart.js UI, trimmed to what this board
supports (no settable current dial).

A background thread calls `request_sweep()` in a loop (it already polls
the firmware's ack internally) and caches the latest result; HTTP
handlers just read the cache, so a slow SPI round-trip never blocks a
page load. `spidev` isn't documented thread-safe, so that same thread is
the only thing that ever touches `SpiMcuSource` - the Start Sweep/Release
Relay POST endpoints hand their request off through a queue instead of
calling into it directly from a handler thread.

Usage::

    python scripts/curve_tracer_server.py
    # or: mpp-sdk curve-tracer-web
    # then open http://<pi-host>:8000/ in a browser
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mpp_sdk.curves import MEASUREMENT_KINDS, CurveRecord, PanelSetup
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc

_WEB_ROOT = Path(__file__).parent / "curve_tracer_web"
_STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/script.js": "script.js",
    "/chart.umd.min.js": "chart.umd.min.js",
}
_POST_COMMANDS = {
    "/start-sweep": "start_sweep",
    "/release-relay": "release_relay",
}
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


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

    def set(self, points: list[tuple[float, float]] | None, link: str) -> None:
        with self._lock:
            if points is not None:
                self._points = points
                self._seq += 1
            self._link = link

    def snapshot(self) -> tuple[list[tuple[float, float]], str, int]:
        with self._lock:
            return list(self._points), self._link, self._seq


def _poll_loop(
    cache: _SweepCache,
    commands: queue.Queue[str],
    bus: int,
    device: int,
    speed_hz: int,
    period_s: float,
) -> None:
    from mpp_sdk.io.spi_mcu import SpiMcuSource

    with SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz) as src:
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
                cache.set(result, "ok" if result is not None else "waiting for sweep")
            time.sleep(period_s)


def _make_handler(cache: _SweepCache, commands: queue.Queue[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A002
            pass  # keep stdout to the poll loop's own status, not per-request access logs

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/data":
                self._serve_data()
                return
            if self.path == "/curves":
                self._serve_curve_list()
                return
            if self.path == "/measurement-kinds":
                self._serve_json(list(MEASUREMENT_KINDS))
                return
            filename = _STATIC_FILES.get(self.path)
            if filename is None:
                self.send_error(404)
                return
            self._serve_static(filename)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/save-curve":
                self._save_curve()
                return
            cmd = _POST_COMMANDS.get(self.path)
            if cmd is None:
                self.send_error(404)
                return
            commands.put_nowait(cmd)
            self.send_response(204)
            self.end_headers()

        def _serve_data(self) -> None:
            points, link, seq = cache.snapshot()
            self._serve_json(
                {
                    "points": [{"x": v, "y": i * 1000.0} for v, i in points],
                    "link": link,
                    "seq": seq,
                }
            )

        def _serve_static(self, filename: str) -> None:
            path = _WEB_ROOT / filename
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES[path.suffix])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_curve_list(self) -> None:
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
                            "n_points": len(r.points),
                            "voc": r.open_circuit_voltage,
                            "isc": r.short_circuit_current,
                            "p_mpp": r.mpp()[2],
                        }
                    )
                except ValueError as exc:
                    entries.append({"path": str(path), "error": str(exc)})
            self._serve_json(entries)

        def _save_curve(self) -> None:
            points, _link, _seq = cache.snapshot()
            if not points:
                self._serve_json({"error": "no sweep captured yet"}, status=409)
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
                record = CurveRecord(
                    captured_at=now_utc(),
                    label=body.get("label", ""),
                    measurement=body.get("measurement", "other"),
                    panels=tuple(PanelSetup.from_dict(p) for p in body.get("panels", [])),
                    points=tuple(points),
                    notes=body.get("notes", ""),
                )
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
                # Server binds 0.0.0.0 by default, so a malformed request
                # (bad JSON, or a panel missing "id"/"tilt_deg") must get a
                # clean error back, not an unhandled traceback that aborts
                # the connection.
                self._serve_json({"error": f"bad request body: {exc}"}, status=400)
                return
            path = curve_library.save(record)
            self._serve_json({"path": str(path)})

    return Handler


def main() -> None:
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
        daemon=True,
    )
    poll_thread.start()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(cache, commands))
    print(f"Serving curve-tracer UI on http://{args.host}:{args.port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
