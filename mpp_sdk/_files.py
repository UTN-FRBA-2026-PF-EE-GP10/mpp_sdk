"""Small file helpers shared by the on-disk record libraries."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_new(directory: Path, stem: str, body: str) -> Path:
    """Write `body` to `{stem}.json` in `directory` and return the path.

    Never overwrites: on a name collision it tries `{stem}-2.json`,
    `{stem}-3.json`, ... The file appears complete or not at all. It is
    written to a temp file first and then hard-linked into place, because
    a power cut during a plain write leaves a truncated record that no
    longer loads. `os.link` fails if the target exists, which keeps the
    no-overwrite rule even when two saves race.
    """
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{stem}-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        suffix = 0
        while True:
            name = f"{stem}.json" if suffix == 0 else f"{stem}-{suffix + 1}.json"
            path = directory / name
            try:
                os.link(tmp, path)
            except FileExistsError:
                suffix += 1
                continue
            return path
    finally:
        tmp.unlink(missing_ok=True)


def read_json_object(path: Path) -> dict:
    """Parse `path` as a JSON object. Raises `ValueError` naming the file
    if it is not valid JSON or not an object: a record file holding `[]`
    or `null` must fail like any other bad record, not crash the caller."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object, got {type(data).__name__}")
    return data
