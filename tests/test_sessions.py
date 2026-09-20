"""Unit tests for `mpp_sdk.sessions`: templates (loading and validation)
and `library.py`'s create/load/update/delete round trip. Pure stdlib, no
hardware, no network - every test uses `tmp_path` as the library
directory.
"""

import json
from datetime import UTC, datetime

import pytest

from mpp_sdk.sessions import (
    STEP_KINDS,
    STEP_STATUSES,
    FieldDef,
    OpenQuestion,
    SessionRecord,
    SessionStep,
    delete,
    get_template,
    list_templates,
    load,
    load_all,
)
from mpp_sdk.sessions import library as session_library
from mpp_sdk.sessions.record import now_utc

_CREATED_AT = datetime(2026, 9, 19, 16, 0, 0, tzinfo=UTC)


def _step(**overrides) -> SessionStep:
    fields = {
        "id": "meter-vout",
        "section": "Before energizing",
        "title": "Meter check of V out",
        "instructions": "At a fixed duty with the load on, compare the meter to the board.",
        "kind": "check",
    }
    fields.update(overrides)
    return SessionStep(**fields)


def _record(**overrides) -> SessionRecord:
    fields = {
        "id": "20260919T160000Z-panel-a-lamp",
        "title": "Panel A alone under the lamp",
        "template_id": "single-panel-characterization",
        "template_version": 1,
        "setup": "single",
        "created_at": _CREATED_AT,
        "updated_at": _CREATED_AT,
        "fields": {"panel": "Luxen LN-10P, 10 W, 12 V", "light": ""},
        "steps": (_step(),),
        "open_questions": (OpenQuestion(id="temperature", text="how to record it?"),),
    }
    fields.update(overrides)
    return SessionRecord(**fields)


# ------------------------------------------------------------------
# Templates
# ------------------------------------------------------------------


def test_list_templates_returns_both_shipped_templates():
    ids = {t.template_id for t in list_templates()}
    assert ids == {"single-panel-characterization", "full-setup-characterization"}


def test_shipped_templates_validate_unique_step_ids_and_known_kinds():
    """`SessionTemplate.from_dict` (called by `list_templates`) raises on a
    duplicate step id or an unknown kind - so a template that loads at all
    has already passed both checks. Re-verified explicitly here so a
    future template edit that broke one of these fails this test, not
    just "some session failed to load" downstream."""
    for template in list_templates():
        step_ids = [s.id for s in template.steps]
        assert len(step_ids) == len(set(step_ids)), template.template_id
        assert all(s.kind in STEP_KINDS for s in template.steps), template.template_id
        assert template.n_steps == len(template.steps)


def test_single_panel_template_covers_the_appendix_checklist():
    template = get_template("single-panel-characterization")
    assert template.setup == "single"
    panel_default = next(f for f in template.field_defs if f.key == "panel").default
    assert panel_default == "Luxen LN-10P, 10 W, 12 V"
    sections = {s.section for s in template.steps}
    assert sections == {
        "Before energizing",
        "Link and limits",
        "Light and curve",
        "Runs (curve as reference, 10 s, starting duty 0.5)",
        "After",
    }
    # The four panel-label readings are no longer steps - they're
    # snapshotted from a picked panel model straight into these fields
    # (mpp_sdk.panels), read-only in the workbench.
    assert {"panel_model_voc", "panel_model_isc", "panel_model_vmp", "panel_model_imp"} <= {
        f.key for f in template.field_defs
    }
    question_ids = {q.id for q in template.open_questions}
    assert "temperature" in question_ids


def test_full_setup_template_is_for_full_setup():
    template = get_template("full-setup-characterization")
    assert template.setup == "full"
    assert template.n_steps > 0
    question_ids = {q.id for q in template.open_questions}
    assert "temperature" in question_ids


def test_both_templates_carry_the_temperature_open_question_verbatim():
    expected = (
        "Panel temperature is not measured (no PT100 fitted; the MAX31865 is off). "
        "Voc falls with temperature, so curves taken at different times are not "
        "strictly comparable. How to record it: a contact thermometer on the panel "
        "back, an IR thermometer, or a fitted PT100?"
    )
    for template_id in ("single-panel-characterization", "full-setup-characterization"):
        template = get_template(template_id)
        question = next(q for q in template.open_questions if q.id == "temperature")
        assert question.text == expected


def test_get_template_unknown_id_raises_key_error():
    with pytest.raises(KeyError):
        get_template("does-not-exist")


def test_session_template_from_dict_rejects_a_duplicate_step_id():
    from mpp_sdk.sessions.templates import SessionTemplate

    data = {
        "schema": 1,
        "template_id": "broken",
        "version": 1,
        "title": "Broken",
        "setup": "single",
        "field_defs": [],
        "steps": [
            {"id": "dup", "section": "s", "title": "a", "instructions": "x", "kind": "check"},
            {"id": "dup", "section": "s", "title": "b", "instructions": "y", "kind": "check"},
        ],
        "open_questions": [],
    }
    with pytest.raises(ValueError, match="duplicate step id"):
        SessionTemplate.from_dict(data)


