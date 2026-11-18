"""Unit tests for `mpp_sdk.runs.library.list_summaries`: the run listing is
served from a sidecar index so it never parses the sample arrays."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from mpp_sdk.runs import RunRecord, RunSample, library, load, save
from mpp_sdk.runs.library import list_summaries


def _record(**overrides) -> RunRecord:
    fields = {
        "captured_at": datetime(2026, 9, 8, 21, 14, 3, tzinfo=UTC),
        "label": "bench check",
        "algorithm": "P&O",
        "samples": (
            RunSample(t=0.0, voltage=20.0, current=0.05, duty=0.5),
            RunSample(t=0.1, voltage=18.0, current=0.1, duty=0.55),
        ),
        "curve_ref": None,
        "aborted": False,
        "notes": "",
    }
    fields.update(overrides)
    return RunRecord(**fields)


def _from_full_load(path):
    r = load(path)
    return {
        "captured_at": r.captured_at.isoformat(),
        "label": r.label,
        "algorithm": r.algorithm,
        "n_samples": len(r.samples),
        "duration_s": r.samples[-1].t - r.samples[0].t if len(r.samples) >= 2 else 0.0,
        "aborted": r.aborted,
        "curve_ref": r.curve_ref,
        "notes": r.notes,
        "source": r.source,
        "session_id": r.session_id,
    }


def test_summaries_match_full_loads_for_the_committed_bench_runs(tmp_path):
    sources = sorted((Path(__file__).parent.parent / "data" / "bench").glob("**/run_*.json"))
    assert sources
    for i, src in enumerate(sources):
        shutil.copy(src, tmp_path / f"{i:03d}.json")
    for _ in range(2):  # cold, then from the index
        listed = list_summaries(tmp_path)
        assert [p.name for p, _ in listed] == [f"{i:03d}.json" for i in range(len(sources))]
        for path, summary in listed:
            assert summary == _from_full_load(path)


def test_old_files_without_an_index_are_still_listed(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps(_record().to_dict()))
    assert not (tmp_path / ".summary-index").exists()
    [(listed_path, summary)] = list_summaries(tmp_path)
    assert listed_path == path
    assert summary["n_samples"] == 2
    assert (tmp_path / ".summary-index").exists()


def test_a_file_edited_on_disk_gets_a_fresh_summary(tmp_path):
    path = save(_record(), tmp_path)
    assert list_summaries(tmp_path)[0][1]["label"] == "bench check"
    data = json.loads(path.read_text())
    data["label"] = "renamed run"
    path.write_text(json.dumps(data))
    assert list_summaries(tmp_path)[0][1]["label"] == "renamed run"


def test_a_malformed_file_reports_its_error(tmp_path):
    (tmp_path / "bad.json").write_text("{}")
    [(_, summary)] = list_summaries(tmp_path)
    assert isinstance(summary, str)


def test_listing_many_runs_does_not_parse_run_files(tmp_path, monkeypatch):
    samples = tuple(RunSample(t=i * 0.01, voltage=18.0, current=0.1, duty=0.5) for i in range(200))
    for i in range(200):
        save(_record(label=f"run {i}", samples=samples), tmp_path)
    assert len(list_summaries(tmp_path)) == 200  # builds the index
    loads = []
    real = library.load
    monkeypatch.setattr(library, "load", lambda p: loads.append(p) or real(p))
    assert len(list_summaries(tmp_path)) == 200
    assert loads == []
