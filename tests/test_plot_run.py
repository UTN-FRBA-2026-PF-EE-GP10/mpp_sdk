"""`scripts/plot_run.py`'s lookup of a run's paired curve."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from scripts.plot_run import _find_curve  # noqa: E402


@pytest.fixture
def curve_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MPP_SDK_CURVE_DIR", str(tmp_path))
    return tmp_path


def test_finds_a_curve_by_file_name_as_the_cli_saves_it(curve_dir):
    (curve_dir / "20260913T080000Z-flat.json").write_text("{}")
    assert (
        _find_curve("20260913T080000Z-flat.json")
        == (curve_dir / "20260913T080000Z-flat.json").resolve()
    )


def test_finds_a_curve_by_bare_id_as_the_web_server_saves_it(curve_dir):
    (curve_dir / "20260913T080000Z-flat.json").write_text("{}")
    assert _find_curve("20260913T080000Z-flat") is not None


@pytest.mark.parametrize("ref", [None, "demo-fixture-psf10-bright", "deleted-curve", "..", "."])
def test_is_none_when_the_ref_names_no_library_file(curve_dir, ref):
    """A demo label, a deleted curve or a dot segment must not crash the
    plot - it just has no curve to draw."""
    assert _find_curve(ref) is None


def test_never_leaves_the_curve_directory(curve_dir):
    outside = curve_dir.parent / "outside.json"
    outside.write_text("{}")
    assert _find_curve("../outside.json") is None
