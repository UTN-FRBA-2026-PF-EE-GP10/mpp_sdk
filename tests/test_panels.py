"""Unit tests for `mpp_sdk.panels`: the record's validation, the
library's create/load/update/delete round trip, and the shipped defaults.
Pure stdlib, no hardware, no network - every test uses `tmp_path` as the
library directory.
"""

import json
import shutil
import subprocess
from dataclasses import replace

import pytest

from mpp_sdk.panels import PanelModelRecord, list_default_panels
from mpp_sdk.panels import library as panel_library


def _record(**overrides) -> PanelModelRecord:
    fields = {
        "id": "luxen-ln-10p",
        "name": "Luxen LN-10P",
        "manufacturer": "Luxen",
        "model": "LN-10P",
        "p_max_w": 10.0,
        "voc": 23.5,
        "isc": 0.57,
        "notes": "Reads a little above its label in strong sun.",
    }
    fields.update(overrides)
    return PanelModelRecord(**fields)


# ------------------------------------------------------------------
# Record validation
# ------------------------------------------------------------------


def test_to_dict_from_dict_round_trips():
    record = _record()
    assert PanelModelRecord.from_dict(record.to_dict()) == record


def test_unset_numeric_fields_round_trip_as_none():
    record = _record(vmp=None, imp=None)
    data = record.to_dict()
    assert data["vmp"] is None
    assert data["imp"] is None
    assert PanelModelRecord.from_dict(data).vmp is None


def test_from_dict_rejects_unknown_schema():
    data = _record().to_dict()
    data["schema"] = 2
    with pytest.raises(ValueError, match="schema"):
        PanelModelRecord.from_dict(data)


def test_from_dict_rejects_missing_name():
    data = _record().to_dict()
    del data["name"]
    with pytest.raises(ValueError, match="name"):
        PanelModelRecord.from_dict(data)


def test_validate_rejects_empty_id():
    with pytest.raises(ValueError, match="id"):
        _record(id="  ").validate()


def test_validate_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        _record(name="").validate()


@pytest.mark.parametrize("field_name", ["p_max_w", "voc", "isc", "vmp", "imp"])
@pytest.mark.parametrize("bad_value", [0.0, -1.0, float("nan"), float("inf")])
def test_validate_rejects_non_finite_or_non_positive_numbers(field_name, bad_value):
    with pytest.raises(ValueError, match=field_name):
        _record(**{field_name: bad_value}).validate()


def test_validate_accepts_a_positive_finite_number():
    _record(vmp=19.5, imp=0.51).validate()  # must not raise


@pytest.mark.parametrize(
    ("field_name", "limit"),
    [
        ("id", 200),
        ("name", 200),
        ("manufacturer", 200),
        ("model", 200),
        ("notes", 2000),
    ],
)
def test_validate_rejects_an_oversized_string_field(field_name, limit):
    with pytest.raises(ValueError, match=field_name):
        _record(**{field_name: "x" * (limit + 1)}).validate()


def test_validate_accepts_a_string_field_at_the_limit():
    _record(name="x" * 200).validate()  # must not raise


# ------------------------------------------------------------------
# library.create / save
# ------------------------------------------------------------------


def test_create_mints_an_id_from_the_name_and_persists_it(tmp_path):
    record = panel_library.create("Luxen LN-10P", p_max_w=10.0, directory=tmp_path)
    assert record.id == "luxen-ln-10p"
    assert (tmp_path / "luxen-ln-10p.json").exists()


def test_create_on_collision_appends_a_suffix_to_the_id(tmp_path):
    first = panel_library.create("Luxen LN-10P", directory=tmp_path)
    second = panel_library.create("Luxen LN-10P", directory=tmp_path)
    assert first.id != second.id
    assert second.id == "luxen-ln-10p-2"


def test_create_rejects_an_invalid_field(tmp_path):
    with pytest.raises(ValueError, match="voc"):
        panel_library.create("Bad panel", voc=-1.0, directory=tmp_path)


