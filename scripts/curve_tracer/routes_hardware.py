"""Routes that command the board through the poll thread: sweeps, relay and
Pico configuration."""

from __future__ import annotations

import queue

from fastapi import FastAPI, HTTPException, Response

from scripts.curve_tracer.cache import _ConfigCache, _SweepCache
from scripts.curve_tracer.live_run import _LiveRunCache
from scripts.curve_tracer.models import _PicoConfigRequest


def register_hardware_routes(
    app: FastAPI,
    cache: _SweepCache,
    commands: queue.Queue[object],
    run_cache: _LiveRunCache,
    config_cache: _ConfigCache,
) -> None:
    def _refuse_if_hardware_run_in_progress() -> None:
        """A hardware run and a sweep command cannot share the one SPI
        link (the same conflict `post_start_run` refuses in the other
        direction, below). A simulated run never touches the link, so it
        does not block a sweep."""
        snap = run_cache.snapshot(0)
        if snap["status"] == "running" and snap["source"] == "hardware":
            raise HTTPException(
                status_code=409,
                detail="a hardware run is in progress - wait for it to finish before "
                "starting a sweep",
            )

    @app.post("/api/start-sweep", status_code=204, response_class=Response)
    def post_start_sweep() -> Response:
        _refuse_if_hardware_run_in_progress()
        cache.mark_sweep_pending()
        commands.put_nowait("start_sweep")
        return Response(status_code=204)

    @app.post("/api/start-demo-sweep", status_code=204, response_class=Response)
    def post_start_demo_sweep(bright: bool = False) -> Response:
        """Replay a curve stored in the firmware over real SPI - lets the
        whole loop be worked on with no panel and no lamp. Distinct from
        the server's own --demo flag, which never touches the board."""
        _refuse_if_hardware_run_in_progress()
        cache.mark_sweep_pending()
        commands.put_nowait("demo_sweep_bright" if bright else "demo_sweep_dim")
        return Response(status_code=204)

    @app.post("/api/release-relay", status_code=204, response_class=Response)
    def post_release_relay() -> Response:
        commands.put_nowait("release_relay")
        return Response(status_code=204)

    @app.get("/api/pico-config")
    def get_pico_config() -> dict:
        return config_cache.snapshot()

    @app.post("/api/pico-config")
    def post_pico_config(req: _PicoConfigRequest) -> dict:
        _refuse_if_hardware_run_in_progress()
        if req.psu_enabled and not req.psu_confirm:
            raise HTTPException(
                400,
                "PowerSupply mode needs psu_confirm: check that the input is a bench "
                "supply, not the panel",
            )
        payload = {k: v for k, v in req.model_dump().items() if v is not None}
        if not payload:
            return {"status": "ok", "message": "No parameters provided"}
        # The cache changes in the poll thread, once the board took it.
        commands.put_nowait(("config", payload))
        return {"status": "ok", "applied": payload}

    @app.post("/api/pico-config/reset-cutoff")
    def post_pico_reset_cutoff() -> dict:
        _refuse_if_hardware_run_in_progress()
        commands.put_nowait(("config", {"reset_cutoff": True}))
        return {"status": "ok", "message": "Cutoff reset command sent"}
