"""Read/write `PanelModelRecord`s to `data/panels/` (or wherever
`MPP_SDK_PANEL_DIR` points), one JSON file per panel model.

A panel model is mutable master data - an operator edits Voc/Isc once,
not every session - so this follows `mpp_sdk.sessions.library`'s "atomic
overwrite in place" story (`update`), not the write-once-then-immutable
one `mpp_sdk.curves.library`/`mpp_sdk.runs.library` follow for a captured
measurement.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path

from .defaults import list_default_panels
from .record import PanelModelRecord

_log = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SLUG_MAX_LEN = 40


def default_dir() -> Path:
    """`data/panels/` under the repo root, overridable via
    `MPP_SDK_PANEL_DIR` (tests use this to avoid touching the real
    directory)."""
    override = os.environ.get("MPP_SDK_PANEL_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "panels"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:_SLUG_MAX_LEN].rstrip("-") or "panel"


def save(record: PanelModelRecord, directory: Path | None = None) -> tuple[PanelModelRecord, Path]:
    """Write `record` as a new file, `{record.id}.json`. `record.id` is
    treated as a *proposed* id: on a collision this appends `-2`, `-3`,
    ... to it, the same scheme `mpp_sdk.sessions.library.save` uses -
    the id is part of the record's own body, so the returned record
    carries the adjusted id, not just the returned path.

    Uses exclusive file creation (`open(..., "x")`), not a
    check-then-write on `Path.exists()`: two saves landing at once must
    not be able to race each other into overwriting one another's file.
    """
    directory = directory if directory is not None else default_dir()
    directory.mkdir(parents=True, exist_ok=True)

    base_id = record.id
    suffix = 0
    while True:
        panel_id = base_id if suffix == 0 else f"{base_id}-{suffix + 1}"
        candidate = record if panel_id == record.id else replace(record, id=panel_id)
        path = directory / f"{panel_id}.json"
        body = json.dumps(candidate.to_dict(), indent=2, allow_nan=False) + "\n"
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(body)
        except FileExistsError:
            suffix += 1
            continue
        return candidate, path


def create(
    name: str,
    manufacturer: str = "",
    model: str = "",
    p_max_w: float | None = None,
    voc: float | None = None,
    isc: float | None = None,
    vmp: float | None = None,
    imp: float | None = None,
    notes: str = "",
    directory: Path | None = None,
) -> PanelModelRecord:
    """Build a new panel model and persist it. The id is minted from
    `name` (a slug, like `mpp_sdk.curves.library.save`'s filenames), not
    taken from the caller - a panel model's id is an internal handle, not
    something an operator types."""
    record = PanelModelRecord(
        id=_slug(name),
        name=name,
        manufacturer=manufacturer,
        model=model,
        p_max_w=p_max_w,
        voc=voc,
        isc=isc,
        vmp=vmp,
        imp=imp,
        notes=notes,
    )
    record.validate()
    saved, _path = save(record, directory)
    return saved


def load(path: Path) -> PanelModelRecord:
    """Parse one panel model file. Raises `ValueError` naming the file
    and the offending field on a missing key, a bad type, or an unknown
    `schema` - these files are hand-editable, not just written by this
    code."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return PanelModelRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def update(record: PanelModelRecord, directory: Path | None = None) -> Path:
    """Overwrite an existing panel model's file in place, atomically (a
    temp file in the same directory, then `os.replace`) - a crash
    mid-write must never leave a half-written record behind. `record.id`
    must already name a file; a missing file means something upstream
    resolved the wrong id, so this raises rather than silently creating
    one."""
    directory = directory if directory is not None else default_dir()
    path = directory / f"{record.id}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path}: no such panel model to update")
    record.validate()
    body = json.dumps(record.to_dict(), indent=2, allow_nan=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{record.id}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return path


def delete(path: Path, directory: Path | None = None) -> bool:
    """Delete one panel model file. Idempotent and directory-scoped, same
    reasoning as `mpp_sdk.curves.library.delete`: returns `True` if a
    file was removed, `False` if it was already gone; raises `ValueError`
    if `path` resolves outside `directory` (default `default_dir()`)."""
    directory = directory if directory is not None else default_dir()
    resolved_dir = directory.resolve()
    resolved_path = path.resolve()
    if resolved_dir not in resolved_path.parents:
        raise ValueError(f"{path}: refusing to delete outside {directory}")
    try:
        resolved_path.unlink()
    except FileNotFoundError:
        return False
    return True


def load_all(directory: Path | None = None) -> list[PanelModelRecord]:
    """Load every `*.json` record in `directory` (default `default_dir()`).
    A file that fails to parse raises rather than being skipped - a
    silently-dropped panel model is worse than a loud error."""
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]


# Which shipped ids this directory has ever been seeded with. Not a
# `*.json` file on purpose: `load_all` and `GET /api/panels` glob `*.json`
# and would list it as a broken panel model.
_SEEDED_MARKER = ".seeded-defaults"
_SEEDED_SCHEMA = 1


def _read_seeded(directory: Path) -> set[str]:
    """The ids recorded in the marker, or an empty set if the marker is
    missing or unreadable. A malformed marker must never stop the server
    starting; the worst case is that an id is treated as not yet seeded,
    which `ensure_defaults_seeded` handles without overwriting anything."""
    try:
        data = json.loads((directory / _SEEDED_MARKER).read_text(encoding="utf-8"))
        ids = data["seeded"]
        if not isinstance(ids, list):
            return set()
        return {i for i in ids if isinstance(i, str)}
    except OSError, ValueError, KeyError, TypeError:
        return set()


def _write_seeded(directory: Path, seeded: set[str]) -> None:
    body = json.dumps({"schema": _SEEDED_SCHEMA, "seeded": sorted(seeded)}, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{_SEEDED_MARKER}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_name, directory / _SEEDED_MARKER)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def ensure_defaults_seeded(directory: Path | None = None) -> None:
    """Write each shipped default panel model into `directory` once, the
    first time that shipped id is seen there, and record it in a small
    marker file (`.seeded-defaults`).

    The record, not the presence of the panel's file, decides whether an
    id is seeded. That is what makes both directions work: an operator's
    edit to a shipped panel is never overwritten (an existing file is
    left alone), and a shipped panel the operator deleted stays deleted
    across restarts (`delete` does not touch the record, so the id is
    still recorded). A shipped id added by a later SDK version is not in
    the record yet, so it still arrives on upgrade.

    A directory that predates the marker starts with an empty record: any
    shipped file already on disk is only recorded, never rewritten."""
    directory = directory if directory is not None else default_dir()
    directory.mkdir(parents=True, exist_ok=True)
    seeded = _read_seeded(directory)
    before = set(seeded)
    for default in list_default_panels():
        if default.id in seeded:
            continue
        path = directory / f"{default.id}.json"
        if not path.exists():
            body = json.dumps(default.to_dict(), indent=2, allow_nan=False) + "\n"
            try:
                with path.open("x", encoding="utf-8") as f:
                    f.write(body)
            except FileExistsError:
                pass  # seeded concurrently by another process - fine, leave it
        # The marker is written after the panel files, so a crash in
        # between retries on the next start instead of recording a panel
        # that was never written.
        seeded.add(default.id)
    if seeded != before:
        try:
            _write_seeded(directory, seeded)
        except OSError as exc:
            # Not worth stopping the server for: the panels are already
            # written, and the next start simply records them again.
            _log.warning("could not record seeded panel models in %s: %s", directory, exc)
