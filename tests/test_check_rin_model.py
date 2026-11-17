"""`scripts/check_rin_model.py` on a tiny synthetic CSV."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from scripts import check_rin_model as m  # noqa: E402

CSV = """duty,v_in,i_in,v_out_adc,v_out_meter,n,load_ohms
0.0,5.0,0.0,0.0,,10,10.0
0.5,5.0,0.5,5.0,,10,10.0
0.25,5.0,0.1,1.7,,10,10.0
"""


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "duty.csv"
    p.write_text(CSV)
    return p


def test_ideal_point_has_zero_error_and_zero_duty_is_skipped(csv_path):
    res = m.evaluate(m.load_points([csv_path]))
    assert [r["duty"] for r in res] == [0.25, 0.5]
    half = res[1]
    assert half["measured"] == pytest.approx(10.0)
    assert half["ideal"] == pytest.approx(10.0)
    assert half["model"] == pytest.approx(10.0)
    assert half["err"] == pytest.approx(0.0)
    assert res[0]["ideal"] == pytest.approx(90.0)
    assert res[0]["measured"] == pytest.approx(50.0)


def test_summary_reports_the_ok_range(csv_path):
    res = m.evaluate(m.load_points([csv_path]))
    assert "D 0.50 to 0.50" in m.summarize(res)


def test_main_writes_plot_only_when_asked(csv_path, tmp_path, capsys):
    m.main([str(csv_path)])
    assert not list(tmp_path.glob("*.png"))
    out = tmp_path / "p.png"
    m.main([str(csv_path), "--plot", str(out)])
    assert out.stat().st_size > 0
    assert "relative error" in capsys.readouterr().out
