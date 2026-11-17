"""Read/write `RunRecord`s to `data/runs/` (or wherever `MPP_SDK_RUN_DIR`
points), one JSON file per run."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .._files import read_json_object, write_new
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
    """Write `record` as `{captured_at}-{slug(label)}.json`. Same rules as
    `mpp_sdk.curves.library.save`: atomic, `-2`/`-3`/... suffix on
    collision, never overwrites."""
    directory = directory if directory is not None else default_dir()
    stem = f"{record.captured_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(record.label)}"
    body = json.dumps(record.to_dict(), indent=2, allow_nan=False) + "\n"
    return write_new(directory, stem, body)


def load(path: Path) -> RunRecord:
    """Parse one run record file - same error-reporting philosophy as
    `mpp_sdk.curves.library.load` (named file + field, since these are
    hand-editable JSON, not just internal state)."""
    data = read_json_object(path)
    try:
        return RunRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def delete(path: Path, directory: Path | None = None) -> bool:
    """Delete one run record file. Same idempotent, directory-scoped
    behaviour as `mpp_sdk.curves.library.delete` - see its docstring for
    the reasoning. Returns `True` if a file was removed, `False` if it was
    already gone; raises `ValueError` if `path` resolves outside
    `directory` (default `default_dir()`)."""
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


_INDEX_NAME = ".summary-index"


def summarize(record: RunRecord) -> dict:
    """The fields a run listing shows, without the sample arrays."""
    samples = record.samples
    return {
        "captured_at": record.captured_at.isoformat(),
        "label": record.label,
        "algorithm": record.algorithm,
        "n_samples": len(samples),
        "duration_s": samples[-1].t - samples[0].t if len(samples) >= 2 else 0.0,
        "aborted": record.aborted,
        "curve_ref": record.curve_ref,
        "notes": record.notes,
        "source": record.source,
        "session_id": record.session_id,
    }


def _read_index(directory: Path) -> dict:
    try:
        data = json.loads((directory / _INDEX_NAME).read_text())
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_index(directory: Path, index: dict) -> None:
    # Only a cache: a failed write just means the next listing rebuilds it.
    tmp = directory / f"{_INDEX_NAME}.tmp"
    try:
        tmp.write_text(json.dumps(index))
        os.replace(tmp, directory / _INDEX_NAME)
    except OSError:
        pass


def list_summaries(directory: Path | None = None) -> list[tuple[Path, dict | str]]:
    """One `(path, summary)` per run file, sorted by name. The summary
    comes from a sidecar index when the file's mtime and size still match;
    otherwise the full file is parsed and the index refreshed. A file that
    cannot be parsed gives its error message instead of a summary."""
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    index = _read_index(directory)
    fresh: dict = {}
    out: list[tuple[Path, dict | str]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            st = path.stat()
        except OSError as exc:
            out.append((path, str(exc)))
            continue
        cached = index.get(path.name)
        if (
            isinstance(cached, dict)
            and cached.get("mtime_ns") == st.st_mtime_ns
            and cached.get("size") == st.st_size
            and isinstance(cached.get("summary"), dict)
        ):
            fresh[path.name] = cached
            out.append((path, cached["summary"]))
            continue
        try:
            summary = summarize(load(path))
        except ValueError as exc:
            out.append((path, str(exc)))
            continue
        fresh[path.name] = {"mtime_ns": st.st_mtime_ns, "size": st.st_size, "summary": summary}
        out.append((path, summary))
    if fresh != index:
        _write_index(directory, fresh)
    return out


def load_all(directory: Path | None = None) -> list[RunRecord]:
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]
