"""`scripts/make_two_peak_results.py`: numbers on the B 60 curve, determinism, peak detection."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from mpp_sdk.curves import library  # noqa: E402
from scripts import make_two_peak_results as m  # noqa: E402

CURVES = m.CURVES[:1]  # 10 Ohm, B 60: peaks 4.75 W at 13.8 V and 6.35 W at 30.4 V


@pytest.fixture(scope="module")
def rows():
    return {r["algorithm"]: r for r in m.evaluate(CURVES, n_steps=2000, starts=(0.5,))}


def test_is_deterministic():
    a = m.evaluate(CURVES, n_steps=200, starts=(0.5,))
    assert a == m.evaluate(CURVES, n_steps=200, starts=(0.5,))
    assert len(a) == 5


def test_global_peak_and_peak_count(rows):
    assert all(r["n_peaks"] == 2 for r in rows.values())
    assert rows["P&O"]["p_mpp"] == pytest.approx(6.35, abs=0.05)


def test_local_trackers_get_stuck_on_the_small_peak(rows):
    for name in ("P&O", "InCond", "Fuzzy"):
        assert rows[name]["eta"] == pytest.approx(0.746, abs=0.01)
        assert rows[name]["found"] is False
    assert 50 < rows["P&O"]["steps"] < 150  # settles, but not at step 0 and not never


def test_global_trackers_find_the_big_peak(rows):
    for name in ("Scan&Track", "PSO"):
        assert rows[name]["eta"] > 0.95
        assert rows[name]["found"] is True
        assert rows[name]["steps"] > 1900  # keeps moving: never settles within 1 %


def test_peaks_come_from_samples_not_from_interpolation():
    record = library.load(m.CURVES[1][1])  # B 30: one sample at the edge of a wide gap
    peaks = m.local_maxima(record)
    assert [round(v, 1) for v, _ in peaks] == [13.7, 32.5]
    assert all(abs(v - 25.4) > 1.0 for v, _ in peaks)
    assert m.largest_gap(record) == pytest.approx((16.266, 32.541))


def test_main_writes_table_and_png(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CURVES", CURVES)
    monkeypatch.setattr(m, "START_DUTIES", (0.5,))
    monkeypatch.setattr(m, "N_STEPS", 50)
    m.main(["--out-dir", str(tmp_path)])
    assert (tmp_path / "two_peak_compare.png").stat().st_size > 0
    assert "| P&O |" in (tmp_path / "two_peak_table.md").read_text()
