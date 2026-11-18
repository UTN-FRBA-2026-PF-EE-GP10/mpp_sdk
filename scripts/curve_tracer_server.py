"""FastAPI server: serves the built curve-tracer React frontend (`frontend/`,
see its README) and a JSON API backed by `SpiMcuSource` / `mpp_sdk.curves` /
`mpp_sdk.runs`.

Needs the `web` extra (`uv sync --extra web`) for `fastapi`/`uvicorn`, and
`hardware` for real SPI access - both optional so the base install stays
lean (AGENTS.md). A background thread calls `request_sweep()` and
`poll_sweep_progress()` in a loop and caches the latest result. Route
handlers just read the cache, so a slow SPI round trip never blocks a
page load. That same thread does all the board work: the start-sweep/
release-relay/runs-start routes hand their request off through a queue
instead of calling into it directly from a request-handling thread.

The one exception is the lamp dimmer (`/api/dimmer`). A run can occupy the
poll thread for 10 minutes and OFF must act within about a second, so the
lamp routes call the lamp methods of `SpiMcuSource` from the request thread.
That is safe because every SPI exchange of the source runs under one RLock
(the dimmer keepalive thread already relies on it). The poll thread publishes
the source to the routes once it exists and withdraws it before it closes.
A lamp command waits at most for one SPI exchange (milliseconds); an ON also
confirms the link and can take about 1.5 s. See `curve_tracer/lamp.py`.

A sweep or run request may carry `"lamp": {"power": 0.3, "warmup_s": 3}` (or
`alpha_deg`): the lamp is then on only for the measurement - on, warm-up,
measure, always off at the end, on Stop, on failure and at shutdown. The total
lamp time is at most 110 s (422 above, 409 when the dimmer is tripped or its
budget is too small, 503 without a dimmer link). See `curve_tracer/lamp_step.py`.

A live closed-loop MPPT run (`POST /api/runs/start`) executes on that same
thread, via `_run_live`/`run_control_loop` (`mpp_sdk/runs/loop.py`) -
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

    # Lamp: --lamp-max-power 0.5 caps the lamp power the API accepts (fraction
    # 0 to 1, default 1.0). Idle is off, every on has a window of at most 120 s,
    # and the lamp is switched off when the server stops.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import math
import queue
import socket
import threading
import time  # noqa: F401  (tests patch time.monotonic through this module)
from pathlib import Path
from urllib.parse import urlsplit

from harness.common import algorithm_specs
from mpp_sdk.io.board import default_spi_bus
from mpp_sdk.panels import library as panel_library
from mpp_sdk.sessions.templates import get_template as get_session_template

try:
    from fastapi import FastAPI, Request
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "fastapi is required for the curve-tracer server. "
        "Install it with: uv add 'mpp-sdk[web]' (or --extra web)"
    ) from exc

# Re-exported: tests and other scripts import these names from here.
from scripts.curve_tracer.cache import _ConfigCache, _Snapshot, _SweepCache
from scripts.curve_tracer.lamp import _LampController, _LampHolder
from scripts.curve_tracer.lamp_step import _LampStepRunner
from scripts.curve_tracer.library_paths import (
    _curve_path,
    _delete_batch,
    _panel_path,
    _run_path,
    _session_path,
    _validate_active_session_id,
)
from scripts.curve_tracer.limits import (
    _CURVE_LABEL_MAX_LEN,
    _DEFAULT_I_MAX,
    _DEFAULT_RUN_DURATION_S,
    _DEFAULT_V_MAX,
    _DEFAULT_V_OUT_MAX,
    _MAX_BATCH_DELETE_IDS,
    _MAX_RUN_DURATION_S,
    _PANEL_MANUFACTURER_MAX_LEN,
    _PANEL_MODEL_MAX_LEN,
    _PANEL_NAME_MAX_LEN,
    _PANEL_NOTES_MAX_LEN,
    _RUN_LABEL_MAX_LEN,
    _SESSION_FIELD_VALUE_MAX_LEN,
    _SESSION_MAX_LINKED_IDS,
    _SESSION_NOTES_MAX_LEN,
    _SESSION_TITLE_MAX_LEN,
    _SWEEP_PENDING_TIMEOUT_S,
)
from scripts.curve_tracer.live_run import _downsample_samples, _LiveRunCache, _RunRequest
from scripts.curve_tracer.models import _StartRunRequest
from scripts.curve_tracer.poll import _apply_pico_config, _poll_loop
from scripts.curve_tracer.routes_curves import register_curve_routes
from scripts.curve_tracer.routes_hardware import register_hardware_routes
from scripts.curve_tracer.routes_lamp import register_lamp_routes
from scripts.curve_tracer.routes_panels import register_panel_routes
from scripts.curve_tracer.routes_runs import register_run_routes
from scripts.curve_tracer.routes_sessions import register_session_routes
from scripts.curve_tracer.routes_status import register_status_routes
from scripts.curve_tracer.run_exec import _make_simulated_source, _run_live, _run_simulated

__all__ = [
    "_CURVE_LABEL_MAX_LEN",
    "_DEFAULT_I_MAX",
    "_DEFAULT_RUN_DURATION_S",
    "_DEFAULT_V_MAX",
    "_DEFAULT_V_OUT_MAX",
    "_MAX_BATCH_DELETE_IDS",
    "_MAX_RUN_DURATION_S",
    "_PANEL_MANUFACTURER_MAX_LEN",
    "_PANEL_MODEL_MAX_LEN",
    "_PANEL_NAME_MAX_LEN",
    "_PANEL_NOTES_MAX_LEN",
    "_RUN_LABEL_MAX_LEN",
    "_SESSION_FIELD_VALUE_MAX_LEN",
    "_SESSION_MAX_LINKED_IDS",
    "_SESSION_NOTES_MAX_LEN",
    "_SESSION_TITLE_MAX_LEN",
    "_SWEEP_PENDING_TIMEOUT_S",
    "_ConfigCache",
    "_LiveRunCache",
    "_RunRequest",
    "_Snapshot",
    "_StartRunRequest",
    "_SweepCache",
    "_apply_pico_config",
    "_curve_path",
    "_default_allowed_hosts",
    "_delete_batch",
    "_downsample_samples",
    "_host_allowed",
    "_make_simulated_source",
    "_panel_path",
    "_poll_loop",
    "_run_live",
    "_run_path",
    "_run_simulated",
    "_session_path",
    "_validate_active_session_id",
    "create_app",
    "get_session_template",
    "main",
    "time",
]

_WEB_ROOT = Path(__file__).parent / "curve_tracer_web"


# Methods that change state. A cross-site page can send these as "simple"
# requests with no CORS preflight (a POST with no body, for example).
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _default_allowed_hosts(extra: list[str]) -> frozenset[str]:
    """Host names a browser may use to reach this server, besides any IP
    address: localhost, this machine's name with and without `.local`
    (mDNS, as on the bench Pi), and any `--allowed-host` values."""
    name = socket.gethostname().lower()
    return frozenset({"localhost", name, f"{name}.local", *(h.lower() for h in extra)})


def _host_allowed(host_header: str, allowed: frozenset[str]) -> bool:
    """True if the Host header names an IP address or an allowed name.
    A DNS-rebinding page reaches the server under the attacker's own
    domain name, so its Host header fails this check."""
    hostname = urlsplit(f"//{host_header}").hostname or ""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname in allowed
    return True


def create_app(
    cache: _SweepCache,
    commands: queue.Queue[object],
    *,
    demo: bool = False,
    config_cache: _ConfigCache | None = None,
    run_cache: _LiveRunCache | None = None,
    run_requests: queue.Queue[_RunRequest] | None = None,
    stop_event: threading.Event | None = None,
    allowed_hosts: frozenset[str] | None = None,
    lamp: _LampController | None = None,
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

    Any web page the operator opens can send requests to this server, and
    the server drives real hardware. Two checks stop that: a state-changing
    request whose `Origin` names another site gets 403, and, when
    `allowed_hosts` is given, a request whose `Host` is neither an IP
    address nor in `allowed_hosts` gets 403 (DNS rebinding). Tests leave
    `allowed_hosts` as None; `main()` always passes it.

    `lamp` serves `/api/dimmer`. Without one, the lamp is unavailable (no
    board). Its refresh thread starts and stops with the app, and the lamp is
    switched off when the app shuts down.
    """
    run_cache = run_cache if run_cache is not None else _LiveRunCache()
    run_requests = run_requests if run_requests is not None else queue.Queue()
    stop_event = stop_event if stop_event is not None else threading.Event()
    config_cache = config_cache if config_cache is not None else _ConfigCache()
    lamp = lamp if lamp is not None else _LampController()
    lamp_steps = _LampStepRunner(lamp)
    specs = {s.label.lower(): s for s in algorithm_specs()}

    # Seeded once, here, rather than per-request: this is "first use" of
    # the panel library for this server process. A file this writes is
    # never touched again by this call, so an operator's later edit to a
    # shipped panel (PATCH /api/panels/{id}) survives every future server
    # restart - see mpp_sdk/panels/library.py's ensure_defaults_seeded.
    panel_library.ensure_defaults_seeded()

    # Session and panel PATCH load a file, change it, and write it back. FastAPI
    # runs plain `def` routes on a thread pool, so two PATCHes on one record
    # (a debounced note and a status click) can interleave and one edit is
    # lost. One lock for both is enough at bench request rates.
    patch_lock = threading.Lock()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        lamp.start()
        try:
            yield
        finally:
            # SIGTERM and Ctrl-C end uvicorn through here. The poll thread's
            # source closing also sends OFF, but it may be busy in a run.
            # A lamp-assisted step ends first: its thread switches the lamp off.
            lamp_steps.shutdown()
            lamp.shutdown_off()

    app = FastAPI(title="curve-tracer", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        # A NaN or infinity in the body is echoed in the error's "input" and
        # cannot be written as JSON, so the default 422 would become a 500.
        errors = [
            {**e, "input": repr(e["input"])}
            if isinstance(e.get("input"), float) and not math.isfinite(e["input"])
            else e
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @app.middleware("http")
    async def refuse_cross_site(request: Request, call_next):
        host = request.headers.get("host", "")
        if allowed_hosts is not None and not _host_allowed(host, allowed_hosts):
            return JSONResponse(status_code=403, content={"detail": "host not allowed"})
        origin = request.headers.get("origin")
        if (
            request.method not in _SAFE_METHODS
            and origin is not None
            and urlsplit(origin).netloc.lower() != host.lower()
        ):
            return JSONResponse(status_code=403, content={"detail": "cross-site request refused"})
        return await call_next(request)

    register_status_routes(app, cache, lamp_steps)
    register_curve_routes(app, cache)
    register_panel_routes(app, patch_lock)
    # Looked up per call, not bound here: tests replace this module's name
    # after the app exists.
    register_session_routes(app, patch_lock, lambda template_id: get_session_template(template_id))
    register_run_routes(
        app, cache, commands, run_cache, run_requests, stop_event, specs, demo, lamp_steps
    )
    register_hardware_routes(app, cache, commands, run_cache, config_cache, lamp_steps)
    register_lamp_routes(app, lamp)

    if _WEB_ROOT.exists():
        # Mounted last: FastAPI/Starlette match routes in registration
        # order, so the decorated /api/* routes above always win over this
        # catch-all. `html=True` serves index.html at "/"; the frontend has
        # no client-side router, so there's no unknown-path fallback to
        # provide - anything else under here 404s normally.
        app.mount("/", StaticFiles(directory=_WEB_ROOT, html=True), name="frontend")

    return app


def _lamp_max_power(text: str) -> float:
    value = float(text)
    if not 0.0 < value <= 1.0:  # False for NaN too
        raise argparse.ArgumentTypeError("must be greater than 0 and at most 1")
    return value


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="address to listen on. 0.0.0.0 (default) lets other machines on the "
        "network open the workbench - the normal setup for the bench Pi. Use "
        "127.0.0.1 to reach it only from this machine",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="NAME",
        help="extra host name a browser may use to reach the server (repeatable). "
        "IP addresses, localhost and this machine's own name always work",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--spi-bus",
        type=int,
        default=default_spi_bus(),
        help="SPI bus (default: 1 on a BeagleBone Black, else 0)",
    )
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--spi-speed-hz", type=int, default=200_000)
    parser.add_argument(
        "--poll-period-s",
        type=float,
        default=0.05,
        help="delay between poll-loop iterations - sets how finely the live sweep is "
        "sampled, and bounds how long a queued sweep or relay command waits. "
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
    parser.add_argument(
        "--lamp-max-power",
        type=_lamp_max_power,
        default=1.0,
        help="highest lamp power the API accepts, as a fraction in (0, 1] (default 1.0)",
    )
    args = parser.parse_args()

    lamp_holder = _LampHolder()
    lamp = _LampController(lamp_holder, max_power=args.lamp_max_power)
    cache = _SweepCache()
    commands: queue.Queue[object] = queue.Queue()
    config_cache = _ConfigCache()
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
            "config_cache": config_cache,
            "stop_event": stop_event,
            "shutdown_event": shutdown_event,
            "lamp_holder": lamp_holder,
        },
        daemon=True,
    )
    poll_thread.start()

    app = create_app(
        cache,
        commands,
        demo=args.demo,
        config_cache=config_cache,
        run_cache=run_cache,
        run_requests=run_requests,
        stop_event=stop_event,
        allowed_hosts=_default_allowed_hosts(args.allowed_host),
        lamp=lamp,
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
