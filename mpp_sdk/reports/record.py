"""One measurement report: a filled-in copy of a checklist template,
tracked from setup to teardown, with its curves and runs linked in rather
than copied.

Plain stdlib only (no numpy) - mirrors mpp_sdk/curves/record.py's and
mpp_sdk/runs/record.py's own reasoning: this module must stay importable
anywhere, including off a fresh checkout with none of the optional extras
installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..curves.record import now_utc  # re-exported below, not duplicated

_SCHEMA = 1

STEP_KINDS = ("check", "number", "text", "curve", "run")
"""What a step asks for. `check`: done or not, no value. `number`: a
value with a `unit` (a meter reading, a percentage). `text`: free text.
`curve` / `run`: the step expects one or more linked curves/runs (see
`ReportStep.curve_ids`/`run_ids`) - the panel-label numbers or a meter
reading are `number` steps even though a curve or run informs them; only
a step whose whole point is "capture and attach this" is `curve`/`run`."""

MAX_REPEATS = 20
"""Upper bound on a step's `repeats`, well below the 100 linked ids a
step may hold."""

STEP_STATUSES = ("todo", "done", "failed", "skipped")
"""A step's progress. Distinct from `kind`: a `check` step is `done` once
verified, not because it holds a value - status is the one field every
kind shares."""


@dataclass(frozen=True)
class ReportStep:
    """One checklist item, filled in from a `mpp_sdk.reports.templates.
    TemplateStep`. `curve_ids`/`run_ids` are ids as served by
    `/api/curves`/`/api/runs` (filename stems) - a report never copies
    curve or run data, it links to it, so a linked item stays exactly as
    fresh (or as deleted) as the library entry it points at."""

    id: str
    section: str
    title: str
    instructions: str
    kind: str
    status: str = "todo"
    # float for a `number` step, str for `text`, unused (None) for
    # `check`/`curve`/`run` - not enforced against `kind` here, the same
    # way CurveRecord doesn't enforce `measurement` against a fixed enum
    # (see MEASUREMENT_KINDS's docstring): a hand-edited report file must
    # not become unreadable over a value that no longer matches its kind.
    value: float | str | None = None
    unit: str | None = None
    notes: str = field(default="")
    curve_ids: tuple[str, ...] = field(default_factory=tuple)
    run_ids: tuple[str, ...] = field(default_factory=tuple)
    # Copied from the template: how many curves or runs to link. The
    # reader computes the median and spread over the linked items.
    repeats: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "section": self.section,
            "title": self.title,
            "instructions": self.instructions,
            "kind": self.kind,
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "notes": self.notes,
            "curve_ids": list(self.curve_ids),
            "run_ids": list(self.run_ids),
            "repeats": self.repeats,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ReportStep:
        return cls(
            id=d["id"],
            section=d["section"],
            title=d["title"],
            instructions=d["instructions"],
            kind=d["kind"],
            status=d.get("status", "todo"),
            value=d.get("value"),
            unit=d.get("unit"),
            notes=d.get("notes", ""),
            curve_ids=tuple(d.get("curve_ids", ())),
            run_ids=tuple(d.get("run_ids", ())),
            repeats=d.get("repeats", 1),
        )


@dataclass(frozen=True)
class OpenQuestion:
    """One unresolved question carried on the report, e.g. "how do we
    record panel temperature" - answered in place, not closed and
    forgotten, so the answer travels with the session it came from."""

    id: str
    text: str
    answer: str = field(default="")

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "answer": self.answer}

    @classmethod
    def from_dict(cls, d: dict) -> OpenQuestion:
        return cls(id=d["id"], text=d["text"], answer=d.get("answer", ""))


@dataclass(frozen=True)
class ReportRecord:
    """One measurement report. Unlike `CurveRecord`/`RunRecord`, this
    carries its own `id`: a report is mutable (edited step by step over a
    session, via PATCH), so its id has to be stable and known up front
    for a client to keep referring to the same report - it is not, as for
    curves/runs, just the filename stem an API layer derives on read.
    `mpp_sdk.reports.library.save` mints it once, at creation."""

    id: str
    title: str
    template_id: str
    template_version: int
    setup: str
    created_at: datetime
    updated_at: datetime
    fields: dict[str, str]
    steps: tuple[ReportStep, ...]
    open_questions: tuple[OpenQuestion, ...] = field(default_factory=tuple)

    @property
    def n_steps(self) -> int:
        return len(self.steps)

    @property
    def n_done(self) -> int:
        return sum(1 for s in self.steps if s.status == "done")

    @property
    def n_failed(self) -> int:
        return sum(1 for s in self.steps if s.status == "failed")

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "id": self.id,
            "title": self.title,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "setup": self.setup,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "fields": dict(self.fields),
            "steps": [s.to_dict() for s in self.steps],
            "open_questions": [q.to_dict() for q in self.open_questions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ReportRecord:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(f"unsupported report record schema {schema!r}, expected {_SCHEMA}")
        try:
            return cls(
                id=d["id"],
                title=d["title"],
                template_id=d["template_id"],
                template_version=d["template_version"],
                setup=d["setup"],
                created_at=datetime.fromisoformat(d["created_at"]),
                updated_at=datetime.fromisoformat(d["updated_at"]),
                fields=dict(d.get("fields", {})),
                steps=tuple(ReportStep.from_dict(s) for s in d["steps"]),
                open_questions=tuple(
                    OpenQuestion.from_dict(q) for q in d.get("open_questions", ())
                ),
            )
        except KeyError as exc:
            raise ValueError(f"report record missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"report record has an invalid field: {exc}") from exc


__all__ = [
    "ReportRecord",
    "ReportStep",
    "OpenQuestion",
    "STEP_KINDS",
    "STEP_STATUSES",
    "now_utc",
]
