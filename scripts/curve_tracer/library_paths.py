"""Resolve URL-supplied ids to library files, and the helpers every
library route shares."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from mpp_sdk.curves import library as curve_library
from mpp_sdk.panels import library as panel_library
from mpp_sdk.runs import library as run_library
from mpp_sdk.sessions import library as session_library
from scripts.curve_tracer.limits import (
    _CURVE_ID_RE,
    _PANEL_ID_RE,
    _RUN_ID_RE,
    _SESSION_ID_RE,
)


def _run_path(run_id: str) -> Path:
    """Resolve a URL-supplied run id to a file inside the run library
    directory, or raise the appropriate HTTPException. Always validates
    against the current library directory rather than trusting the id's
    shape alone - belt and braces alongside the regex above."""
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    directory = run_library.default_dir()
    path = (directory / f"{run_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid run id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return path


def _curve_path(curve_id: str) -> Path:
    """Resolve a URL-supplied curve id to a file inside the curve library
    directory, or raise the appropriate HTTPException - same validated-id,
    directory-containment pattern as `_run_path` above (never a filesystem
    path taken directly from the URL)."""
    if not _CURVE_ID_RE.fullmatch(curve_id):
        raise HTTPException(status_code=400, detail="invalid curve id")
    directory = curve_library.default_dir()
    path = (directory / f"{curve_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid curve id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="curve not found")
    return path


def _session_path(session_id: str) -> Path:
    """Resolve a URL-supplied session id to a file inside the session
    library directory, or raise the appropriate HTTPException - same
    validated-id, directory-containment pattern as `_curve_path`/
    `_run_path` above (never a filesystem path taken directly from the
    URL)."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="invalid session id")
    directory = session_library.default_dir()
    path = (directory / f"{session_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid session id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="session not found")
    return path


def _validate_active_session_id(session_id: str | None) -> None:
    """Validates a client-supplied "active session" id (POST /api/save-curve,
    POST /api/runs/start) the same way `_session_path` validates a URL id -
    same regex, same directory-containment check, same existence check -
    and raises the same HTTPException on failure. `None` (no active session
    on the client) is always fine. Never returns a path: the id is only
    ever stamped verbatim onto the saved record, never used to build one."""
    if session_id is not None:
        _session_path(session_id)


def _panel_path(panel_id: str) -> Path:
    """Resolve a URL-supplied panel model id to a file inside the panel
    library directory, or raise the appropriate HTTPException - same
    validated-id, directory-containment pattern as `_session_path`/
    `_curve_path`/`_run_path` above (never a filesystem path taken
    directly from the URL)."""
    if not _PANEL_ID_RE.fullmatch(panel_id):
        raise HTTPException(status_code=400, detail="invalid panel id")
    directory = panel_library.default_dir()
    path = (directory / f"{panel_id}.json").resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="invalid panel id")
    if not path.exists():
        raise HTTPException(status_code=404, detail="panel not found")
    return path


def _delete_batch(
    ids: list[str], path_for: Callable[[str], Path], delete: Callable[[Path], None]
) -> dict:
    """Shared by the curves and runs batch-delete routes below: resolve
    and delete each id independently, so one bad id (mistyped, already
    removed, a stale selection) does not abort the rest of the batch -
    the workbench's batch-delete button needs to say which ones failed
    and keep the rest of the request going, not fail atomically.

    `path_for` is `_curve_path` or `_run_path`, reused unchanged so a
    batch delete is held to exactly the same id-validation and
    directory-containment rules as the single-item DELETE route above -
    never a filesystem path taken directly from the request body."""
    deleted: list[str] = []
    failed: list[dict] = []
    # dict.fromkeys drops repeats in order: a repeated id would otherwise
    # report "not found" for a file this same request just removed.
    for item_id in dict.fromkeys(ids):
        try:
            path = path_for(item_id)
            delete(path)
        except HTTPException as exc:
            failed.append({"id": item_id, "error": str(exc.detail)})
        except OSError as exc:
            # A permission or disk error on one file must not end the batch
            # with a 500 that also skips every id after it.
            failed.append({"id": item_id, "error": f"could not delete: {exc.strerror or exc}"})
        else:
            deleted.append(item_id)
    return {"deleted": deleted, "failed": failed}
