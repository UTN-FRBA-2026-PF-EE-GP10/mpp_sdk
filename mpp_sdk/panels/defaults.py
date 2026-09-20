"""Shipped default panel models: package data, not user data (that's
`mpp_sdk.panels.library`'s job) - read via `importlib.resources` rather
than a repo-relative path, the same reasoning as
`mpp_sdk.sessions.templates`: a default has to be readable from an
installed (non-editable) wheel too. See `pyproject.toml`'s
`[tool.hatch.build.targets.wheel]` for how these files are included.
"""

from __future__ import annotations

import json
from importlib import resources

from .record import PanelModelRecord


def _defaults_dir():
    return resources.files(__package__) / "defaults"


def list_default_panels() -> list[PanelModelRecord]:
    """Every panel model shipped with the SDK, sorted by id for a
    deterministic listing."""
    records = []
    for entry in _defaults_dir().iterdir():
        if entry.name.endswith(".json"):
            data = json.loads(entry.read_text(encoding="utf-8"))
            records.append(PanelModelRecord.from_dict(data))
    return sorted(records, key=lambda r: r.id)


__all__ = ["list_default_panels"]
