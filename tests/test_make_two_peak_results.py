"""`scripts/make_two_peak_results.py` runs on a tiny input and is deterministic."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from scripts import make_two_peak_results as m  # noqa: E402

CURVES = m.CURVES[:1]


def test_tiny_run_is_deterministic_and_reports_all_algorithms():
    a = m.evaluate(CURVES, n_steps=50, starts=(0.5,))
    b = m.evaluate(CURVES, n_steps=50, starts=(0.5,))
    assert a == b
    assert len(a) == 5
    assert all(r["n_peaks"] == 2 for r in a)


def test_main_writes_table_and_png(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CURVES", CURVES)
    monkeypatch.setattr(m, "START_DUTIES", (0.5,))
    monkeypatch.setattr(m, "N_STEPS", 50)
    m.main(["--out-dir", str(tmp_path)])
    assert (tmp_path / "two_peak_compare.png").stat().st_size > 0
    assert "| P&O |" in (tmp_path / "two_peak_table.md").read_text()
