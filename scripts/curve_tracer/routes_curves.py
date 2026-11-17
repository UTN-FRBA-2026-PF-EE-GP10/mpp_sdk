"""Routes for the captured I-V curve library and saving the current sweep."""

from __future__ import annotations

import math

from fastapi import FastAPI, HTTPException, Response

from mpp_sdk.curves import CurveRecord, PanelSetup
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc
from scripts.curve_tracer.cache import _SweepCache
from scripts.curve_tracer.library_paths import (
    _curve_path,
    _delete_batch,
    _validate_active_session_id,
)
from scripts.curve_tracer.limits import (
    _CURVE_LABEL_MAX_LEN,
    _CURVE_NOTES_MAX_LEN,
    _CURVE_PANEL_ID_MAX_LEN,
    _CURVE_PANELS_MAX,
    _MAX_BATCH_DELETE_IDS,
)
from scripts.curve_tracer.models import _BatchDeleteRequest, _SaveCurveRequest


def register_curve_routes(app: FastAPI, cache: _SweepCache) -> None:
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
                        "id": path.stem,
                        "path": str(path),
                        "captured_at": r.captured_at.isoformat(),
                        "label": r.label,
                        "measurement": r.measurement,
                        "panels": [p.to_dict() for p in r.panels],
                        "notes": r.notes,
                        "n_points": len(r.points),
                        "source": r.source,
                        "session_id": r.session_id,
                        "voc": r.open_circuit_voltage,
                        "isc": r.short_circuit_current,
                        "p_mpp": r.mpp()[2],
                        # Amps, matching voc/isc/p_mpp above and the
                        # on-disk record (CurveRecord.to_dict) - GET
                        # /api/data is the only route that speaks
                        # milliamps, for the live-capture UI's own reasons.
                        "points": [{"v": v, "i": i} for v, i in r.points],
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    @app.delete("/api/curves/{curve_id}", status_code=204, response_class=Response)
    def delete_curve(curve_id: str) -> Response:
        curve_library.delete(_curve_path(curve_id))
        return Response(status_code=204)

    @app.post("/api/curves/delete-batch")
    def post_delete_curves_batch(body: _BatchDeleteRequest) -> dict:
        """Delete several curves in one request - the workbench's "Delete
        N selected" button, so a multi-curve cleanup isn't N separate round
        trips. Always 200, even when some ids fail (see `_delete_batch`);
        the only thing rejected outright is an oversized request body."""
        if len(body.ids) > _MAX_BATCH_DELETE_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"at most {_MAX_BATCH_DELETE_IDS} ids per request",
            )
        return _delete_batch(body.ids, _curve_path, curve_library.delete)

    @app.post("/api/save-curve")
    def post_save_curve(body: _SaveCurveRequest) -> dict:
        snap = cache.snapshot()
        if not snap.points:
            raise HTTPException(status_code=409, detail="no sweep captured yet")
        _validate_active_session_id(body.session_id)
        if len(body.label) > _CURVE_LABEL_MAX_LEN:
            raise HTTPException(
                status_code=400, detail=f"label must be at most {_CURVE_LABEL_MAX_LEN} characters"
            )
        if len(body.notes) > _CURVE_NOTES_MAX_LEN:
            raise HTTPException(
                status_code=400, detail=f"notes must be at most {_CURVE_NOTES_MAX_LEN} characters"
            )
        if len(body.panels) > _CURVE_PANELS_MAX:
            raise HTTPException(
                status_code=400, detail=f"at most {_CURVE_PANELS_MAX} panels per curve"
            )
        for p in body.panels:
            if len(p.id) > _CURVE_PANEL_ID_MAX_LEN or not math.isfinite(p.tilt_deg):
                raise HTTPException(
                    status_code=400,
                    detail="each panel needs an id of at most "
                    f"{_CURVE_PANEL_ID_MAX_LEN} characters and a finite tilt_deg",
                )
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
            session_id=body.session_id,
        )
        path = curve_library.save(record)
        return {"path": str(path), "id": path.stem}
