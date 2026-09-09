"""Unit tests for `mpp_sdk.runs`: `library.py`'s save/load round-trip.
Pure stdlib, no hardware - every test uses `tmp_path` as the library
directory, mirroring `tests/test_curve_library.py`.
"""

import json
from datetime import UTC, datetime

import pytest

from mpp_sdk.runs import RunRecord, RunSample, load, load_all, save

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
