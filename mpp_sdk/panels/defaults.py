"""Shipped default panel models: package data, not user data (that's
`mpp_sdk.panels.library`'s job) - read via `importlib.resources` rather
than a repo-relative path, the same reasoning as
`mpp_sdk.sessions.templates`: a default has to be readable from an
installed (non-editable) wheel too. See `pyproject.toml`'s
`[tool.hatch.build.targets.wheel]` for how these files are included.
"""

from __future__ import annotations

import json
import logging
from importlib import resources

from .record import PanelModelRecord

_log = logging.getLogger(__name__)


def _defaults_dir():
    return resources.files(__package__) / "defaults"


def list_default_panels() -> list[PanelModelRecord]:
    """Every panel model shipped with the SDK, sorted by id for a
    deterministic listing.

    A default that cannot be read or parsed is skipped and logged, never
    raised: this runs while the server starts (`create_app` seeds the
    library), and one bad packaged file must not stop the whole workbench
    from coming up - the same per-file fault isolation every other
    hand-editable-JSON listing in this codebase applies."""
    records = []
    for entry in _defaults_dir().iterdir():
        if not entry.name.endswith(".json"):
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            records.append(PanelModelRecord.from_dict(data))
        except (OSError, ValueError, AttributeError) as exc:
            # ValueError covers bad JSON, bad UTF-8 and every from_dict
            # rejection; AttributeError is a JSON document that is not an
            # object (from_dict calls .get on it).
            _log.warning("skipping shipped panel model %s: %s", entry.name, exc)
    return sorted(records, key=lambda r: r.id)


__all__ = ["list_default_panels"]
