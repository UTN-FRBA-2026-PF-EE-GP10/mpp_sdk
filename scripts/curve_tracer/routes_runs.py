"""Routes for saved runs and starting, stopping and watching a live run."""

from __future__ import annotations

import math
import queue
import threading

from fastapi import FastAPI, HTTPException, Response

from harness.common import AlgorithmSpec
from mpp_sdk import MeasuredPanel
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc
from mpp_sdk.runs import library as run_library
from scripts.curve_tracer.cache import _SweepCache
from scripts.curve_tracer.library_paths import (
    _curve_path,
    _delete_batch,
    _run_path,
    _validate_active_session_id,
)
from scripts.curve_tracer.limits import (
    _DEFAULT_I_MAX,
    _DEFAULT_LIVE_MAX_SAMPLES,
    _DEFAULT_MAX_SAMPLES,
    _DEFAULT_RUN_DURATION_S,
    _DEFAULT_V_MAX,
    _DEFAULT_V_OUT_MAX,
    _DEMO_LABEL_RE,
    _MAX_BATCH_DELETE_IDS,
    _MAX_INLINE_CURVE_POINTS,
    _MAX_RUN_DURATION_S,
    _RUN_LABEL_MAX_LEN,
)
from scripts.curve_tracer.live_run import (
    _downsample_samples,
    _LiveRunCache,
    _run_duration_s,
    _RunRequest,
)
from scripts.curve_tracer.models import _BatchDeleteRequest, _StartRunRequest
from scripts.curve_tracer.run_exec import _builtin_reference_points, _run_simulated
from scripts.run_algorithm import MAX_CONTROL_PERIOD_MS


