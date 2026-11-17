"""`scripts/check_rin_model.py` on a tiny synthetic CSV."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from scripts import check_rin_model as m  # noqa: E402

# D 0.5: ideal 10 Ohm, measured 10 (err 0). D 0.25: ideal 90, measured 50 (err +0.8, outside).
# D 0.4: ideal 22.5, measured 23.5 (err -0.043, inside). D 0.3: ideal 54.44, measured 80 (err -0.32, outside).
CSV = """duty,v_in,i_in,v_out_adc,v_out_meter,n,load_ohms
0.0,5.0,0.0,0.0,,10,10.0
0.5,5.0,0.5,5.0,,10,10.0
0.25,5.0,0.1,1.7,,10,10.0
0.4,4.7,0.2,2.0,,10,10.0
0.3,4.0,0.05,1.0,,10,10.0
"""


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "duty.csv"
    p.write_text(CSV)
    return p


def test_exact_values_and_zero_duty_is_skipped(csv_path):
    res = m.evaluate(m.load_points([csv_path]))
    assert [r["duty"] for r in res] == [0.25, 0.3, 0.4, 0.5]
    quarter, thirty, forty, half = res
    assert half["measured"] == pytest.approx(10.0)
    assert half["model"] == pytest.approx(10.0)
    assert half["err"] == pytest.approx(0.0)
    assert quarter["measured"] == pytest.approx(50.0)
    assert quarter["ideal"] == pytest.approx(90.0)
    assert quarter["err"] == pytest.approx(0.8)  # (90 - 50) / 50
    assert forty["measured"] == pytest.approx(23.5)
    assert forty["err"] == pytest.approx(-1.0 / 23.5)
    assert thirty["measured"] == pytest.approx(80.0)
    assert thirty["err"] == pytest.approx((54.4444444 - 80.0) / 80.0)


def test_summary_exact_text(csv_path):
    res = m.evaluate(m.load_points([csv_path]))
    # |err| = 0.8, 0.32, 0.043, 0: median 18.1 %, max 80.0 %; only 0.4 and 0.5 are within 10 %.
    assert m.summarize(res) == (
        "relative error (ideal - measured) / measured: median 18.1 %, max 80.0 %; "
        "ideal formula within 10 % at D 0.40 to 0.50"
    )


def test_main_writes_plot_only_when_asked(csv_path, tmp_path, capsys):
    m.main([str(csv_path)])
    assert not list(tmp_path.glob("*.png"))
    out = tmp_path / "p.png"
    m.main([str(csv_path), "--plot", str(out)])
    assert out.stat().st_size > 0
    assert "relative error" in capsys.readouterr().out
