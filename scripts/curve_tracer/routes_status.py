"""Live sweep data and static facts served to the page."""

from __future__ import annotations

from fastapi import FastAPI

from harness.common import algorithm_specs
from mpp_sdk.curves import MEASUREMENT_KINDS
from scripts.curve_tracer.cache import _SweepCache
from scripts.curve_tracer.lamp_step import _LampStepRunner
from scripts.curve_tracer.limits import (
    _DEFAULT_I_MAX,
    _DEFAULT_INITIAL_DUTY,
    _DEFAULT_RUN_DURATION_S,
    _DEFAULT_V_MAX,
    _DEFAULT_V_OUT_MAX,
    _MAX_RUN_DURATION_S,
)

_NO_LAMP = {"lamp_phase": None, "lamp_warmup_left_s": None}


def register_status_routes(
    app: FastAPI, cache: _SweepCache, lamp_steps: _LampStepRunner | None = None
) -> None:
    @app.get("/api/data")
    def get_data() -> dict:
        snap = cache.snapshot()
        return {
            "points": [{"x": v, "y": i * 1000.0} for v, i in snap.points],
            "partial": [{"x": v, "y": i * 1000.0} for v, i in snap.partial],
            "active": snap.active,
            "link": snap.link,
            "seq": snap.seq,
            "sweep_id": snap.seq,
            "command_error": snap.command_error,
            "demo_source": snap.demo_source,
            # null when the last sweep had no lamp option: see lamp_step.py
            **(lamp_steps.snapshot("sweep") if lamp_steps else _NO_LAMP),
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
            "default_v_out_max": _DEFAULT_V_OUT_MAX,
        }