def register_run_routes(
    app: FastAPI,
    cache: _SweepCache,
    commands: queue.Queue[object],
    run_cache: _LiveRunCache,
    run_requests: queue.Queue[_RunRequest],
    stop_event: threading.Event,
    specs: dict[str, AlgorithmSpec],
    demo: bool,
) -> None:
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
                entries.append(
                    {
                        "id": path.stem,
                        "path": str(path),
                        "captured_at": r.captured_at.isoformat(),
                        "label": r.label,
                        "algorithm": r.algorithm,
                        "n_samples": len(r.samples),
                        "duration_s": _run_duration_s(r.samples),
                        "aborted": r.aborted,
                        "curve_ref": r.curve_ref,
                        "notes": r.notes,
                        "source": r.source,
                        "session_id": r.session_id,
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    @app.post("/api/runs/start")
    def post_start_run(body: _StartRunRequest) -> dict:
        """Start a live closed-loop run - on the real board by default, or
        against a `SimulatedSource` with `"simulated": true`. Refuses
        rather than queuing a doomed request: no board at all (`--demo`,
        and `simulated` was not set), an unknown algorithm, a `curve_ref`
        that doesn't exist, a run already in progress (only one at a
        time, of either kind - see `_LiveRunCache`), or (hardware runs
        only) a curve-tracer sweep still active on the one SPI link a run
        would need.

        `duration_s` omitted, or over `_MAX_RUN_DURATION_S`, is clamped to
        that backstop rather than rejected - a forgotten run must not be
        able to drive the converter indefinitely just because the caller
        asked for "no limit" or a very large number. Applies to a
        simulated run too, even though nothing physical is at risk there -
        one runaway loop should not be able to occupy the single run slot
        forever either.

        `v_max`/`i_max` above the board's documented limits
        (`_DEFAULT_V_MAX`/`_DEFAULT_I_MAX`) are clamped down to them, the
        same way an over-long duration is clamped: an operator may narrow
        these safety bounds, never widen them past the board's limits. A
        non-positive value is rejected outright rather than clamped - it
        isn't a limit at all.
        """
        if demo and not body.simulated:
            raise HTTPException(
                status_code=409,
                detail="no board attached in --demo mode: a live run needs real hardware "
                "(pass simulated=true to run against a simulated source instead)",
            )
        _validate_active_session_id(body.session_id)
        # A hardware run and curve-tracer sweep polling cannot share the
        # one SPI link (see the module docstring) - refuse up front rather
        # than let a run queue behind a sweep and appear to "complete"
        # while the firmware actually held the gate at 0 throughout,
        # displaced by the sweep the whole time. A simulated run never
        # touches the link, so it is unaffected. `commands` is checked
        # too, not just `cache.snapshot().active`: a queued command hasn't
        # reached the firmware yet, so the sweep it starts wouldn't show
        # up as active until the poll thread dispatches it and a progress
        # frame confirms it - a run accepted in that gap would still
        # collide with it.
        if not body.simulated and (
            not commands.empty() or cache.snapshot().active or cache.sweep_pending()
        ):
            raise HTTPException(
                status_code=409,
                detail="a curve-tracer sweep is in progress - wait for it to finish "
                "before starting a run",
            )
        # JSON's NaN/Infinity literals parse straight into these float
        # fields - reject them up front with math.isfinite, before any of
        # the checks below, since a non-finite value can silently defeat
        # them (e.g. `nan <= 0` is False, so a NaN v_max would sail past
        # the non-positive check and disable the overvoltage abort for
        # the run's whole duration).
        for field_name, value in (
            ("v_max", body.v_max),
            ("i_max", body.i_max),
            ("v_out_max", body.v_out_max),
            ("initial_duty", body.initial_duty),
            *(() if body.duration_s is None else (("duration_s", body.duration_s),)),
            *(
                ()
                if body.control_period_ms is None
                else (("control_period_ms", body.control_period_ms),)
            ),
        ):
            if not math.isfinite(value):
                raise HTTPException(status_code=400, detail=f"{field_name} must be finite")
        spec = specs.get(body.algorithm.lower())
        if spec is None:
            raise HTTPException(status_code=400, detail=f"unknown algorithm {body.algorithm!r}")
        curve_ref = body.curve_ref or None
        curve_points: tuple[tuple[float, float], ...] | None = None
        if body.reference_label is not None and body.curve_points is None:
            raise HTTPException(
                status_code=400, detail="reference_label is only accepted alongside curve_points"
            )
        if body.curve_points is not None:
            # A hardware run tracks the real panel, so an inline curve could
            # only ever be a misleading picture next to it.
            if not body.simulated:
                raise HTTPException(
                    status_code=400, detail="curve_points is only accepted for a simulated run"
                )
            if curve_ref is not None:
                raise HTTPException(
                    status_code=400, detail="pass curve_ref or curve_points, not both"
                )
            curve_points = tuple((float(v), float(i)) for v, i in body.curve_points)
            if not 2 <= len(curve_points) <= _MAX_INLINE_CURVE_POINTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"curve_points needs 2 to {_MAX_INLINE_CURVE_POINTS} points",
                )
            if not all(math.isfinite(v) and math.isfinite(i) for v, i in curve_points):
                raise HTTPException(status_code=400, detail="curve_points must be finite")
            try:
                MeasuredPanel(
                    CurveRecord(
                        captured_at=now_utc(),
                        label="inline",
                        measurement="other",
                        panels=(),
                        points=curve_points,
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            reference_points = curve_points
            if body.reference_label is not None:
                # The "demo-" prefix keeps these labels apart from library
                # ids (timestamp-first), and the collision check covers a
                # hand-named file: a run tracked against inline points must
                # never point the player at a different, real curve.
                if not _DEMO_LABEL_RE.fullmatch(body.reference_label):
                    raise HTTPException(
                        status_code=400,
                        detail="reference_label must be demo-<name> (letters, digits, - or _)",
                    )
                if (curve_library.default_dir() / f"{body.reference_label}.json").exists():
                    raise HTTPException(
                        status_code=400,
                        detail="reference_label names a real curve in the library",
                    )
                # Saved as curve_ref on the RunRecord below - a label the
                # caller's own curve list (demo mode's fixtures) can look
                # up by id, even though it names no file in this server's
                # curve library. Never passed to _curve_path.
                curve_ref = body.reference_label
        elif curve_ref is not None:
            # raises 400/404 if it doesn't check out
            reference_points = curve_library.load(_curve_path(curve_ref)).points
        elif body.simulated:
            reference_points = _builtin_reference_points()
        else:
            reference_points = ()
        # A seed outside (0, 1) is not a duty cycle. Rejected rather than
        # clamped: silently moving an operator's chosen starting point
        # would change which maximum a hill-climber converges on without
        # saying so.
        if not 0.0 < body.initial_duty < 1.0:
            raise HTTPException(
                status_code=400, detail="initial_duty must be between 0 and 1 (exclusive)"
            )

        if body.duration_s is None:
            duration_s = _DEFAULT_RUN_DURATION_S
        else:
            if body.duration_s <= 0:
                raise HTTPException(status_code=400, detail="duration_s must be positive")
            duration_s = min(body.duration_s, _MAX_RUN_DURATION_S)
        # An operator may only narrow v_max/i_max, never widen them past the
        # board's documented limits - those are the only thing that aborts a
        # continuous drive on overvoltage/overcurrent (run_algorithm.py's own
        # module docstring); the firmware has no on-target cutoff for this
        # case. Non-positive is rejected outright rather than clamped: a
        # v_max of 0 isn't a limit, it's an immediate abort mislabeled as one.
        if body.control_period_ms is not None and not (
            0 < body.control_period_ms <= MAX_CONTROL_PERIOD_MS
        ):
            raise HTTPException(
                status_code=400,
                detail=f"control_period_ms must be above 0 and at most {MAX_CONTROL_PERIOD_MS:g}",
            )
        if body.v_max <= 0:
            raise HTTPException(status_code=400, detail="v_max must be positive")
        if body.i_max <= 0:
            raise HTTPException(status_code=400, detail="i_max must be positive")
        if body.v_out_max <= 0:
            raise HTTPException(status_code=400, detail="v_out_max must be positive")
        v_max = min(body.v_max, _DEFAULT_V_MAX)
        i_max = min(body.i_max, _DEFAULT_I_MAX)
        v_out_max = min(body.v_out_max, _DEFAULT_V_OUT_MAX)
        label = body.label.strip() or spec.label
        if len(label) > _RUN_LABEL_MAX_LEN:
            raise HTTPException(
                status_code=400, detail=f"label must be at most {_RUN_LABEL_MAX_LEN} characters"
            )

        if not run_cache.try_start(
            algorithm=spec.label,
            label=label,
            curve_ref=curve_ref,
            simulated=body.simulated,
            reference_points=reference_points,
        ):
            raise HTTPException(status_code=409, detail="a run is already in progress")
        stop_event.clear()
        request = _RunRequest(
            spec=spec,
            duration_s=duration_s,
            initial_duty=body.initial_duty,
            v_max=v_max,
            i_max=i_max,
            v_out_max=v_out_max,
            curve_ref=curve_ref,
            label=label,
            curve_points=curve_points,
            session_id=body.session_id,
            control_period_ms=body.control_period_ms,
        )
        if body.simulated:
            # Never touches spidev, so it does not need to wait for the
            # poll thread that owns the real board - see the module
            # docstring. try_start above already claimed the one run slot,
            # so this can never end up running alongside a hardware run.
            threading.Thread(
                target=_run_simulated, args=(run_cache, request, stop_event), daemon=True
            ).start()
        else:
            run_requests.put_nowait(request)
        return {
            "status": "running",
            "algorithm": spec.label,
            "label": label,
            "duration_s": duration_s,
        }

    @app.post("/api/runs/stop", status_code=204, response_class=Response)
    def post_stop_run() -> Response:
        # Checked and set atomically under run_cache's own lock
        # (stop_if_running), not as two separate steps - otherwise a run
        # that finishes and a new one that claims the slot in the gap
        # between the check and the set would take a stop meant for the
        # old run instead.
        if not run_cache.stop_if_running(stop_event):
            raise HTTPException(status_code=409, detail="no run in progress")
        return Response(status_code=204)

    @app.get("/api/runs/live")
    def get_live_run(max_samples: int = _DEFAULT_LIVE_MAX_SAMPLES) -> dict:
        """Poll the run in progress (or the most recently finished one,
        until the next one starts) - `status` is `"idle"` (nothing has run
        yet), `"running"`, or `"done"`. `vout` is the converter output
        voltage from the most recent sample only (`RunSample` itself never
        carries it - see the module docstring on why); `voltage`/
        `current`/`duty` are that same latest sample's input-side reading,
        for a page that wants a live readout without decoding `samples`.

        Registered ahead of `GET /api/runs/{run_id}` below: routes match
        in registration order, and "live" would otherwise be swallowed as
        a (nonexistent) run id by that path-parameter route.
        """
        return run_cache.snapshot(max_samples)

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
            "source": r.source,
            "session_id": r.session_id,
            "settings": r.settings,
            "step_period_mean_ms": r.step_period_mean_ms,
            "step_period_max_ms": r.step_period_max_ms,
            "bad_frames": r.bad_frames,
            "settle_failures": r.settle_failures,
            "suspect_readings": r.suspect_readings,
            "n_samples": len(r.samples),
            "duration_s": _run_duration_s(r.samples),
            "downsampled": downsampled,
            "samples": [s.to_dict() for s in samples],
        }

    @app.delete("/api/runs/{run_id}", status_code=204, response_class=Response)
    def delete_run(run_id: str) -> Response:
        run_library.delete(_run_path(run_id))
        return Response(status_code=204)

    @app.post("/api/runs/delete-batch")
    def post_delete_runs_batch(body: _BatchDeleteRequest) -> dict:
        """Delete several runs in one request - same shape and reasoning
        as `post_delete_curves_batch` above."""
        if len(body.ids) > _MAX_BATCH_DELETE_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"at most {_MAX_BATCH_DELETE_IDS} ids per request",
            )
        return _delete_batch(body.ids, _run_path, run_library.delete)
