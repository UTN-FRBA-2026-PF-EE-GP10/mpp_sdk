"""Lamp dimmer routes. They call the source from the request thread, not through
the poll thread: see `scripts/curve_tracer/lamp.py` for why and for the worst case.
Lamp state is independent of runs and sweeps, so nothing here refuses a command
because a run is in progress."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from mpp_sdk.io.dimmer import lamp_power_fraction
from scripts.curve_tracer.lamp import LampError, _LampController
from scripts.curve_tracer.models import _LampRequest

# The alpha that gives exactly the cap power is found by bisection, so it can be a hair over.
_CAP_TOLERANCE = 1e-9


def register_lamp_routes(app: FastAPI, lamp: _LampController) -> None:
    @app.get("/api/dimmer")
    def get_dimmer() -> dict:
        return lamp.snapshot()

    @app.post("/api/dimmer")
    def post_dimmer(req: _LampRequest) -> dict:
        # alpha is capped through the power it gives, so --lamp-max-power binds both.
        power = req.power if req.power is not None else lamp_power_fraction(req.alpha_deg)
        if power > lamp.max_power + _CAP_TOLERANCE:
            raise HTTPException(
                422, f"lamp power {power:.3f} is above the server cap {lamp.max_power:g}"
            )
        if req.power == 0.0 or req.alpha_deg == 180.0:
            return lamp.off()
        try:
            return lamp.on(power=req.power, alpha_deg=req.alpha_deg, max_on_s=req.max_on_s)
        except LampError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

    @app.post("/api/dimmer/off")
    def post_dimmer_off() -> dict:
        return lamp.off()
