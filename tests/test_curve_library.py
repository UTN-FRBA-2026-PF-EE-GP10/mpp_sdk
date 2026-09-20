"""Unit tests for `mpp_sdk.curves`: `CurveRecord`'s derived quantities and
`library.py`'s save/load round-trip. Pure stdlib, no hardware, no network -
every test uses `tmp_path` as the library directory.
"""

import json
from datetime import UTC, datetime

import pytest

from mpp_sdk.curves import (
    MEASUREMENT_KINDS,
    CurveRecord,
    PanelSetup,
    delete,
    group_by_measurement,
    load,
    load_all,
    save,
)
from mpp_sdk.curves.record import now_utc

_CAPTURED_AT = datetime(2026, 8, 26, 21, 14, 3, tzinfo=UTC)


def test_measurement_kinds_is_pinned():
    # A rename here is a breaking change for saved data and the frontend's
    # vocabulary - pin the tuple so a future rename is a deliberate edit to
    # this test, not a silent side effect of touching record.py.
    assert MEASUREMENT_KINDS == ("baseline", "tilted", "dimmed", "other")


def _record(**overrides) -> CurveRecord:
    fields = {
        "captured_at": _CAPTURED_AT,
        "label": "both panels flat, lamp at 30cm",
        "measurement": "baseline",
        "panels": (PanelSetup(id="A", tilt_deg=0), PanelSetup(id="B", tilt_deg=0)),
        "points": ((21.33, 0.006), (18.0, 0.195), (0.5, 0.205)),
    }
    fields.update(overrides)
    return CurveRecord(**fields)


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
    assert path.name == "20260826T211403Z-both-panels-flat-lamp-at-30cm.json"


# ------------------------------------------------------------------
# Derived quantities
# ------------------------------------------------------------------


def test_open_circuit_voltage_is_largest_measured_voltage():
    assert _record().open_circuit_voltage == 21.33


def test_short_circuit_current_is_largest_measured_current():
    assert _record().short_circuit_current == 0.205


def test_mpp_is_the_point_of_maximum_power():
    # (18.0, 0.195) -> 3.51 W is the largest of the three points' V*I.
    v, i, p = _record().mpp()
    assert (v, i) == (18.0, 0.195)
    assert p == pytest.approx(18.0 * 0.195)


# ------------------------------------------------------------------
# Filename collisions
# ------------------------------------------------------------------


def test_save_on_collision_appends_suffix_instead_of_overwriting(tmp_path):
    first = save(_record(label="dup"), tmp_path)
    second = save(_record(label="dup"), tmp_path)
    assert first != second
    assert first.exists()
    assert second.exists()
    assert load(first).points == load(second).points


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


def test_load_rejects_missing_points_field(tmp_path):
    path = tmp_path / "bad.json"
    data = _record().to_dict()
    del data["points"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="points"):
        load(path)


# ------------------------------------------------------------------
# load_all / group_by_measurement
# ------------------------------------------------------------------


def test_load_all_returns_every_record_in_directory(tmp_path):
    save(_record(label="one", measurement="baseline"), tmp_path)
    save(_record(label="two", measurement="tilted"), tmp_path)
    records = load_all(tmp_path)
    assert {r.label for r in records} == {"one", "two"}


def test_load_all_on_missing_directory_returns_empty_list(tmp_path):
    assert load_all(tmp_path / "does-not-exist") == []


def test_group_by_measurement_buckets_by_kind_including_unknown(tmp_path):
    records = [
        _record(label="a", measurement="baseline"),
        _record(label="b", measurement="baseline"),
        _record(label="c", measurement="a-typo-not-in-the-vocabulary"),
    ]
    groups = group_by_measurement(records)
    assert {r.label for r in groups["baseline"]} == {"a", "b"}
    assert [r.label for r in groups["a-typo-not-in-the-vocabulary"]] == ["c"]


def test_source_round_trips_and_defaults_to_unknown(tmp_path):
    """Provenance must survive save/load, and a record that never stated
    it must read back as "unknown" rather than silently claiming to be a
    measurement - see CURVE_SOURCES."""
    replayed = CurveRecord(
        captured_at=now_utc(),
        label="replayed",
        measurement="baseline",
        panels=(),
        points=((19.3, 0.006), (13.9, 0.555)),
        source="firmware-replay",
    )
    assert load(save(replayed, directory=tmp_path)).source == "firmware-replay"

    unstated = CurveRecord(
        captured_at=now_utc(),
        label="unstated",
        measurement="baseline",
        panels=(),
        points=((19.3, 0.006),),
    )
    assert unstated.source == "unknown"
    assert load(save(unstated, directory=tmp_path)).source == "unknown"


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
    outside = tmp_path.parent / "not-a-curve.json"
    outside.write_text("{}")
    try:
        with pytest.raises(ValueError, match="outside"):
            delete(outside, tmp_path)
        assert outside.exists()
    finally:
        outside.unlink()


def test_a_file_written_before_source_existed_loads_as_unknown(tmp_path):
    record = CurveRecord(
        captured_at=now_utc(),
        label="old",
        measurement="baseline",
        panels=(),
        points=((19.3, 0.006),),
        source="hardware",
    )
    path = save(record, directory=tmp_path)
    payload = json.loads(path.read_text())
    del payload["source"]
    path.write_text(json.dumps(payload))

    assert load(path).source == "unknown"


# ------------------------------------------------------------------
# session_id
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
    path = save(_record(), directory=tmp_path)
    payload = json.loads(path.read_text())
    del payload["session_id"]
    path.write_text(json.dumps(payload))

    assert load(path).session_id is None
