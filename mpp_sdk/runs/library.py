"""Read/write `RunRecord`s to `data/runs/` (or wherever `MPP_SDK_RUN_DIR`
points), one JSON file per run."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .record import RunRecord

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SLUG_MAX_LEN = 40


def default_dir() -> Path:
    """`data/runs/` under the repo root, overridable via `MPP_SDK_RUN_DIR`
    (tests use this to avoid touching the real directory)."""
    override = os.environ.get("MPP_SDK_RUN_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "runs"


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug[:_SLUG_MAX_LEN].rstrip("-") or "run"


def save(record: RunRecord, directory: Path | None = None) -> Path:
    """Write `record` as `{captured_at}-{slug(label)}.json`. Same
    collision handling as `mpp_sdk.curves.library.save` - exclusive
    creation, `-2`/`-3`/... suffix on collision, never overwrites."""
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


def load(path: Path) -> RunRecord:
    """Parse one run record file - same error-reporting philosophy as
    `mpp_sdk.curves.library.load` (named file + field, since these are
    hand-editable JSON, not just internal state)."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return RunRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def load_all(directory: Path | None = None) -> list[RunRecord]:
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]
