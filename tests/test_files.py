"""Tests for `mpp_sdk._files`, the write and read helpers shared by the
curve, run, session and panel libraries."""

import json

import pytest

from mpp_sdk._files import read_json_object, write_new


def test_write_new_writes_the_body(tmp_path):
    path = write_new(tmp_path, "rec", '{"a": 1}\n')
    assert path == tmp_path / "rec.json"
    assert json.loads(path.read_text()) == {"a": 1}


def test_write_new_never_overwrites_and_adds_a_suffix(tmp_path):
    first = write_new(tmp_path, "rec", '{"n": 1}\n')
    second = write_new(tmp_path, "rec", '{"n": 2}\n')
    third = write_new(tmp_path, "rec", '{"n": 3}\n')
    assert [p.name for p in (first, second, third)] == ["rec.json", "rec-2.json", "rec-3.json"]
    assert json.loads(first.read_text()) == {"n": 1}


def test_write_new_leaves_no_temp_file_behind(tmp_path):
    write_new(tmp_path, "rec", "{}\n")
    write_new(tmp_path, "rec", "{}\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec-2.json", "rec.json"]


def test_write_new_creates_the_directory(tmp_path):
    path = write_new(tmp_path / "new", "rec", "{}\n")
    assert path.exists()


def test_read_json_object_returns_the_object(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}')
    assert read_json_object(path) == {"a": 1}


@pytest.mark.parametrize("text", ["[]", "null", "3", '"s"'])
def test_read_json_object_rejects_a_non_object(tmp_path, text):
    path = tmp_path / "x.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="expected a JSON object"):
        read_json_object(path)


def test_read_json_object_rejects_invalid_json(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_json_object(path)
