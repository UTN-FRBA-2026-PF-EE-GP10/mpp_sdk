"""Read/write `CurveRecord`s to `data/curves/` (or wherever
`MPP_SDK_CURVE_DIR` points), one JSON file per sweep.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from .._files import read_json_object, write_new
from .record import CurveRecord

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SLUG_MAX_LEN = 40


def default_dir() -> Path:
    """`data/curves/` under the repo root, overridable via
    `MPP_SDK_CURVE_DIR` (tests use this to avoid touching the real
    directory)."""
    override = os.environ.get("MPP_SDK_CURVE_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "curves"


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug[:_SLUG_MAX_LEN].rstrip("-") or "curve"


def save(record: CurveRecord, directory: Path | None = None) -> Path:
    """Write `record` as `{captured_at}-{slug(label)}.json`. On a filename
    collision (two saves in the same second), append `-2`, `-3`, ... rather
    than overwriting - a captured measurement is never silently lost.

    The write is atomic and never overwrites (see `mpp_sdk._files.write_new`):
    the server handles each request on its own thread, so two saves in the
    same second must not race into one file, and a power cut must not leave
    a truncated record."""
    directory = directory if directory is not None else default_dir()
    stem = f"{record.captured_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(record.label)}"
    body = json.dumps(record.to_dict(), indent=2, allow_nan=False) + "\n"
    return write_new(directory, stem, body)


def load(path: Path) -> CurveRecord:
    """Parse one curve record file. Raises `ValueError` naming the file and
    the offending field on a missing key, a bad type, or an unknown
    `schema` - these files are hand-edited by operators, not just written
    by this code."""
    data = read_json_object(path)
    try:
        return CurveRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def delete(path: Path, directory: Path | None = None) -> bool:
    """Delete one curve record file. Returns `True` if a file was removed,
    `False` if it was already gone - a delete is idempotent, since a UI
    button firing twice (or acting on a listing that's gone stale) must not
    surface as a hard error.

    Refuses to delete anything outside `directory` (default `default_dir()`)
    and raises `ValueError` if `path` resolves outside it. The API layer
    maps an untrusted URL id to a path through this same directory, and a
    bug there must not turn into an arbitrary-file delete."""
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


def load_all(directory: Path | None = None) -> list[CurveRecord]:
    """Load every `*.json` record in `directory` (default `default_dir()`).
    A file that fails to parse raises rather than being skipped - a
    silently-dropped curve is worse than a loud error."""
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]


def group_by_measurement(records: list[CurveRecord]) -> dict[str, list[CurveRecord]]:
    """Bucket `records` by `.measurement`, preserving input order within
    each bucket."""
    groups: dict[str, list[CurveRecord]] = defaultdict(list)
    for record in records:
        groups[record.measurement].append(record)
    return dict(groups)