def test_save_uses_exclusive_create_and_does_not_overwrite(tmp_path):
    record = _record()
    panel_library.save(record, tmp_path)
    second, path = panel_library.save(record, tmp_path)
    assert second.id == "luxen-ln-10p-2"
    assert path.name == "luxen-ln-10p-2.json"
    # The original file is untouched.
    assert panel_library.load(tmp_path / "luxen-ln-10p.json") == record


# ------------------------------------------------------------------
# Round trip / parse errors
# ------------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path):
    record = _record()
    _saved, path = panel_library.save(record, tmp_path)
    assert panel_library.load(path) == record


def test_load_rejects_not_valid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        panel_library.load(path)


def test_load_rejects_missing_field(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    del data["name"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="name"):
        panel_library.load(path)


def test_load_rejects_an_invalid_value_written_by_hand(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    data["voc"] = -5.0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="voc"):
        panel_library.load(path)


# ------------------------------------------------------------------
# update (atomic save-in-place)
# ------------------------------------------------------------------


def test_update_overwrites_the_existing_file_in_place(tmp_path):
    record = _record()
    _saved, path = panel_library.save(record, tmp_path)

    updated = PanelModelRecord(
        id=record.id,
        name=record.name,
        manufacturer=record.manufacturer,
        model=record.model,
        p_max_w=record.p_max_w,
        voc=23.7,  # corrected after a bench re-check
        isc=record.isc,
        vmp=record.vmp,
        imp=record.imp,
        notes=record.notes,
    )
    returned_path = panel_library.update(updated, directory=tmp_path)
    assert returned_path == path
    assert panel_library.load(path).voc == 23.7


def test_update_leaves_no_temp_file_behind(tmp_path):
    record = _record()
    panel_library.save(record, tmp_path)
    panel_library.update(record, directory=tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {f"{record.id}.json"}


def test_update_of_a_panel_with_no_existing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        panel_library.update(_record(), directory=tmp_path)


def test_update_rejects_an_invalid_change(tmp_path):
    record = _record()
    panel_library.save(record, tmp_path)
    bad = PanelModelRecord(
        id=record.id,
        name=record.name,
        manufacturer=record.manufacturer,
        model=record.model,
        p_max_w=record.p_max_w,
        voc=-1.0,
        isc=record.isc,
        vmp=record.vmp,
        imp=record.imp,
        notes=record.notes,
    )
    with pytest.raises(ValueError, match="voc"):
        panel_library.update(bad, directory=tmp_path)
    # The file on disk was never touched.
    assert panel_library.load(tmp_path / f"{record.id}.json").voc == record.voc


# ------------------------------------------------------------------
# delete
# ------------------------------------------------------------------


def test_delete_removes_the_file_and_returns_true(tmp_path):
    _saved, path = panel_library.save(_record(), tmp_path)
    assert panel_library.delete(path, tmp_path) is True
    assert not path.exists()


def test_delete_of_an_already_gone_file_is_a_no_op_returning_false(tmp_path):
    _saved, path = panel_library.save(_record(), tmp_path)
    path.unlink()
    assert panel_library.delete(path, tmp_path) is False


def test_delete_refuses_a_path_outside_the_library_directory(tmp_path):
    outside = tmp_path.parent / "not-a-panel.json"
    outside.write_text("{}")
    try:
        with pytest.raises(ValueError, match="outside"):
            panel_library.delete(outside, tmp_path)
        assert outside.exists()
    finally:
        outside.unlink()


# ------------------------------------------------------------------
# load_all
# ------------------------------------------------------------------


def test_load_all_returns_every_record(tmp_path):
    panel_library.save(_record(id="a", name="A"), tmp_path)
    panel_library.save(_record(id="b", name="B"), tmp_path)
    records = panel_library.load_all(tmp_path)
    assert {r.id for r in records} == {"a", "b"}


def test_load_all_on_missing_directory_returns_empty_list(tmp_path):
    assert panel_library.load_all(tmp_path / "does-not-exist") == []


# ------------------------------------------------------------------
# Shipped defaults
# ------------------------------------------------------------------


def test_list_default_panels_returns_luxen_and_hissuma():
    ids = {p.id for p in list_default_panels()}
    assert ids == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_luxen_default_matches_its_label():
    luxen = next(p for p in list_default_panels() if p.id == "luxen-ln-10p")
    assert luxen.p_max_w == 10.0
    assert luxen.voc == 23.5
    assert luxen.isc == 0.57
    assert luxen.vmp == 18.6
    assert luxen.imp == 0.54
    # The label's own cross-check: Vmp x Imp is its rated power.
    assert luxen.vmp * luxen.imp == pytest.approx(luxen.p_max_w, rel=0.01)


def test_luxen_notes_say_what_the_label_values_are_and_why_it_reads_high():
    luxen = next(p for p in list_default_panels() if p.id == "luxen-ln-10p")
    assert "STC" in luxen.notes
    assert "1000 W/m2" in luxen.notes
    assert "0 to +3 W" in luxen.notes
    assert "not on hand" not in luxen.notes


def test_hissuma_default_carries_vmp_and_imp_from_the_harness_config():
    hissuma = next(p for p in list_default_panels() if p.id == "hissuma-psf10mono")
    assert hissuma.p_max_w == 10.0
    assert hissuma.voc == 17.0
    assert hissuma.isc == 0.79
    assert hissuma.vmp == 14.0
    assert hissuma.imp == 0.72


def test_default_panels_all_validate():
    for record in list_default_panels():
        record.validate()  # must not raise


def test_ensure_defaults_seeded_writes_both_defaults_once(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    ids = {r.id for r in panel_library.load_all(tmp_path)}
    assert ids == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_ensure_defaults_seeded_does_not_overwrite_an_edited_shipped_panel(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    edited = panel_library.load(tmp_path / "luxen-ln-10p.json")
    edited = PanelModelRecord(
        id=edited.id,
        name=edited.name,
        manufacturer=edited.manufacturer,
        model=edited.model,
        p_max_w=edited.p_max_w,
        voc=23.9,  # operator corrected it after a bench check
        isc=edited.isc,
        vmp=edited.vmp,
        imp=edited.imp,
        notes=edited.notes,
    )
    panel_library.update(edited, directory=tmp_path)

    # A second seeding call (e.g. the next server restart) must not
    # clobber the edit.
    panel_library.ensure_defaults_seeded(tmp_path)
    assert panel_library.load(tmp_path / "luxen-ln-10p.json").voc == 23.9


def test_ensure_defaults_seeded_is_idempotent_on_an_empty_directory(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    panel_library.ensure_defaults_seeded(tmp_path)
    ids = [r.id for r in panel_library.load_all(tmp_path)]
    assert sorted(ids) == sorted(set(ids))


def test_an_unset_number_is_saved_as_null_and_loads_back_unset(tmp_path):
    record = panel_library.create("Bare panel", voc=21.0, directory=tmp_path)
    on_disk = json.loads((tmp_path / f"{record.id}.json").read_text())
    assert on_disk["vmp"] is None
    assert on_disk["imp"] is None
    loaded = panel_library.load(tmp_path / f"{record.id}.json")
    assert (loaded.vmp, loaded.imp) == (None, None)


# ------------------------------------------------------------------
# Seeding: a delete sticks, a new shipped id arrives, faults are isolated
# ------------------------------------------------------------------

_MARKER = ".seeded-defaults"


def _seeded_ids(directory):
    return set(json.loads((directory / _MARKER).read_text())["seeded"])


def _extra_default() -> PanelModelRecord:
    return PanelModelRecord(id="acme-a-1", name="Acme A-1", p_max_w=20.0, voc=40.0)


def test_seeding_records_which_shipped_ids_it_has_seeded(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    assert _seeded_ids(tmp_path) == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_the_marker_is_never_listed_as_a_panel_model(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    assert (tmp_path / _MARKER).exists()
    assert {r.id for r in panel_library.load_all(tmp_path)} == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_a_deleted_shipped_panel_stays_deleted_across_restarts(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    panel_library.delete(tmp_path / "luxen-ln-10p.json", tmp_path)

    # Every later server start calls this again.
    panel_library.ensure_defaults_seeded(tmp_path)
    panel_library.ensure_defaults_seeded(tmp_path)

    assert not (tmp_path / "luxen-ln-10p.json").exists()
    assert {r.id for r in panel_library.load_all(tmp_path)} == {"hissuma-psf10mono"}


def test_delete_leaves_the_seeded_record_alone(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    panel_library.delete(tmp_path / "luxen-ln-10p.json", tmp_path)
    assert _seeded_ids(tmp_path) == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_a_newly_shipped_panel_still_arrives_after_an_upgrade(tmp_path, monkeypatch):
    panel_library.ensure_defaults_seeded(tmp_path)
    panel_library.delete(tmp_path / "luxen-ln-10p.json", tmp_path)

    # A later SDK version ships one more panel model.
    monkeypatch.setattr(
        panel_library, "list_default_panels", lambda: [*list_default_panels(), _extra_default()]
    )
    panel_library.ensure_defaults_seeded(tmp_path)

    assert (tmp_path / "acme-a-1.json").exists()
    assert _seeded_ids(tmp_path) == {"luxen-ln-10p", "hissuma-psf10mono", "acme-a-1"}
    # The upgrade does not resurrect the one that was deleted.
    assert not (tmp_path / "luxen-ln-10p.json").exists()


def test_a_directory_from_before_the_marker_is_recorded_not_rewritten(tmp_path):
    # Files seeded by an earlier version, edited by the operator, no marker.
    panel_library.ensure_defaults_seeded(tmp_path)
    (tmp_path / _MARKER).unlink()
    luxen = panel_library.load(tmp_path / "luxen-ln-10p.json")
    panel_library.update(replace(luxen, voc=23.9), directory=tmp_path)

    panel_library.ensure_defaults_seeded(tmp_path)

    assert panel_library.load(tmp_path / "luxen-ln-10p.json").voc == 23.9
    assert _seeded_ids(tmp_path) == {"luxen-ln-10p", "hissuma-psf10mono"}


@pytest.mark.parametrize(
    "garbage",
    [
        b"not json at all",
        b"",
        b"[]",
        b'{"seeded": "luxen-ln-10p"}',
        b'{"seeded": [1, null, {"a": 1}]}',
        b'{"schema": 1}',
        b"\xff\xfe\x00",
    ],
)
def test_a_malformed_marker_does_not_fail_or_overwrite_an_edit(tmp_path, garbage):
    panel_library.ensure_defaults_seeded(tmp_path)
    luxen = panel_library.load(tmp_path / "luxen-ln-10p.json")
    panel_library.update(replace(luxen, voc=23.9), directory=tmp_path)
    (tmp_path / _MARKER).write_bytes(garbage)

    panel_library.ensure_defaults_seeded(tmp_path)  # must not raise

    assert panel_library.load(tmp_path / "luxen-ln-10p.json").voc == 23.9
    # The marker is repaired for the next start.
    assert _seeded_ids(tmp_path) == {"luxen-ln-10p", "hissuma-psf10mono"}


def test_a_marker_that_cannot_be_written_does_not_stop_startup(tmp_path, caplog):
    (tmp_path / _MARKER).mkdir()  # cannot be read as, or replaced by, a file
    with caplog.at_level("WARNING", logger="mpp_sdk.panels.library"):
        panel_library.ensure_defaults_seeded(tmp_path)  # must not raise
    assert (tmp_path / "luxen-ln-10p.json").exists()
    assert any("could not record" in r.getMessage() for r in caplog.records)


def test_seeding_leaves_no_temp_file_behind(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {
        "luxen-ln-10p.json",
        "hissuma-psf10mono.json",
        _MARKER,
    }


def test_a_custom_panel_named_like_a_seeded_default_gets_its_own_id(tmp_path):
    panel_library.ensure_defaults_seeded(tmp_path)
    shipped = panel_library.load(tmp_path / "luxen-ln-10p.json")

    custom = panel_library.create("Luxen LN-10P", voc=99.0, directory=tmp_path)

    assert custom.id == "luxen-ln-10p-2"
    assert (tmp_path / "luxen-ln-10p-2.json").exists()
    # The shipped one is untouched.
    assert panel_library.load(tmp_path / "luxen-ln-10p.json") == shipped


# A stand-in for the packaged defaults directory: one good file next to
# every kind of broken one a hand edit or a bad merge could leave behind.
def _fake_defaults_dir(tmp_path, monkeypatch):
    from mpp_sdk.panels import defaults as panel_defaults

    fake = tmp_path / "shipped"
    fake.mkdir()
    good = json.dumps(_extra_default().to_dict())
    (fake / "good.json").write_text(good)
    (fake / "broken-json.json").write_text("{not json")
    (fake / "not-an-object.json").write_text("[1, 2]")
    (fake / "bad-schema.json").write_text(json.dumps({**_extra_default().to_dict(), "schema": 9}))
    (fake / "negative-voc.json").write_text(
        json.dumps({**_extra_default().to_dict(), "id": "neg", "voc": -1.0})
    )
    (fake / "missing-name.json").write_text(json.dumps({"schema": 1, "id": "x"}))
    (fake / "bad-utf8.json").write_bytes(b"\xff\xfe\x00")
    (fake / "readme.txt").write_text("ignored, not a .json")
    monkeypatch.setattr(panel_defaults, "_defaults_dir", lambda: fake)
    return fake


def test_a_malformed_shipped_default_is_skipped_and_logged(tmp_path, monkeypatch, caplog):
    _fake_defaults_dir(tmp_path, monkeypatch)
    with caplog.at_level("WARNING", logger="mpp_sdk.panels.defaults"):
        records = list_default_panels()  # must not raise
    assert [r.id for r in records] == ["acme-a-1"]
    skipped = {rec.args[0] for rec in caplog.records}
    assert skipped == {
        "broken-json.json",
        "not-an-object.json",
        "bad-schema.json",
        "negative-voc.json",
        "missing-name.json",
        "bad-utf8.json",
    }


def test_seeding_survives_a_malformed_shipped_default(tmp_path, monkeypatch):
    _fake_defaults_dir(tmp_path, monkeypatch)
    library = tmp_path / "library"
    panel_library.ensure_defaults_seeded(library)  # must not raise
    assert {r.id for r in panel_library.load_all(library)} == {"acme-a-1"}
    # Only what was actually seeded is recorded, so a repaired file
    # arrives on the next start.
    assert _seeded_ids(library) == {"acme-a-1"}


def test_a_shipped_default_fixed_later_still_arrives(tmp_path, monkeypatch):
    fake = _fake_defaults_dir(tmp_path, monkeypatch)
    library = tmp_path / "library"
    panel_library.ensure_defaults_seeded(library)

    fixed = {**_extra_default().to_dict(), "id": "fixed-one", "name": "Fixed one"}
    (fake / "broken-json.json").write_text(json.dumps(fixed))
    panel_library.ensure_defaults_seeded(library)

    assert "fixed-one" in {r.id for r in panel_library.load_all(library)}


def test_shipped_defaults_load_from_a_built_wheel(tmp_path):
    """`mpp_sdk/panels/defaults/*.json` must actually ship inside the
    wheel (pyproject.toml's artifacts list), not just be readable off a
    checkout - build one and install it into a throwaway venv (both via
    `uv`, already this project's own build/dev tool - a stdlib `pip`
    install would also need `numpy`/`matplotlib`, mpp_sdk's base
    dependencies, resolved from network, which a sandboxed test run may
    not have), and read the defaults back from there."""
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH - cannot build a wheel to check")
    repo_root = panel_library._REPO_ROOT
    build_dir = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(build_dir), str(repo_root)],
        check=True,
        capture_output=True,
    )
    wheels = list(build_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels

    venv_dir = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", "--python", "3.14", str(venv_dir)], check=True, capture_output=True
    )
    venv_python = venv_dir / "bin" / "python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from mpp_sdk.panels import list_default_panels; "
            "print(sorted(p.id for p in list_default_panels()))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "hissuma-psf10mono" in result.stdout
    assert "luxen-ln-10p" in result.stdout