def test_session_template_from_dict_rejects_an_unknown_kind():
    from mpp_sdk.sessions.templates import SessionTemplate

    data = {
        "schema": 1,
        "template_id": "broken",
        "version": 1,
        "title": "Broken",
        "setup": "single",
        "field_defs": [],
        "steps": [
            {"id": "a", "section": "s", "title": "a", "instructions": "x", "kind": "not-a-kind"},
        ],
        "open_questions": [],
    }
    with pytest.raises(ValueError, match="unknown"):
        SessionTemplate.from_dict(data)


def _one_step_template(**step) -> dict:
    base = {"id": "a", "section": "s", "title": "a", "instructions": "x", "kind": "curve"}
    base.update(step)
    return {
        "schema": 1,
        "template_id": "t",
        "version": 1,
        "title": "T",
        "setup": "single",
        "field_defs": [],
        "steps": [base],
        "open_questions": [],
    }


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ({"repeats": 0}, "repeats"),
        ({"repeats": 21}, "repeats"),
        ({"repeats": True}, "repeats"),
        ({"repeats": 2.0}, "repeats"),
        ({"repeats": 3, "kind": "number"}, "only curve and run"),
    ],
)
def test_session_template_from_dict_rejects_bad_repeats(step, match):
    from mpp_sdk.sessions.templates import SessionTemplate

    with pytest.raises(ValueError, match=match):
        SessionTemplate.from_dict(_one_step_template(**step))


def test_session_template_repeats_defaults_to_one():
    from mpp_sdk.sessions.templates import SessionTemplate

    template = SessionTemplate.from_dict(_one_step_template())
    assert template.steps[0].repeats == 1


def test_shipped_templates_ask_for_repeated_curves_and_runs():
    for template in list_templates():
        baseline = next(s for s in template.steps if s.id == "baseline-curve")
        assert baseline.repeats == 3
        runs = [s for s in template.steps if s.kind == "run" and s.repeats > 1]
        assert runs, template.template_id


def test_full_setup_template_defaults_to_the_hissuma_panels():
    fields = {f.key: f.default for f in get_template("full-setup-characterization").field_defs}
    assert "Hissuma PSF10MONO" in fields["panel_a"]
    assert "Hissuma PSF10MONO" in fields["panel_b"]


def test_full_setup_template_has_snapshot_fields_for_both_panels():
    keys = {f.key for f in get_template("full-setup-characterization").field_defs}
    for prefix in ("panel_a", "panel_b"):
        assert {
            f"{prefix}_model_voc",
            f"{prefix}_model_isc",
            f"{prefix}_model_vmp",
            f"{prefix}_model_imp",
        } <= keys


def test_field_def_is_editable_unless_the_template_says_readonly():
    assert FieldDef.from_dict({"key": "operator", "label": "Operator"}).readonly is False
    locked = FieldDef.from_dict({"key": "x", "label": "X", "readonly": True})
    assert locked.readonly is True
    assert FieldDef.from_dict(locked.to_dict()) == locked


def test_shipped_templates_declare_exactly_the_panel_model_numbers_readonly():
    """`PATCH /api/sessions/{id}` locks whatever a template marks
    `readonly` - so the snapshot fields must be marked there, and nothing
    else (the free-text panel label stays editable)."""
    single = {f.key for f in get_template("single-panel-characterization").field_defs if f.readonly}
    assert single == {f"panel_model_{q}" for q in ("voc", "isc", "vmp", "imp")}
    full = {f.key for f in get_template("full-setup-characterization").field_defs if f.readonly}
    assert full == {f"panel_{p}_model_{q}" for p in "ab" for q in ("voc", "isc", "vmp", "imp")}


# ------------------------------------------------------------------
# library.create
# ------------------------------------------------------------------


def test_create_builds_a_session_from_a_template_and_persists_it(tmp_path):
    template = get_template("single-panel-characterization")
    record = session_library.create(template, "Panel A alone", directory=tmp_path)
    assert record.template_id == template.template_id
    assert record.setup == "single"
    assert record.n_steps == template.n_steps
    assert all(s.status == "todo" for s in record.steps)
    assert [s.repeats for s in record.steps] == [s.repeats for s in template.steps]
    assert (tmp_path / f"{record.id}.json").exists()


def test_create_seeds_fields_from_template_defaults(tmp_path):
    template = get_template("single-panel-characterization")
    record = session_library.create(template, "Panel A alone", directory=tmp_path)
    assert record.fields["panel"] == "Luxen LN-10P, 10 W, 12 V"
    assert record.fields["adc_range"] == "Low"


