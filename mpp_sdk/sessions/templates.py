"""Session templates: the checklist shape a new session starts from.

Templates ship as JSON files under `mpp_sdk/sessions/templates/` -
**package data**, not user data (that's `mpp_sdk.sessions.library`'s
job). Read via `importlib.resources` rather than a repo-relative path:
the latter only works from a checkout, and a template has to be
readable from an installed (non-editable) wheel too - see
`pyproject.toml`'s `[tool.hatch.build.targets.wheel]` for how these
files are included.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from .record import MAX_REPEATS, STEP_KINDS

_SCHEMA = 1


@dataclass(frozen=True)
class FieldDef:
    """One setup field a template asks for - the workbench renders these
    as a small editable table (Part C). `default` seeds a new session's
    `fields[key]` (e.g. the panel model on this bench doesn't change
    often, so a new session should not start with it blank).

    `readonly` marks a field a session only ever gets written into once,
    at creation, by something other than the operator typing into the
    table - a panel model snapshot (`panel_model_voc` and friends) is the
    only case today. It is the data `PATCH /api/sessions/{id}` checks
    against to refuse an edit to one of these fields after the fact (see
    `curve_tracer_server.py`'s `patch_session`) - declared here, on the
    template, rather than inferred from the key's shape, so a future
    snapshot field can't be forgotten by a regex that doesn't know about
    it yet."""

    key: str
    label: str
    hint: str = ""
    default: str = ""
    readonly: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "hint": self.hint,
            "default": self.default,
            "readonly": self.readonly,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FieldDef:
        return cls(
            key=d["key"],
            label=d["label"],
            hint=d.get("hint", ""),
            default=d.get("default", ""),
            readonly=bool(d.get("readonly", False)),
        )


@dataclass(frozen=True)
class TemplateStep:
    """One step definition inside a template - becomes one
    `mpp_sdk.sessions.record.SessionStep` per session created from it.
    Pass criteria live inside `instructions` as plain text, not as a
    separate structured field: a checklist item is read and judged by a
    person at the bench, not evaluated by code."""

    id: str
    section: str
    title: str
    instructions: str
    kind: str
    unit: str | None = None
    # How many curves or runs the step asks for. More than one gives the
    # spread (median, deviation) of a result, not just one sample of it.
    repeats: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "section": self.section,
            "title": self.title,
            "instructions": self.instructions,
            "kind": self.kind,
            "unit": self.unit,
            "repeats": self.repeats,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TemplateStep:
        return cls(
            id=d["id"],
            section=d["section"],
            title=d["title"],
            instructions=d["instructions"],
            kind=d["kind"],
            unit=d.get("unit"),
            repeats=d.get("repeats", 1),
        )


@dataclass(frozen=True)
class TemplateQuestion:
    """One open question a template starts every session with, e.g. how
    panel temperature should be recorded - answered per session, not
    resolved once and dropped from the template."""

    id: str
    text: str

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> TemplateQuestion:
        return cls(id=d["id"], text=d["text"])


@dataclass(frozen=True)
class SessionTemplate:
    """A session without values: the shape `mpp_sdk.sessions.library.create`
    fills in to produce a new `SessionRecord`."""

    template_id: str
    version: int
    title: str
    setup: str  # "single" | "full" - which workbench setup mode this fits
    field_defs: tuple[FieldDef, ...]
    steps: tuple[TemplateStep, ...]
    open_questions: tuple[TemplateQuestion, ...] = field(default_factory=tuple)

    @property
    def n_steps(self) -> int:
        return len(self.steps)

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "template_id": self.template_id,
            "version": self.version,
            "title": self.title,
            "setup": self.setup,
            "field_defs": [f.to_dict() for f in self.field_defs],
            "steps": [s.to_dict() for s in self.steps],
            "open_questions": [q.to_dict() for q in self.open_questions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> SessionTemplate:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(f"unsupported session template schema {schema!r}, expected {_SCHEMA}")
        try:
            steps = tuple(TemplateStep.from_dict(s) for s in d["steps"])
            template = cls(
                template_id=d["template_id"],
                version=d["version"],
                title=d["title"],
                setup=d["setup"],
                field_defs=tuple(FieldDef.from_dict(f) for f in d.get("field_defs", ())),
                steps=steps,
                open_questions=tuple(
                    TemplateQuestion.from_dict(q) for q in d.get("open_questions", ())
                ),
            )
        except KeyError as exc:
            raise ValueError(f"session template missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"session template has an invalid field: {exc}") from exc
        template._validate()
        return template

    def _validate(self) -> None:
        """A malformed template silently breaks every session created
        from it, so these are checked once here rather than left for a
        client to discover: step ids must be unique (a PATCH addresses a
        step by id) and every kind must be one this SDK understands."""
        seen: set[str] = set()
        for s in self.steps:
            if s.id in seen:
                raise ValueError(
                    f"session template {self.template_id!r}: duplicate step id {s.id!r}"
                )
            seen.add(s.id)
            if s.kind not in STEP_KINDS:
                raise ValueError(
                    f"session template {self.template_id!r}: step {s.id!r} has unknown "
                    f"kind {s.kind!r}, expected one of {STEP_KINDS}"
                )
            if type(s.repeats) is not int or not 1 <= s.repeats <= MAX_REPEATS:
                raise ValueError(
                    f"session template {self.template_id!r}: step {s.id!r} has repeats "
                    f"{s.repeats!r}, expected an integer from 1 to {MAX_REPEATS}"
                )
            if s.repeats > 1 and s.kind not in ("curve", "run"):
                raise ValueError(
                    f"session template {self.template_id!r}: step {s.id!r} has repeats "
                    f"{s.repeats} but only curve and run steps can repeat"
                )


def _template_dir():
    return resources.files(__package__) / "templates"


def list_templates() -> list[SessionTemplate]:
    """Every template shipped with the SDK, sorted by `template_id` for a
    deterministic listing."""
    templates = []
    for entry in _template_dir().iterdir():
        if entry.name.endswith(".json"):
            data = json.loads(entry.read_text(encoding="utf-8"))
            templates.append(SessionTemplate.from_dict(data))
    return sorted(templates, key=lambda t: t.template_id)


def get_template(template_id: str) -> SessionTemplate:
    """Look up one template by id. Raises `KeyError` (not `ValueError`)
    on a miss, so callers can tell "no such template" apart from "a
    template file on disk is malformed", which `list_templates` already
    raises loudly rather than skipping."""
    for template in list_templates():
        if template.template_id == template_id:
            return template
    raise KeyError(template_id)


__all__ = [
    "SessionTemplate",
    "FieldDef",
    "TemplateStep",
    "TemplateQuestion",
    "list_templates",
    "get_template",
]
