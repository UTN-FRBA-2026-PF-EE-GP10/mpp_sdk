"""Request bodies of the curve-tracer API."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, StrictFloat, StrictInt, field_validator, model_validator

from mpp_sdk.io.board import (
    CUTOFF_I_MAX_CEILING_MA,
    CUTOFF_V_MAX_CEILING_MV,
    PSU_VOUT_TARGET_CEILING_MV,
)
from mpp_sdk.io.dimmer import MAX_LAMP_WINDOW_S
from scripts.curve_tracer.limits import (
    _DEFAULT_I_MAX,
    _DEFAULT_INITIAL_DUTY,
    _DEFAULT_V_MAX,
    _DEFAULT_V_OUT_MAX,
    _LAMP_WARMUP_DEFAULT_S,
    _LAMP_WARMUP_MAX_S,
)

_DividerRange = Literal["low", "mid", "full", 0, 1, 2]


class _PicoConfigRequest(BaseModel):
    """Bounds match SpiMcuSource's setters, so a bad value is a 422 here and
    never reaches the poll thread."""

    vin_range: _DividerRange | None = None
    vout_range: _DividerRange | None = None
    ron_mohm: int | None = Field(default=None, ge=0, le=65535)
    max31865: bool | None = None
    i_max_ma: int | None = Field(default=None, ge=1, le=CUTOFF_I_MAX_CEILING_MA)
    v_max_mv: int | None = Field(default=None, ge=1, le=CUTOFF_V_MAX_CEILING_MV)
    reset_cutoff: bool = False
    psu_enabled: bool | None = None
    psu_open_loop: bool | None = None
    psu_vout_target_mv: int | None = Field(default=None, ge=0, le=PSU_VOUT_TARGET_CEILING_MV)
    psu_fixed_duty: float | None = Field(default=None, ge=0.0, le=0.95, allow_inf_nan=False)
    # PowerSupply mode drives the converter with no Pi watchdog. The page
    # sets this only after the operator confirmed the input is not the panel.
    psu_confirm: bool = False


class _PanelSetupIn(BaseModel):
    id: str
    tilt_deg: float


class _SaveCurveRequest(BaseModel):
    label: str = ""
    measurement: str = "other"
    panels: list[_PanelSetupIn] = []
    notes: str = ""
    # The client's "active session" (see frontend/src/lib/activeSession.ts),
    # sent per-request rather than held as server state - two browsers must
    # not fight over one "current session". Validated like any other id and
    # stamped onto the saved CurveRecord verbatim - see
    # _validate_active_session_id.
    session_id: str | None = None
    # Sweep number (`sweep_id` of GET /api/data) the client saw. When given
    # and no longer the sweep held by the server, the save is refused.
    sweep_id: int | None = None


class _CreatePanelRequest(BaseModel):
    """Body of `POST /api/panels`. `id` is never accepted here - it is
    minted from `name` by `mpp_sdk.panels.library.create`, the same
    "server mints the id" story `POST /api/save-curve` and
    `POST /api/sessions` already follow."""

    name: str
    manufacturer: str = ""
    model: str = ""
    p_max_w: float | None = None
    voc: float | None = None
    isc: float | None = None
    vmp: float | None = None
    imp: float | None = None
    notes: str = ""


class _PatchPanelRequest(BaseModel):
    """Body of `PATCH /api/panels/{id}`. Every field is optional - only
    what's given changes. There is no way to explicitly clear a numeric
    field back to null through this route, the same simplification
    `_PatchSessionStepRequest.value` already makes."""

    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    p_max_w: float | None = None
    voc: float | None = None
    isc: float | None = None
    vmp: float | None = None
    imp: float | None = None
    notes: str | None = None


class _CreateSessionRequest(BaseModel):
    """Body of `POST /api/sessions`. `fields` overrides the template's
    per-field defaults (e.g. the panel model) for keys given; any field
    the template defines and this omits keeps its default."""

    template_id: str
    title: str
    fields: dict[str, str] | None = None


class _PatchSessionStepRequest(BaseModel):
    """One step's partial update inside `PATCH /api/sessions/{id}`. `id`
    picks which step; every other field is left as it was when omitted
    (`None`) - there is no way to explicitly clear `value` back to null
    through this route, the same simplification `_StartRunRequest.curve_ref`
    already makes elsewhere in this file."""

    id: str
    status: str | None = None
    value: float | str | None = None
    notes: str | None = None
    curve_ids: list[str] | None = None
    run_ids: list[str] | None = None


class _PatchOpenQuestionRequest(BaseModel):
    id: str
    answer: str


class _PatchSessionRequest(BaseModel):
    """Body of `PATCH /api/sessions/{id}`. Every field is optional -
    only what's given is changed. `updated_at` is never accepted here:
    the server stamps it on every successful PATCH."""

    title: str | None = None
    fields: dict[str, str] | None = None
    steps: list[_PatchSessionStepRequest] | None = None
    open_questions: list[_PatchOpenQuestionRequest] | None = None


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
    v_out_max: float = _DEFAULT_V_OUT_MAX
    curve_ref: str | None = None
    # (volts, amps) pairs; simulated runs only, instead of `curve_ref`.
    curve_points: list[tuple[float, float]] | None = None
    # Only accepted alongside curve_points: demo mode's bundled curves are
    # not in the server's curve library, so there is no id to save as
    # curve_ref the way a real curve_ref run gets one for free. This lets
    # the caller supply that id anyway, purely as a label for the saved
    # RunRecord - the run player looks it up among its own curve list
    # (the demo fixtures, in demo mode) the same way it already does for
    # curve_ref. It must match _DEMO_LABEL_RE and must not name a real
    # library curve, and it is never resolved to a path - unlike
    # curve_ref, it never reaches _curve_path.
    reference_label: str | None = None
    label: str = ""
    simulated: bool = False
    # The client's "active session" - see _SaveCurveRequest.session_id's
    # own doc comment. Validated the same way, stamped onto the saved
    # RunRecord the same way, by post_start_run/_execute_run below.
    session_id: str | None = None
    # Minimum time between algorithm steps; None keeps one step per exchange.
    control_period_ms: StrictFloat | StrictInt | None = None
    # Lamp on only around the run: see scripts/curve_tracer/lamp_step.py.
    lamp: _LampOption | None = None


class _BatchDeleteRequest(BaseModel):
    """Body of both `POST /api/curves/delete-batch` and
    `POST /api/runs/delete-batch`."""

    ids: list[str]


def _plain_finite_number(value: object) -> object:
    # bool is an int in Python and NaN passes range checks as False, so both
    # would get through the bounds of the fields.
    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("must be a number")
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an integer too large for a float
        finite = False
    if not finite:
        raise ValueError("must be finite")
    return value


class _LampLevel(BaseModel):
    """Exactly one of `power` (fraction 0 to 1) and `alpha_deg` (0 = full on, 180 = off).
    The server's `--lamp-max-power` is checked in the routes."""

    power: float | None = Field(default=None, ge=0.0, le=1.0)
    alpha_deg: float | None = Field(default=None, ge=0.0, le=180.0)

    @field_validator("power", "alpha_deg", mode="before")
    @classmethod
    def _plain_level(cls, value: object) -> object:
        return _plain_finite_number(value)

    @model_validator(mode="after")
    def _exactly_one(self) -> _LampLevel:
        if (self.power is None) == (self.alpha_deg is None):
            raise ValueError("give exactly one of power and alpha_deg")
        return self


class _LampRequest(_LampLevel):
    """Body of `POST /api/dimmer`. Power 0 and alpha 180 mean OFF."""

    max_on_s: float = Field(default=30.0, gt=0.0, le=MAX_LAMP_WINDOW_S)

    @field_validator("max_on_s", mode="before")
    @classmethod
    def _plain_window(cls, value: object) -> object:
        return _plain_finite_number(value)


class _LampOption(_LampLevel):
    """The `lamp` option of a sweep or run request: the lamp is on only around
    the measurement, after `warmup_s` seconds of warm-up."""

    warmup_s: float = Field(default=_LAMP_WARMUP_DEFAULT_S, ge=0.0, le=_LAMP_WARMUP_MAX_S)

    @field_validator("warmup_s", mode="before")
    @classmethod
    def _plain_warmup(cls, value: object) -> object:
        return _plain_finite_number(value)


class _StartSweepRequest(BaseModel):
    """Optional body of `POST /api/start-sweep`."""

    lamp: _LampOption | None = None