def test_create_overrides_defaults_with_given_fields(tmp_path):
    template = get_template("single-panel-characterization")
    record = session_library.create(
        template, "Panel A alone", fields={"operator": "bench operator"}, directory=tmp_path
    )
    assert record.fields["operator"] == "bench operator"
    assert record.fields["panel"] == "Luxen LN-10P, 10 W, 12 V"


def test_create_on_collision_appends_a_suffix_to_the_id_and_the_body(tmp_path):
    template = get_template("single-panel-characterization")
    first = session_library.create(template, "dup", directory=tmp_path, created_at=_CREATED_AT)
    second = session_library.create(template, "dup", directory=tmp_path, created_at=_CREATED_AT)
    assert first.id != second.id
    assert second.id.endswith("-2")
    # The id inside the saved body must match the filename it lives in.
    assert load(tmp_path / f"{second.id}.json").id == second.id


# ------------------------------------------------------------------
# Round trip
# ------------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path):
    record = _record(steps=(_step(), _step(id="baseline", kind="curve", repeats=3)))
    _saved, path = session_library.save(record, tmp_path)
    assert load(path) == record


def test_save_names_file_from_the_records_own_id(tmp_path):
    record = _record()
    _saved, path = session_library.save(record, tmp_path)
    assert path.name == "20260919T160000Z-panel-a-lamp.json"


# ------------------------------------------------------------------
# Parse errors
# ------------------------------------------------------------------


def test_load_rejects_unknown_schema(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    data["schema"] = 2
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="schema"):
        load(path)


def test_load_rejects_missing_steps_field(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    del data["steps"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="steps"):
        load(path)


def test_load_rejects_not_valid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load(path)


# ------------------------------------------------------------------
# update (atomic save-in-place)
# ------------------------------------------------------------------


def test_update_overwrites_the_existing_file_in_place(tmp_path):
    record = _record()
    _saved, path = session_library.save(record, tmp_path)

    updated = SessionRecord(
        id=record.id,
        title="Panel A, second pass",
        template_id=record.template_id,
        template_version=record.template_version,
        setup=record.setup,
        created_at=record.created_at,
        updated_at=now_utc(),
        fields=record.fields,
        steps=record.steps,
        open_questions=record.open_questions,
    )
    returned_path = session_library.update(updated, directory=tmp_path)
    assert returned_path == path
    assert load(path).title == "Panel A, second pass"


def test_update_leaves_no_temp_file_behind(tmp_path):
    record = _record()
    session_library.save(record, tmp_path)
    session_library.update(record, directory=tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {f"{record.id}.json"}


def test_update_of_a_session_with_no_existing_file_raises(tmp_path):
    record = _record()
    with pytest.raises(FileNotFoundError):
        session_library.update(record, directory=tmp_path)


# ------------------------------------------------------------------
# delete
# ------------------------------------------------------------------


def test_delete_removes_the_file_and_returns_true(tmp_path):
    _saved, path = session_library.save(_record(), tmp_path)
    assert delete(path, tmp_path) is True
    assert not path.exists()


def test_delete_of_an_already_gone_file_is_a_no_op_returning_false(tmp_path):
    _saved, path = session_library.save(_record(), tmp_path)
    path.unlink()
    assert delete(path, tmp_path) is False


def test_delete_refuses_a_path_outside_the_library_directory(tmp_path):
    outside = tmp_path.parent / "not-a-session.json"
    outside.write_text("{}")
    try:
        with pytest.raises(ValueError, match="outside"):
            delete(outside, tmp_path)
        assert outside.exists()
    finally:
        outside.unlink()


# ------------------------------------------------------------------
# load_all
# ------------------------------------------------------------------


def test_load_all_returns_every_record_oldest_first(tmp_path):
    early = _record(id="20260919T160000Z-one", title="one")
    late = _record(id="20260919T170000Z-two", title="two")
    session_library.save(late, tmp_path)
    session_library.save(early, tmp_path)
    records = load_all(tmp_path)
    assert [r.title for r in records] == ["one", "two"]


def test_load_all_on_missing_directory_returns_empty_list(tmp_path):
    assert load_all(tmp_path / "does-not-exist") == []


# ------------------------------------------------------------------
# Progress counts
# ------------------------------------------------------------------


def test_progress_counts_reflect_step_status():
    record = _record(
        steps=(
            _step(id="a", status="done"),
            _step(id="b", status="failed"),
            _step(id="c", status="todo"),
            _step(id="d", status="skipped"),
        )
    )
    assert record.n_steps == 4
    assert record.n_done == 1
    assert record.n_failed == 1


def test_step_statuses_and_kinds_are_pinned():
    # A rename here is a breaking change for saved sessions and the
    # frontend's vocabulary - pin the tuples so a future rename is a
    # deliberate edit to this test.
    assert STEP_STATUSES == ("todo", "done", "failed", "skipped")
    assert STEP_KINDS == ("check", "number", "text", "curve", "run")
