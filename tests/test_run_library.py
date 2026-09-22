"""Unit tests for `mpp_sdk.runs`: `library.py`'s save/load round-trip.
Pure stdlib, no hardware - every test uses `tmp_path` as the library
directory, mirroring `tests/test_curve_library.py`.
"""

import json
from datetime import UTC, datetime

import pytest

from mpp_sdk.runs import RunRecord, RunSample, delete, load, load_all, save

_CAPTURED_AT = datetime(2026, 9, 8, 21, 14, 3, tzinfo=UTC)


def _record(**overrides) -> RunRecord:
    fields = {
        "captured_at": _CAPTURED_AT,
        "label": "bench check",
        "algorithm": "P&O",
        "samples": (
            RunSample(t=0.0, voltage=20.0, current=0.05, duty=0.5),
            RunSample(t=0.1, voltage=18.0, current=0.1, duty=0.55),
        ),
        "curve_ref": "20260908T120000Z-baseline.json",
        "aborted": False,
        "notes": "",
    }
    fields.update(overrides)
    return RunRecord(**fields)


# ------------------------------------------------------------------
# Round-trip
# ------------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path):
    record = _record()
    path = save(record, tmp_path)
    loaded = load(path)
    assert loaded == record


def test_save_names_file_from_captured_at_and_slug(tmp_path):
    path = save(_record(), tmp_path)
    assert path.name == "20260908T211403Z-bench-check.json"


# ------------------------------------------------------------------
# Filename collisions
# ------------------------------------------------------------------


def test_save_on_collision_appends_suffix_instead_of_overwriting(tmp_path):
    first = save(_record(label="dup"), tmp_path)
    second = save(_record(label="dup"), tmp_path)
    assert first != second
    assert first.exists()
    assert second.exists()
    assert load(first).samples == load(second).samples


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


def test_load_rejects_missing_samples_field(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    del data["samples"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="samples"):
        load(path)


# ------------------------------------------------------------------
# load_all
# ------------------------------------------------------------------


def test_load_all_returns_every_record_in_directory(tmp_path):
    save(_record(label="one"), tmp_path)
    save(_record(label="two"), tmp_path)
    records = load_all(tmp_path)
    assert {r.label for r in records} == {"one", "two"}


def test_load_all_on_missing_directory_returns_empty_list(tmp_path):
    assert load_all(tmp_path / "does-not-exist") == []


# ------------------------------------------------------------------
# delete
# ------------------------------------------------------------------


def test_delete_removes_the_file_and_returns_true(tmp_path):
    path = save(_record(), tmp_path)
    assert delete(path, tmp_path) is True
    assert not path.exists()


def test_delete_of_an_already_gone_file_is_a_no_op_returning_false(tmp_path):
    """Deleting is idempotent: a UI's delete button firing twice, or a
    stale listing, must not surface as an error - see library.delete's
    docstring for the reasoning."""
    path = save(_record(), tmp_path)
    path.unlink()
    assert delete(path, tmp_path) is False


def test_delete_refuses_a_path_outside_the_library_directory(tmp_path):
    outside = tmp_path.parent / "not-a-run.json"
    outside.write_text("{}")
    try:
        with pytest.raises(ValueError, match="outside"):
            delete(outside, tmp_path)
        assert outside.exists()
    finally:
        outside.unlink()


# ------------------------------------------------------------------
# source (provenance) - mirrors test_curve_library.py's own tests
# ------------------------------------------------------------------


def test_source_round_trips_and_defaults_to_unknown(tmp_path):
    """Provenance must survive save/load, and a record that never stated
    it must read back as "unknown" rather than silently claiming to have
    driven real hardware - see RUN_SOURCES."""
    simulated = _record(label="simulated", source="simulated")
    assert load(save(simulated, tmp_path)).source == "simulated"

    unstated = _record(label="unstated")
    assert unstated.source == "unknown"
    assert load(save(unstated, tmp_path)).source == "unknown"


def test_a_file_written_before_source_existed_loads_as_unknown(tmp_path):
    path = save(_record(source="hardware"), tmp_path)
    payload = json.loads(path.read_text())
    del payload["source"]
    path.write_text(json.dumps(payload))

    assert load(path).source == "unknown"


# ------------------------------------------------------------------
# session_id - mirrors test_curve_library.py's own tests
# ------------------------------------------------------------------


def test_session_id_round_trips(tmp_path):
    record = _record(session_id="20260101T000000Z-a-session")
    loaded = load(save(record, tmp_path))
    assert loaded.session_id == "20260101T000000Z-a-session"


def test_session_id_defaults_to_none(tmp_path):
    record = _record()
    assert record.session_id is None
    assert load(save(record, tmp_path)).session_id is None


def test_a_file_written_before_session_id_existed_loads_with_none(tmp_path):
    """A file saved before this field existed has no "session_id" key at
    all (not even null) - same "absent, not stated" case as `source`
    above (test_a_file_written_before_source_existed_loads_as_unknown)."""
    path = save(_record(), tmp_path)
    payload = json.loads(path.read_text())
    del payload["session_id"]
    path.write_text(json.dumps(payload))

    assert load(path).session_id is None


@pytest.mark.parametrize("bad", [42, 1.5, True, ["a"], {"id": "a"}])
def test_a_session_id_that_is_not_a_string_or_null_is_rejected(tmp_path, bad):
    """Same rule as the curve record's - see test_curve_library.py."""
    path = save(_record(), tmp_path)
    payload = json.loads(path.read_text())
    payload["session_id"] = bad
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="session_id"):
        load(path)
