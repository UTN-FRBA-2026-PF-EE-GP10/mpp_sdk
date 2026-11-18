"""The poll thread: the only thread that touches the board."""

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING

from scripts.curve_tracer.cache import _ConfigCache, _SweepCache
from scripts.curve_tracer.live_run import _LiveRunCache, _RunRequest
from scripts.curve_tracer.run_exec import _run_live

if TYPE_CHECKING:
    from mpp_sdk.io.spi_mcu import SpiMcuSource
    from mpp_sdk.io.sweep_source import SweepSource


# Consecutive failed frames before the link is reported down. At the
# default poll period this is well under a second, fast enough to notice
# a cable pulled mid-session, while still riding out the odd corrupt
# frame that a busy link produces.
_BAD_FRAMES_LINK_DOWN = 8


def _apply_pico_config(
    src: object, cache: _SweepCache, config_cache: _ConfigCache | None, payload: dict
) -> None:
    """Send one queued Pico configuration to the board. The config cache
    changes only after the board took it, so GET /api/pico-config never
    shows a value the board does not have."""
    try:
        if payload.get("reset_cutoff"):
            reset_fn = getattr(src, "reset_cutoff", None)
            if reset_fn is not None:
                reset_fn()
        cfg_fn = getattr(src, "configure", None)
        if cfg_fn is not None:
            cfg_fn(
                vin_range=payload.get("vin_range"),
                vout_range=payload.get("vout_range"),
                ron_mohm=payload.get("ron_mohm"),
                max31865=payload.get("max31865"),
                i_max_ma=payload.get("i_max_ma"),
                v_max_mv=payload.get("v_max_mv"),
                psu_enabled=payload.get("psu_enabled"),
                psu_open_loop=payload.get("psu_open_loop"),
                psu_vout_target_mv=payload.get("psu_vout_target_mv"),
                psu_fixed_duty=payload.get("psu_fixed_duty"),
                psu_confirm=bool(payload.get("psu_confirm")),
            )
    except (RuntimeError, ValueError, OSError) as exc:
        if config_cache is not None:
            config_cache.update({}, error=str(exc))
        cache.set_command_error(f"config failed: {exc}")
        return
    if config_cache is not None:
        config_cache.update(
            {k: v for k, v in payload.items() if k not in ("reset_cutoff", "psu_confirm")}
        )
    cache.set_command_error(None)


def _poll_loop(
    cache: _SweepCache,
    commands: queue.Queue[object],
    bus: int,
    device: int,
    speed_hz: int,
    period_s: float,
    *,
    demo: bool = False,
    run_requests: queue.Queue[_RunRequest] | None = None,
    run_cache: _LiveRunCache | None = None,
    config_cache: _ConfigCache | None = None,
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

    def poll_once(src) -> None:
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
            return

        # At most one queued command per iteration, not a drain loop:
        # the firmware's TRACER_COMMAND signal is single-slot ("latest
        # wins"), so two commands sent back-to-back with no SPI round
        # trip in between risk the second silently overwriting the
        # first before it is consumed. This bounds each command to
        # about one `request_sweep()` cycle apart.
        if not commands.empty():
            cmd = commands.get_nowait()
            if isinstance(cmd, tuple) and cmd[0] == "config":
                _apply_pico_config(src, cache, config_cache, cmd[1])
                cmd = None
            try:
                if cmd is None:
                    pass
                elif cmd == "start_sweep":
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

    with source_cm as src:
        while shutdown_event is None or not shutdown_event.is_set():
            try:
                poll_once(src)
            except Exception as exc:
                # This thread is the only one that may touch the board. If
                # it dies, every later sweep and run request is dropped
                # with no visible error, so any fault (spidev raises
                # OSError, not RuntimeError) is reported and polling goes on.
                cache.set(None, f"error: {exc}")
                time.sleep(period_s)
