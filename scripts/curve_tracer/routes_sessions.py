"""Routes for session templates and bench session checklists."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable
from dataclasses import replace

from fastapi import FastAPI, HTTPException, Response

from mpp_sdk.sessions import STEP_STATUSES
from mpp_sdk.sessions import library as session_library
from mpp_sdk.sessions import list_templates as list_session_templates
from mpp_sdk.sessions.record import now_utc as sessions_now_utc
from scripts.curve_tracer.library_paths import _session_path
from scripts.curve_tracer.limits import (
    _CURVE_ID_RE,
    _RUN_ID_RE,
    _SESSION_FIELD_VALUE_MAX_LEN,
    _SESSION_LINKED_ID_MAX_LEN,
    _SESSION_MAX_LINKED_IDS,
    _SESSION_NOTES_MAX_LEN,
    _SESSION_TITLE_MAX_LEN,
)
from scripts.curve_tracer.models import _CreateSessionRequest, _PatchSessionRequest


def register_session_routes(
    app: FastAPI, patch_lock: threading.Lock, get_session_template: Callable
) -> None:
    @app.get("/api/session-templates")
    def get_session_templates() -> list[dict]:
        return [
            {
                "template_id": t.template_id,
                "version": t.version,
                "title": t.title,
                "setup": t.setup,
                "n_steps": t.n_steps,
            }
            for t in list_session_templates()
        ]

    @app.get("/api/session-templates/{template_id}")
    def get_session_template_route(template_id: str) -> dict:
        try:
            template = get_session_template(template_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="template not found") from None
        return template.to_dict()

    @app.get("/api/sessions")
    def get_sessions() -> list[dict]:
        """List saved sessions, summary only, newest first - a session's
        filename is timestamp-prefixed (see mpp_sdk.sessions.library.save),
        so a reverse filename sort is a reverse chronological sort."""
        directory = session_library.default_dir()
        paths = sorted(directory.glob("*.json"), reverse=True) if directory.exists() else []
        entries = []
        for path in paths:
            # Session files, like curve and run files, are hand-editable
            # JSON - a single malformed one must not take the whole
            # listing down (see get_curves above for the same pattern).
            try:
                r = session_library.load(path)
                entries.append(
                    {
                        "id": r.id,
                        "title": r.title,
                        "template_id": r.template_id,
                        "setup": r.setup,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                        "n_steps": r.n_steps,
                        "n_done": r.n_done,
                        "n_failed": r.n_failed,
                    }
                )
            except ValueError as exc:
                entries.append({"id": path.stem, "path": str(path), "error": str(exc)})
        return entries

    def _check_field_lengths(fields: dict[str, str]) -> None:
        for key, value in fields.items():
            if len(value) > _SESSION_FIELD_VALUE_MAX_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"field {key!r} must be at most {_SESSION_FIELD_VALUE_MAX_LEN} characters"
                    ),
                )

    def _check_field_keys(fields: dict[str, str], known: set[str]) -> None:
        # The template decides which setup fields exist, so the session
        # view can show them all as one fixed table.
        unknown = sorted(set(fields) - known)
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown field {unknown[0]!r}")

    def _readonly_field_keys(template_id: str) -> set[str]:
        # Data-driven, not a regex on the key name: a template's own
        # FieldDef.readonly says which fields it snapshots (panel model
        # Voc/Isc/Vmp/Imp today), so a future snapshot field is protected
        # by declaring it there, not by a pattern match here that could
        # miss it. Falls back to "nothing is read-only" for a session
        # whose template was since removed - the field-existence check
        # above already covers that session, this one is only extra
        # protection on top for a template that still exists.
        try:
            template = get_session_template(template_id)
        except KeyError:
            return set()
        return {fd.key for fd in template.field_defs if fd.readonly}

    def _check_no_readonly_fields(fields: dict[str, str], readonly_keys: set[str]) -> None:
        # This is what actually enforces "a session snapshots a panel
        # model's values, it does not track them live" - the frontend
        # only disables the input; without this check here, any other
        # client could still PATCH a snapshotted field back to life (see
        # patch_panel's docstring for the guarantee this backs).
        locked = sorted(set(fields) & readonly_keys)
        if locked:
            raise HTTPException(status_code=400, detail=f"field {locked[0]!r} is read-only")

    def _check_linked_ids(ids: list[str], pattern: re.Pattern[str], kind: str) -> None:
        # Linked ids are stored, never opened as paths, but they must look
        # like real library ids so a session cannot grow without limit.
        for linked in ids:
            if len(linked) > _SESSION_LINKED_ID_MAX_LEN or not pattern.fullmatch(linked):
                raise HTTPException(status_code=400, detail=f"invalid {kind} id {linked!r:.80}")

    @app.post("/api/sessions")
    def post_create_session(body: _CreateSessionRequest) -> dict:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="title must not be empty")
        if len(body.title) > _SESSION_TITLE_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"title must be at most {_SESSION_TITLE_MAX_LEN} characters",
            )
        try:
            template = get_session_template(body.template_id)
        except KeyError:
            raise HTTPException(
                status_code=400, detail=f"unknown template {body.template_id!r}"
            ) from None
        fields = body.fields or {}
        _check_field_lengths(fields)
        _check_field_keys(fields, {fd.key for fd in template.field_defs})
        record = session_library.create(template, body.title, fields=fields)
        return record.to_dict()

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        path = _session_path(session_id)
        try:
            r = session_library.load(path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return r.to_dict()

    @app.patch("/api/sessions/{session_id}")
    def patch_session(session_id: str, body: _PatchSessionRequest) -> dict:
        with patch_lock:
            return _patch_session(session_id, body)

    def _patch_session(session_id: str, body: _PatchSessionRequest) -> dict:
        """Partial update: only the fields given in the body change.
        `updated_at` is always stamped here, server-side - never taken
        from the request, so a client can't backdate or freeze it.
        Written through `session_library.update`, which replaces the file
        atomically (temp file + `os.replace`)."""
        path = _session_path(session_id)
        try:
            r = session_library.load(path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        title = r.title
        if body.title is not None:
            if not body.title.strip():
                raise HTTPException(status_code=400, detail="title must not be empty")
            if len(body.title) > _SESSION_TITLE_MAX_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=f"title must be at most {_SESSION_TITLE_MAX_LEN} characters",
                )
            title = body.title

        fields = dict(r.fields)
        if body.fields is not None:
            _check_field_lengths(body.fields)
            _check_field_keys(body.fields, set(r.fields))
            _check_no_readonly_fields(body.fields, _readonly_field_keys(r.template_id))
            fields.update(body.fields)

        steps = list(r.steps)
        if body.steps is not None:
            seen_step_ids: set[str] = set()
            for step_patch in body.steps:
                if step_patch.id in seen_step_ids:
                    raise HTTPException(
                        status_code=400, detail=f"duplicate step id {step_patch.id!r} in patch"
                    )
                seen_step_ids.add(step_patch.id)
                idx = next((i for i, s in enumerate(steps) if s.id == step_patch.id), None)
                if idx is None:
                    raise HTTPException(
                        status_code=400, detail=f"unknown step id {step_patch.id!r}"
                    )
                changes: dict = {}
                if step_patch.status is not None:
                    if step_patch.status not in STEP_STATUSES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"status must be one of {STEP_STATUSES}",
                        )
                    changes["status"] = step_patch.status
                if step_patch.value is not None:
                    # NaN and infinity would be written as bare tokens that
                    # strict JSON readers (a browser, a session file) reject.
                    if isinstance(step_patch.value, float) and not math.isfinite(step_patch.value):
                        raise HTTPException(status_code=400, detail="value must be finite")
                    changes["value"] = step_patch.value
                if step_patch.notes is not None:
                    if len(step_patch.notes) > _SESSION_NOTES_MAX_LEN:
                        raise HTTPException(
                            status_code=400,
                            detail=f"notes must be at most {_SESSION_NOTES_MAX_LEN} characters",
                        )
                    changes["notes"] = step_patch.notes
                if step_patch.curve_ids is not None:
                    if len(step_patch.curve_ids) > _SESSION_MAX_LINKED_IDS:
                        raise HTTPException(
                            status_code=400,
                            detail=f"at most {_SESSION_MAX_LINKED_IDS} linked curve ids per step",
                        )
                    _check_linked_ids(step_patch.curve_ids, _CURVE_ID_RE, "curve")
                    changes["curve_ids"] = tuple(step_patch.curve_ids)
                if step_patch.run_ids is not None:
                    if len(step_patch.run_ids) > _SESSION_MAX_LINKED_IDS:
                        raise HTTPException(
                            status_code=400,
                            detail=f"at most {_SESSION_MAX_LINKED_IDS} linked run ids per step",
                        )
                    _check_linked_ids(step_patch.run_ids, _RUN_ID_RE, "run")
                    changes["run_ids"] = tuple(step_patch.run_ids)
                steps[idx] = replace(steps[idx], **changes)

        open_questions = list(r.open_questions)
        if body.open_questions is not None:
            seen_question_ids: set[str] = set()
            for q_patch in body.open_questions:
                if q_patch.id in seen_question_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"duplicate open question id {q_patch.id!r} in patch",
                    )
                seen_question_ids.add(q_patch.id)
                idx = next((i for i, q in enumerate(open_questions) if q.id == q_patch.id), None)
                if idx is None:
                    raise HTTPException(
                        status_code=400, detail=f"unknown open question id {q_patch.id!r}"
                    )
                if len(q_patch.answer) > _SESSION_NOTES_MAX_LEN:
                    raise HTTPException(
                        status_code=400,
                        detail=f"answer must be at most {_SESSION_NOTES_MAX_LEN} characters",
                    )
                open_questions[idx] = replace(open_questions[idx], answer=q_patch.answer)

        updated = replace(
            r,
            title=title,
            fields=fields,
            steps=tuple(steps),
            open_questions=tuple(open_questions),
            updated_at=sessions_now_utc(),
        )
        session_library.update(updated)
        return updated.to_dict()

    @app.delete("/api/sessions/{session_id}", status_code=204, response_class=Response)
    def delete_session(session_id: str) -> Response:
        session_library.delete(_session_path(session_id))
        return Response(status_code=204)
