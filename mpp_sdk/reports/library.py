"""Read/write `ReportRecord`s to `data/reports/` (or wherever
`MPP_SDK_REPORT_DIR` points), one JSON file per report.

Unlike `mpp_sdk.curves.library`/`mpp_sdk.runs.library`, a report is
mutable - it is filled in step by step over a session, not captured once
and left alone - so this module adds `update`, which overwrites a
report's file in place, atomically.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .record import OpenQuestion, ReportRecord, ReportStep, now_utc
from .templates import ReportTemplate

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SLUG_MAX_LEN = 40


def default_dir() -> Path:
    """`data/reports/` under the repo root, overridable via
    `MPP_SDK_REPORT_DIR` (tests use this to avoid touching the real
    directory)."""
    override = os.environ.get("MPP_SDK_REPORT_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "reports"


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:_SLUG_MAX_LEN].rstrip("-") or "report"


def save(record: ReportRecord, directory: Path | None = None) -> tuple[ReportRecord, Path]:
    """Write `record` as a new file, `{record.id}.json`. `record.id` is
    treated as a *proposed* id: on a collision (two reports created in
    the same second from the same title) this appends `-2`, `-3`, ... to
    it - same idea as `mpp_sdk.curves.library.save`'s filename suffixing,
    except here the id is also part of the record's own body, so the
    returned record carries the adjusted id, not just the returned path.

    Uses exclusive file creation (`open(..., "x")`), not a
    check-then-write on `Path.exists()`, for the same reason
    `curves.library.save` does: two saves landing in the same second must
    not be able to race each other into overwriting one another's file.
    """
    directory = directory if directory is not None else default_dir()
    directory.mkdir(parents=True, exist_ok=True)

    base_id = record.id
    suffix = 0
    while True:
        report_id = base_id if suffix == 0 else f"{base_id}-{suffix + 1}"
        candidate = record if report_id == record.id else _with_id(record, report_id)
        path = directory / f"{report_id}.json"
        body = json.dumps(candidate.to_dict(), indent=2) + "\n"
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(body)
        except FileExistsError:
            suffix += 1
            continue
        return candidate, path


def _with_id(record: ReportRecord, report_id: str) -> ReportRecord:
    # dataclasses.replace would work just as well here; spelled out as a
    # plain constructor call so this file doesn't need to know every
    # field ReportRecord happens to carry stays untouched, only that id
    # does not.
    return ReportRecord(
        id=report_id,
        title=record.title,
        template_id=record.template_id,
        template_version=record.template_version,
        setup=record.setup,
        created_at=record.created_at,
        updated_at=record.updated_at,
        fields=record.fields,
        steps=record.steps,
        open_questions=record.open_questions,
    )


def create(
    template: ReportTemplate,
    title: str,
    fields: dict[str, str] | None = None,
    directory: Path | None = None,
    created_at: datetime | None = None,
) -> ReportRecord:
    """Build a new report from `template` and persist it. Field values
    default to each `FieldDef.default` (e.g. the panel model on this
    bench doesn't change often), overridden by `fields` where given.
    Every template step becomes a fresh `todo` `ReportStep` with no
    linked curves/runs yet."""
    directory = directory if directory is not None else default_dir()
    created_at = created_at if created_at is not None else now_utc()
    merged_fields = {fd.key: fd.default for fd in template.field_defs}
    if fields:
        merged_fields.update(fields)
    steps = tuple(
        ReportStep(
            id=s.id,
            section=s.section,
            title=s.title,
            instructions=s.instructions,
            kind=s.kind,
            unit=s.unit,
            repeats=s.repeats,
        )
        for s in template.steps
    )
    open_questions = tuple(OpenQuestion(id=q.id, text=q.text) for q in template.open_questions)
    stem = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(title)}"
    record = ReportRecord(
        id=stem,
        title=title,
        template_id=template.template_id,
        template_version=template.version,
        setup=template.setup,
        created_at=created_at,
        updated_at=created_at,
        fields=merged_fields,
        steps=steps,
        open_questions=open_questions,
    )
    saved, _path = save(record, directory)
    return saved


def load(path: Path) -> ReportRecord:
    """Parse one report file. Raises `ValueError` naming the file and the
    offending field on a missing key, a bad type, or an unknown
    `schema` - same reasoning as `curves.library.load`/`runs.library.load`:
    these files are hand-editable JSON, not just internal state."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return ReportRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def update(record: ReportRecord, directory: Path | None = None) -> Path:
    """Overwrite an existing report's file in place, atomically (a temp
    file in the same directory, then `os.replace`) - a crash mid-write
    must never leave a half-written report behind. `record.id` must
    already name a file (the API layer loads, modifies, then calls this
    with the same record it loaded); a missing file means something
    upstream resolved the wrong id, so this raises rather than silently
    creating one."""
    directory = directory if directory is not None else default_dir()
    path = directory / f"{record.id}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path}: no such report to update")
    body = json.dumps(record.to_dict(), indent=2) + "\n"
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
    """Delete one report file. Same idempotent, directory-scoped
    behaviour as `curves.library.delete`/`runs.library.delete` - see
    `curves.library.delete`'s docstring for the reasoning. Returns `True`
    if a file was removed, `False` if it was already gone; raises
    `ValueError` if `path` resolves outside `directory` (default
    `default_dir()`)."""
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


def load_all(directory: Path | None = None) -> list[ReportRecord]:
    """Load every `*.json` record in `directory` (default `default_dir()`),
    oldest first (filenames are timestamp-prefixed, so this is
    chronological) - same order as `curves.library.load_all`/
    `runs.library.load_all`. A file that fails to parse raises rather
    than being skipped - a silently-dropped report is worse than a loud
    error."""
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]
