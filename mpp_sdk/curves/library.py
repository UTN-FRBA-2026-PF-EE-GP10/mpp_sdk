"""Read/write `CurveRecord`s to `data/curves/` (or wherever
`MPP_SDK_CURVE_DIR` points), one JSON file per sweep.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

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

    Uses exclusive file creation (`open(..., "x")`) rather than a
    check-then-write on `Path.exists()`: the server handles each request on
    its own thread, so two saves landing in the same second must not be
    able to race each other into overwriting one another's file."""
    directory = directory if directory is not None else default_dir()
    directory.mkdir(parents=True, exist_ok=True)

    stem = f"{record.captured_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(record.label)}"
    body = json.dumps(record.to_dict(), indent=2) + "\n"
    suffix = 0
    while True:
        name = f"{stem}.json" if suffix == 0 else f"{stem}-{suffix + 1}.json"
        path = directory / name
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(body)
        except FileExistsError:
            suffix += 1
            continue
        return path


def load(path: Path) -> CurveRecord:
    """Parse one curve record file. Raises `ValueError` naming the file and
    the offending field on a missing key, a bad type, or an unknown
    `schema` - these files are hand-edited by operators, not just written
    by this code."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return CurveRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


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
