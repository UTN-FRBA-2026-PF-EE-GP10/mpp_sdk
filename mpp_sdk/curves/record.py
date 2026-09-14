"""A single captured I-V sweep, with the measurement context it needs to be
more than a picture: what was on the panel array and how the points group
with other sweeps.

Plain stdlib only (no numpy) - this module must stay importable anywhere,
including off a fresh checkout with none of the optional extras installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

MEASUREMENT_KINDS = (
    "baseline",  # both panels at 90 degrees, facing the light squarely
    "tilted",  # panel B off 90 degrees - one capture or a full sweep across
    # its angles is the same physical setup on this bench, so it is one kind
    "dimmed",  # varying illumination via a controllable lamp dimmer - no
    # such dimmer exists yet, so this kind has no captures for now
    "other",
)
"""Seed vocabulary for `CurveRecord.measurement`. Not an enum: an operator
must be able to record a kind this list did not anticipate without a code
change. The tuple exists so the UI can populate a dropdown and a typo is
visible next to the intended value, not so the field is validated against it.

Tilt convention (bench-specific, not a general SDK concept): light travels
from 180 degrees toward 0 degrees. 90 degrees is vertical, facing the light
squarely - the untilted reference, not zero. Panel A is fixed at 90 degrees
and is never adjusted. Panel B takes one of five detented angles - 90, 70,
60, 45, 30 - where lower means tilted further right, away from the light,
so less illumination reaches it. Panel B at 90 (both panels matching) is
what makes a capture a "baseline".
"""

CURVE_SOURCES = (
    "hardware",  # swept off a real panel through SpiMcuSource
    "firmware-replay",  # a curve stored in the firmware, replayed over real SPI
    "simulated",  # curve_tracer_server.py --demo - no board involved at all
    "unknown",  # provenance not recorded (a file written before this field existed)
)
"""Vocabulary for `CurveRecord.source`. Unlike `MEASUREMENT_KINDS`, which
describes what the operator arranged, this describes where the numbers came
from - a replayed or simulated curve looks exactly like a measured one on
disk, and grading an algorithm against one while believing it is real would
be a silent, uncorrectable error in the results.
"""

_SCHEMA = 1


@dataclass(frozen=True)
class PanelSetup:
    """One panel in the array at the moment of capture."""

    id: str
    tilt_deg: float

    def to_dict(self) -> dict:
        return {"id": self.id, "tilt_deg": self.tilt_deg}

    @classmethod
    def from_dict(cls, d: dict) -> PanelSetup:
        return cls(id=d["id"], tilt_deg=d["tilt_deg"])


@dataclass(frozen=True)
class CurveRecord:
    """One I-V sweep plus the metadata needed to know what it is."""

    captured_at: datetime
    label: str
    measurement: str
    panels: tuple[PanelSetup, ...]
    points: tuple[tuple[float, float], ...]  # (volts, amps), as swept
    notes: str = field(default="")
    # Defaults to "unknown" rather than "hardware": a caller that forgets
    # to say where its points came from must not thereby claim they were
    # measured. See CURVE_SOURCES.
    source: str = field(default="unknown")

    @property
    def open_circuit_voltage(self) -> float:
        """Largest measured voltage. A **measured extreme**, not an
        extrapolated intercept: the sweep stops just past the knee, so this
        is the first point's voltage under near-zero load, not true Voc."""
        return max(v for v, _ in self.points)

    @property
    def short_circuit_current(self) -> float:
        """Largest measured current. A **measured extreme**, not an
        extrapolated intercept - see `open_circuit_voltage`."""
        return max(i for _, i in self.points)

    def mpp(self) -> tuple[float, float, float]:
        """Return `(V, I, P)` at the measured point of maximum power."""
        v, i = max(self.points, key=lambda p: p[0] * p[1])
        return v, i, v * i

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "captured_at": self.captured_at.isoformat(),
            "label": self.label,
            "measurement": self.measurement,
            "panels": [p.to_dict() for p in self.panels],
            "notes": self.notes,
            "source": self.source,
            "points": [{"v": v, "i": i} for v, i in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> CurveRecord:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(f"unsupported curve record schema {schema!r}, expected {_SCHEMA}")
        try:
            captured_at = datetime.fromisoformat(d["captured_at"])
            points = tuple((float(p["v"]), float(p["i"])) for p in d["points"])
            panels = tuple(PanelSetup.from_dict(p) for p in d["panels"])
            return cls(
                captured_at=captured_at,
                label=d["label"],
                measurement=d["measurement"],
                panels=panels,
                points=points,
                notes=d.get("notes", ""),
                # Absent in files written before this field existed - those
                # genuinely have no recorded provenance, so say so.
                source=d.get("source", "unknown"),
            )
        except KeyError as exc:
            raise ValueError(f"curve record missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"curve record has an invalid field: {exc}") from exc


def now_utc() -> datetime:
    """`datetime.now(UTC)`, factored out so capture code and tests share one
    clock call."""
    return datetime.now(UTC)
