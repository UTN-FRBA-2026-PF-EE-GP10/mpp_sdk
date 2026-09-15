"""One closed-loop MPPT run: a time series of (V, I, D) captured while an
algorithm drove real hardware or a simulated source, plus the metadata
needed to know what it is (see `RUN_SOURCES` below for which) and,
optionally, which captured I-V curve it should be graded against.

Plain stdlib only (no numpy) - mirrors mpp_sdk/curves/record.py's own
reasoning: this module must stay importable anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..curves.record import now_utc  # re-exported below, not duplicated

_SCHEMA = 1

RUN_SOURCES = (
    "hardware",  # driven through SpiMcuSource - a real SEPIC, a real panel
    "simulated",  # driven through SimulatedSource - no board involved at all
    "unknown",  # provenance not recorded (a file written before this field existed)
)
"""Vocabulary for `RunRecord.source`. Mirrors `CURVE_SOURCES` in
mpp_sdk/curves/record.py, and for the same reason: a simulated run and one
that drove the real converter are indistinguishable on disk without this -
grading an algorithm's bench performance against a run that never touched
hardware would be a silent, uncorrectable error in the results.
"""


@dataclass(frozen=True)
class RunSample:
    """One control-loop step. `t` is seconds since the run started
    (wall-clock, from whatever `clock` the loop was given - not assumed to
    be evenly spaced, since real SPI round-trip time varies)."""

    t: float
    voltage: float
    current: float
    duty: float

    def to_dict(self) -> dict:
        return {"t": self.t, "v": self.voltage, "i": self.current, "d": self.duty}

    @classmethod
    def from_dict(cls, d: dict) -> RunSample:
        return cls(t=d["t"], voltage=d["v"], current=d["i"], duty=d["d"])


@dataclass(frozen=True)
class RunRecord:
    """One captured closed-loop run plus the metadata needed to grade it."""

    captured_at: datetime
    label: str
    algorithm: str  # free text, e.g. "P&O" - matches harness/common.py's AlgorithmSpec.label
    samples: tuple[RunSample, ...]
    curve_ref: str | None = None  # filename under mpp_sdk.curves.library.default_dir(), or None
    aborted: bool = False  # True if the safety abort fired before completion
    notes: str = field(default="")
    # Defaults to "unknown" rather than "hardware": a caller that forgets
    # to say what drove this run must not thereby claim it was the real
    # converter. See RUN_SOURCES. Stamped server-side only - never taken
    # from a request body (scripts/curve_tracer_server.py).
    source: str = field(default="unknown")

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "captured_at": self.captured_at.isoformat(),
            "label": self.label,
            "algorithm": self.algorithm,
            "curve_ref": self.curve_ref,
            "aborted": self.aborted,
            "notes": self.notes,
            "source": self.source,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RunRecord:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(f"unsupported run record schema {schema!r}, expected {_SCHEMA}")
        try:
            return cls(
                captured_at=datetime.fromisoformat(d["captured_at"]),
                label=d["label"],
                algorithm=d["algorithm"],
                samples=tuple(RunSample.from_dict(s) for s in d["samples"]),
                curve_ref=d.get("curve_ref"),
                aborted=d.get("aborted", False),
                notes=d.get("notes", ""),
                # Absent in files written before this field existed - those
                # genuinely have no recorded provenance, so say so.
                source=d.get("source", "unknown"),
            )
        except KeyError as exc:
            raise ValueError(f"run record missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"run record has an invalid field: {exc}") from exc


__all__ = ["RunRecord", "RunSample", "RUN_SOURCES", "now_utc"]
