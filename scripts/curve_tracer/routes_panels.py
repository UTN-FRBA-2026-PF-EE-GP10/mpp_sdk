"""Routes for the panel model library."""

from __future__ import annotations

import math
import threading
from dataclasses import replace

from fastapi import FastAPI, HTTPException, Response

from mpp_sdk.panels import library as panel_library
from scripts.curve_tracer.library_paths import _panel_path
from scripts.curve_tracer.limits import (
    _PANEL_MANUFACTURER_MAX_LEN,
    _PANEL_MODEL_MAX_LEN,
    _PANEL_NAME_MAX_LEN,
    _PANEL_NOTES_MAX_LEN,
)
from scripts.curve_tracer.models import _CreatePanelRequest, _PatchPanelRequest


def _check_panel_fields(
    *,
    name: str | None,
    manufacturer: str | None,
    model: str | None,
    notes: str | None,
    p_max_w: float | None,
    voc: float | None,
    isc: float | None,
    vmp: float | None,
    imp: float | None,
) -> None:
    """Shared by POST and PATCH /api/panels: reject an oversized string or
    a non-finite/non-positive number before it ever reaches the library
    layer (which checks the same things again on write - belt and braces,
    same reasoning as `_curve_path`'s directory-containment check)."""
    if name is not None and len(name) > _PANEL_NAME_MAX_LEN:
        raise HTTPException(
            status_code=400, detail=f"name must be at most {_PANEL_NAME_MAX_LEN} characters"
        )
    if manufacturer is not None and len(manufacturer) > _PANEL_MANUFACTURER_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"manufacturer must be at most {_PANEL_MANUFACTURER_MAX_LEN} characters",
        )
    if model is not None and len(model) > _PANEL_MODEL_MAX_LEN:
        raise HTTPException(
            status_code=400, detail=f"model must be at most {_PANEL_MODEL_MAX_LEN} characters"
        )
    if notes is not None and len(notes) > _PANEL_NOTES_MAX_LEN:
        raise HTTPException(
            status_code=400, detail=f"notes must be at most {_PANEL_NOTES_MAX_LEN} characters"
        )
    numeric_fields = (("p_max_w", p_max_w), ("voc", voc), ("isc", isc), ("vmp", vmp), ("imp", imp))
    for field_name, value in numeric_fields:
        if value is None:
            continue
        if not math.isfinite(value) or value <= 0:
            raise HTTPException(
                status_code=400, detail=f"{field_name} must be a finite positive number"
            )


def register_panel_routes(app: FastAPI, patch_lock: threading.Lock) -> None:
    @app.get("/api/panels")
    def get_panels() -> list[dict]:
        """List saved panel models. The shipped defaults (Luxen LN-10P,
        Hissuma PSF10MONO) are seeded into the library once, at app
        startup (see `panel_library.ensure_defaults_seeded` below) - by
        the time any request reaches here they are ordinary library
        entries, editable and deletable like any other."""
        directory = panel_library.default_dir()
        paths = sorted(directory.glob("*.json")) if directory.exists() else []
        entries = []
        for path in paths:
            # Panel model files, like curve/run/session files, are
            # hand-editable JSON - a single malformed one must not take
            # the whole listing down (see get_curves for the same pattern).
            try:
                r = panel_library.load(path)
                entries.append(r.to_dict())
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    @app.post("/api/panels")
    def post_create_panel(body: _CreatePanelRequest) -> dict:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="name must not be empty")
        _check_panel_fields(
            name=body.name,
            manufacturer=body.manufacturer,
            model=body.model,
            notes=body.notes,
            p_max_w=body.p_max_w,
            voc=body.voc,
            isc=body.isc,
            vmp=body.vmp,
            imp=body.imp,
        )
        try:
            record = panel_library.create(
                name=body.name,
                manufacturer=body.manufacturer,
                model=body.model,
                p_max_w=body.p_max_w,
                voc=body.voc,
                isc=body.isc,
                vmp=body.vmp,
                imp=body.imp,
                notes=body.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record.to_dict()

    @app.get("/api/panels/{panel_id}")
    def get_panel(panel_id: str) -> dict:
        path = _panel_path(panel_id)
        try:
            r = panel_library.load(path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return r.to_dict()

    @app.patch("/api/panels/{panel_id}")
    def patch_panel(panel_id: str, body: _PatchPanelRequest) -> dict:
        with patch_lock:
            return _patch_panel(panel_id, body)

    def _patch_panel(panel_id: str, body: _PatchPanelRequest) -> dict:
        """Partial update: only the fields given in the body change.
        Written through `panel_library.update`, which replaces the file
        atomically (temp file + `os.replace`) - editing a panel model
        never rewrites a session that already snapshotted its old values
        (see mpp_sdk/panels/library.py's module docstring)."""
        path = _panel_path(panel_id)
        try:
            r = panel_library.load(path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if body.name is not None and not body.name.strip():
            raise HTTPException(status_code=400, detail="name must not be empty")
        _check_panel_fields(
            name=body.name,
            manufacturer=body.manufacturer,
            model=body.model,
            notes=body.notes,
            p_max_w=body.p_max_w,
            voc=body.voc,
            isc=body.isc,
            vmp=body.vmp,
            imp=body.imp,
        )

        changes: dict = {}
        if body.name is not None:
            changes["name"] = body.name
        if body.manufacturer is not None:
            changes["manufacturer"] = body.manufacturer
        if body.model is not None:
            changes["model"] = body.model
        if body.notes is not None:
            changes["notes"] = body.notes
        for field_name, value in (
            ("p_max_w", body.p_max_w),
            ("voc", body.voc),
            ("isc", body.isc),
            ("vmp", body.vmp),
            ("imp", body.imp),
        ):
            if value is not None:
                changes[field_name] = value

        updated = replace(r, **changes)
        try:
            panel_library.update(updated)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return updated.to_dict()

    @app.delete("/api/panels/{panel_id}", status_code=204, response_class=Response)
    def delete_panel(panel_id: str) -> Response:
        panel_library.delete(_panel_path(panel_id))
        return Response(status_code=204)
