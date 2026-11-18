"""The committed P&O fixtures must match what scripts/gen_po_traces.py makes."""

from scripts.gen_po_traces import FIXTURE_DIR, render


def test_fixtures_match_generator():
    expected = render()
    assert expected
    for name, text in expected.items():
        assert (FIXTURE_DIR / name).read_text() == text, f"{name} is stale: rerun the script"


def test_traces_move_and_stay_in_limits():
    for text in render().values():
        duties = [int(r.split(",")[2]) for r in text.splitlines()[1:]]
        assert len(set(duties)) > 3
        assert all(3277 <= d <= 62258 for d in duties)
