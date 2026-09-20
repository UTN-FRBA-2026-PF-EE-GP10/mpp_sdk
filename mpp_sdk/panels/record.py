"""One panel model: the label values (Voc, Isc, Vmp, Imp, Pmax) printed on
a panel, recorded once instead of retyped every bench session.

Not `mpp_sdk.models.PanelModel` (the I-V-curve abstraction algorithms and
the simulation harness run against) - this is bench master data, the same
kind of thing `mpp_sdk.curves.CurveRecord` and `mpp_sdk.sessions.SessionRecord`
are, so it follows their shape exactly.

Plain stdlib only (no numpy) - this module must stay importable anywhere,
including off a fresh checkout with none of the optional extras installed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

_SCHEMA = 1

# String bounds - an operator types these by hand (or a picker composes
# them), so a mistaken paste must not be able to grow a library file
# without limit. Matches the order of magnitude sessions.library uses for
# its own field/notes bounds.
_ID_MAX_LEN = 200
_NAME_MAX_LEN = 200
_MANUFACTURER_MAX_LEN = 200
_MODEL_MAX_LEN = 200
_NOTES_MAX_LEN = 2000

_NUMERIC_FIELDS = ("p_max_w", "voc", "isc", "vmp", "imp")


@dataclass(frozen=True)
class PanelModelRecord:
    """One panel's label specification. `p_max_w`/`voc`/`isc`/`vmp`/`imp`
    are each `None` when genuinely unknown (e.g. a panel whose Vmp/Imp
    were never on hand) rather than a guessed value - a session that
    snapshots this record must show "not recorded", not an invented
    number."""

    id: str
    name: str
    manufacturer: str = field(default="")
    model: str = field(default="")
    p_max_w: float | None = None
    voc: float | None = None
    isc: float | None = None
    vmp: float | None = None
    imp: float | None = None
    notes: str = field(default="")

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "id": self.id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "p_max_w": self.p_max_w,
            "voc": self.voc,
            "isc": self.isc,
            "vmp": self.vmp,
            "imp": self.imp,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PanelModelRecord:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(
                f"unsupported panel model record schema {schema!r}, expected {_SCHEMA}"
            )
        try:
            record = cls(
                id=d["id"],
                name=d["name"],
                manufacturer=d.get("manufacturer", ""),
                model=d.get("model", ""),
                p_max_w=_as_float_or_none(d.get("p_max_w")),
                voc=_as_float_or_none(d.get("voc")),
                isc=_as_float_or_none(d.get("isc")),
                vmp=_as_float_or_none(d.get("vmp")),
                imp=_as_float_or_none(d.get("imp")),
                notes=d.get("notes", ""),
            )
        except KeyError as exc:
            raise ValueError(f"panel model record missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"panel model record has an invalid field: {exc}") from exc
        record.validate()
        return record

    def validate(self) -> None:
        """Checked on every load, not just on write from this codebase -
        these files are hand-editable JSON. Numbers must be finite and
        positive (a negative or NaN Voc is never physically meaningful);
        strings are bounded so a runaway client can't grow a library file
        without limit."""
        if not self.id.strip():
            raise ValueError("panel model id must not be empty")
        if len(self.id) > _ID_MAX_LEN:
            raise ValueError(f"panel model id must be at most {_ID_MAX_LEN} characters")
        if not self.name.strip():
            raise ValueError("panel model name must not be empty")
        if len(self.name) > _NAME_MAX_LEN:
            raise ValueError(f"panel model name must be at most {_NAME_MAX_LEN} characters")
        if len(self.manufacturer) > _MANUFACTURER_MAX_LEN:
            raise ValueError(
                f"panel model manufacturer must be at most {_MANUFACTURER_MAX_LEN} characters"
            )
        if len(self.model) > _MODEL_MAX_LEN:
            raise ValueError(f"panel model model must be at most {_MODEL_MAX_LEN} characters")
        if len(self.notes) > _NOTES_MAX_LEN:
            raise ValueError(f"panel model notes must be at most {_NOTES_MAX_LEN} characters")
        for name in _NUMERIC_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"panel model {name} must be a finite positive number")


def _as_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]


__all__ = ["PanelModelRecord"]
