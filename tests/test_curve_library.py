"""Unit tests for `mpp_sdk.curves`: `CurveRecord`'s derived quantities and
`library.py`'s save/load round-trip. Pure stdlib, no hardware, no network -
every test uses `tmp_path` as the library directory.
"""

import json
from datetime import UTC, datetime

import pytest

from mpp_sdk.curves import CurveRecord, PanelSetup, group_by_measurement, load, load_all, save

_CAPTURED_AT = datetime(2026, 8, 26, 21, 14, 3, tzinfo=UTC)


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
    save(_record(label="two", measurement="partial-shade"), tmp_path)
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
