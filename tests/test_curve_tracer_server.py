"""Unit tests for scripts/curve_tracer_server.py's FastAPI routes.

`fastapi` (and its `httpx2`-backed `TestClient`) live behind the optional
``[web]`` extra - skip cleanly if it isn't installed, same convention this
repo already uses for pvlib-dependent tests. No hardware/`spidev` needed:
`create_app()` takes a `_SweepCache`/command queue directly, and only
`_poll_loop` (never called here) touches `SpiMcuSource`.
"""

import json
import queue
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mpp_sdk.curves import CurveRecord, PanelSetup, save  # noqa: E402
from mpp_sdk.curves.record import now_utc  # noqa: E402
from mpp_sdk.runs import RunRecord, RunSample  # noqa: E402
from mpp_sdk.runs import save as save_run  # noqa: E402
from scripts.curve_tracer_server import (  # noqa: E402
    _curve_path,
    _downsample_samples,
    _run_path,
    _SweepCache,
    create_app,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient against a fresh, hardware-free app: `default_dir()`
    (via `MPP_SDK_CURVE_DIR`/`MPP_SDK_RUN_DIR`) points at isolated
    directories under tmp_path, and the returned `cache` lets a test drive
    `/api/data` directly, the same way `_poll_loop` would.

    Curves and runs get separate directories (tmp_path itself, and a
    `runs/` subdirectory) - both glob `*.json` in their own default_dir(),
    and sharing one directory would make each listing pick up the other's
    files."""
    monkeypatch.setenv("MPP_SDK_CURVE_DIR", str(tmp_path))
    run_dir = tmp_path / "runs"
    monkeypatch.setenv("MPP_SDK_RUN_DIR", str(run_dir))
    cache = _SweepCache()
    commands: queue.Queue[str] = queue.Queue()
    app = create_app(cache, commands)
    with TestClient(app) as test_client:
        test_client.cache = cache  # type: ignore[attr-defined]
        test_client.commands = commands  # type: ignore[attr-defined]
        test_client.run_dir = run_dir  # type: ignore[attr-defined]
        yield test_client


class _FakeProgress:
    def __init__(self, index, voltage, current, active, final_point=False):
        self.index, self.voltage, self.current = index, voltage, current
        self.active, self.final_point = active, final_point


def _save(directory, label="t", measurement="baseline", points=((21.3, 0.006), (18.0, 0.195))):
    return save(
        CurveRecord(
            captured_at=now_utc(),
            label=label,
            measurement=measurement,
            panels=(PanelSetup(id="A", tilt_deg=0),),
            points=tuple(points),
        ),
        directory=directory,
    )


def _save_run(directory, label="run", algorithm="P&O", samples=None, **overrides):
    if samples is None:
        samples = (
            RunSample(t=0.0, voltage=20.0, current=0.05, duty=0.5),
            RunSample(t=0.1, voltage=18.0, current=0.10, duty=0.55),
        )
    fields = {
        "captured_at": now_utc(),
        "label": label,
        "algorithm": algorithm,
        "samples": tuple(samples),
        "curve_ref": None,
        "aborted": False,
        "notes": "",
    }
    fields.update(overrides)
    return save_run(RunRecord(**fields), directory=directory)


# ------------------------------------------------------------------
# GET /api/data
# ------------------------------------------------------------------


def test_data_defaults_before_anything_is_cached(client):
    r = client.get("/api/data")
    assert r.status_code == 200
    assert r.json() == {
        "points": [],
        "partial": [],
        "active": False,
        "link": "no data yet",
        "seq": 0,
        "command_error": None,
        "demo_source": False,
    }


def test_data_reflects_a_completed_sweep_in_milliamps(client):
    client.cache.set([(21.3, 0.006), (18.0, 0.195)], "ok")
    payload = client.get("/api/data").json()
    assert payload["points"] == [{"x": 21.3, "y": 6.0}, {"x": 18.0, "y": 195.0}]
    assert payload["link"] == "ok"
    assert payload["seq"] == 1


def test_data_reflects_live_progress_while_active(client):
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    payload = client.get("/api/data").json()
    assert payload["active"] is True
    assert payload["partial"] == [{"x": 21.3, "y": 6.0}]


def test_a_zero_point_sweep_clears_a_previous_sweeps_stale_partial(client):
    """A sweep that aborts with zero points (e.g. auto_range() finds no
    panel) publishes only one inactive update, with no preceding
    active=True calls of its own - `partial` must not keep serving the
    previous, unrelated sweep's leftover points as if they belonged to
    this (empty) one."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    client.cache.set_progress(_FakeProgress(255, 0.0, 0.0, active=False, final_point=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is False
    assert payload["partial"] == []


def test_an_index_below_the_high_water_mark_starts_a_new_sweep(client):
    """A new sweep's own early point (low index) arriving while the cache
    still thinks the previous, higher-indexed sweep is active must replace
    `partial`, not merge with it - see set_progress()'s comment on why
    index==0 alone isn't a reliable "new sweep" signal."""
    client.cache.set_progress(_FakeProgress(5, 15.0, 0.050, active=True))
    client.cache.set_progress(_FakeProgress(6, 14.5, 0.060, active=True))

    # Next sweep's first observed point - index 1, well below the previous
    # sweep's high-water mark of 6 - arrives while `active` is still True
    # (no intervening inactive update, matching how a fast next sweep can
    # actually be observed by a lossy poller).
    client.cache.set_progress(_FakeProgress(1, 21.0, 0.010, active=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is True
    assert payload["partial"] == [{"x": 21.0, "y": 10.0}]


def test_redelivering_the_current_max_index_does_not_reset_partial(client):
    """poll_sweep_progress() is peek-not-consume (see SpiMcuSource /
    DemoSweepSource docstrings) - a slow poller can observe the same
    in-progress point more than once before the sweep advances. That must
    not be mistaken for a new sweep starting (the reset condition is
    index < max, strictly), and must not lose earlier points."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    # Same index (1) delivered again, same sweep still active.
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is True
    assert payload["partial"] == [
        {"x": 21.3, "y": 6.0},
        {"x": 20.1, "y": 105.0},
    ]


# ------------------------------------------------------------------
# GET /api/measurement-kinds
# ------------------------------------------------------------------


def test_measurement_kinds_returns_the_seed_vocabulary(client):
    r = client.get("/api/measurement-kinds")
    assert r.status_code == 200
    assert "baseline" in r.json()
    assert "tilted" in r.json()


# ------------------------------------------------------------------
# GET /api/curves
# ------------------------------------------------------------------


def test_curves_empty_library_returns_empty_list(client):
    assert client.get("/api/curves").json() == []


def test_curves_lists_saved_records_with_stats(client, tmp_path):
    _save(tmp_path, label="both flat", points=((21.3, 0.006), (18.0, 0.195), (8.0, 0.215)))
    entries = client.get("/api/curves").json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["label"] == "both flat"
    assert entry["measurement"] == "baseline"
    assert entry["n_points"] == 3
    assert entry["voc"] == pytest.approx(21.3)
    assert entry["isc"] == pytest.approx(0.215)
    assert entry["panels"] == [{"id": "A", "tilt_deg": 0}]


def test_curves_reports_points_in_amps_matching_the_saved_record(client, tmp_path):
    """GET /api/curves must stay internally consistent with its own
    voc/isc/p_mpp (amps/volts/watts) - unlike GET /api/data, which reports
    current in milliamps for the live-capture UI."""
    points = ((21.3, 0.006), (18.0, 0.195), (8.0, 0.215))
    _save(tmp_path, label="both flat", points=points)
    entry = client.get("/api/curves").json()[0]
    assert entry["points"] == [{"v": v, "i": i} for v, i in points]


def test_curves_reports_a_malformed_file_without_failing_the_whole_list(client, tmp_path):
    (tmp_path / "bad.json").write_text("not json")
    _save(tmp_path, label="good")
    entries = client.get("/api/curves").json()
    by_label_or_error = {e.get("label", e.get("error")) for e in entries}
    assert "good" in by_label_or_error
    assert any("error" in e for e in entries)


def test_curves_include_an_id_matching_the_filename_stem(client, tmp_path):
    path = _save(tmp_path, label="both flat")
    entry = client.get("/api/curves").json()[0]
    assert entry["id"] == path.stem


# ------------------------------------------------------------------
# DELETE /api/curves/{id}
# ------------------------------------------------------------------


def test_delete_curve_removes_the_file(client, tmp_path):
    path = _save(tmp_path, label="both flat")
    r = client.delete(f"/api/curves/{path.stem}")
    assert r.status_code == 204
    assert not path.exists()
    assert client.get("/api/curves").json() == []


def test_delete_curve_unknown_id_is_404(client):
    r = client.delete("/api/curves/does-not-exist")
    assert r.status_code == 404


def test_delete_curve_rejects_an_id_with_disallowed_characters(client):
    r = client.delete("/api/curves/weird id")
    assert r.status_code == 400


def test_curve_path_rejects_an_id_containing_a_slash(client):
    with pytest.raises(fastapi.HTTPException) as exc_info:
        _curve_path("../secret")
    assert exc_info.value.status_code == 400


# ------------------------------------------------------------------
# POST /api/save-curve
# ------------------------------------------------------------------


def test_save_curve_without_a_captured_sweep_returns_409(client):
    r = client.post("/api/save-curve", json={"label": "x", "measurement": "baseline"})
    assert r.status_code == 409


def test_save_curve_round_trips(client):
    client.cache.set([(21.3, 0.006), (18.0, 0.195)], "ok")
    r = client.post(
        "/api/save-curve",
        json={
            "label": "both flat",
            "measurement": "baseline",
            "panels": [{"id": "A", "tilt_deg": 0}],
            "notes": "",
        },
    )
    assert r.status_code == 200
    assert Path(r.json()["path"]).exists()


def test_save_curve_defaults_measurement_and_panels_when_omitted(client):
    client.cache.set([(21.3, 0.006), (18.0, 0.195)], "ok")
    r = client.post("/api/save-curve", json={})
    assert r.status_code == 200


# ------------------------------------------------------------------
# POST /api/start-sweep, /api/release-relay
# ------------------------------------------------------------------


def test_start_sweep_enqueues_the_command(client):
    r = client.post("/api/start-sweep")
    assert r.status_code == 204
    assert client.commands.get_nowait() == "start_sweep"


def test_release_relay_enqueues_the_command(client):
    r = client.post("/api/release-relay")
    assert r.status_code == 204
    assert client.commands.get_nowait() == "release_relay"


# ------------------------------------------------------------------
# Command-error visibility (_SweepCache.set_command_error)
# ------------------------------------------------------------------


def test_command_error_is_reported_via_api_data(client):
    client.cache.set_command_error("release_relay failed: SPI timeout")
    payload = client.get("/api/data").json()
    assert payload["command_error"] == "release_relay failed: SPI timeout"


def test_command_error_survives_a_later_telemetry_update(client):
    """A command can fail on a transient glitch while the very next
    request_sweep() call (same _poll_loop iteration) succeeds. The error
    must still be visible afterward - cache.set() must not clobber it."""
    client.cache.set_command_error("start_sweep failed: SPI timeout")
    client.cache.set([(21.3, 0.006)], "ok")

    payload = client.get("/api/data").json()
    assert payload["link"] == "ok"
    assert payload["command_error"] == "start_sweep failed: SPI timeout"


def test_command_error_clears_on_the_next_successful_command(client):
    client.cache.set_command_error("release_relay failed: SPI timeout")
    client.cache.set_command_error(None)

    payload = client.get("/api/data").json()
    assert payload["command_error"] is None


def test_demo_source_flag_survives_polling_and_flips_back(client):
    """A replayed curve must stay marked as one for as long as it is the
    curve on screen - otherwise the page would show firmware-stored points
    as if they had just been measured."""
    client.cache.set_demo_source(True)
    client.cache.set([(19.3, 0.006)], "ok")
    assert client.get("/api/data").json()["demo_source"] is True
    # Repeated polls must not clear it.
    assert client.get("/api/data").json()["demo_source"] is True

    # Dispatching a real-sweep command alone must not flip the flag - the
    # points on screen are still the demo curve until a result lands.
    client.cache.set_demo_source(False)
    assert client.get("/api/data").json()["demo_source"] is True

    client.cache.set([(21.0, 0.010)], "ok")
    assert client.get("/api/data").json()["demo_source"] is False


def test_demo_source_does_not_flip_before_the_commanded_sweep_completes(client):
    """Reproduces the provenance bug: a real sweep is commanded (flipping
    the PENDING flag) but auto_range() hasn't produced a result yet, so
    `_points` still holds the previous demo curve. GET /api/data - and a
    save taken in this window - must keep describing that demo data, not
    the still-in-flight real command."""
    client.cache.set_demo_source(True)
    client.cache.set([(19.3, 0.006)], "ok")

    # Operator clicks Start Measurement: the poll loop dispatches the
    # command and flips the pending flag immediately, seconds before
    # auto_range() finishes and a result is fetched.
    client.cache.set_demo_source(False)

    payload = client.get("/api/data").json()
    assert payload["demo_source"] is True
    assert payload["points"] == [{"x": 19.3, "y": 6.0}]

    r = client.post("/api/save-curve", json={"label": "mid-command", "measurement": "baseline"})
    assert r.status_code == 200
    saved = json.loads(Path(r.json()["path"]).read_text())
    assert saved["source"] == "firmware-replay"


def test_demo_source_does_not_flip_early_the_other_direction(client):
    """Same bug, opposite direction: a demo sweep is commanded while a real
    measurement is still on screen. The real curve must not be mislabeled
    as firmware-replay before the demo sweep's own points arrive."""
    client.cache.set([(19.3, 0.006)], "ok")
    assert client.get("/api/data").json()["demo_source"] is False

    client.cache.set_demo_source(True)

    payload = client.get("/api/data").json()
    assert payload["demo_source"] is False
    assert payload["points"] == [{"x": 19.3, "y": 6.0}]

    r = client.post("/api/save-curve", json={"label": "still-real", "measurement": "baseline"})
    assert r.status_code == 200
    saved = json.loads(Path(r.json()["path"]).read_text())
    assert saved["source"] == "hardware"

    # Once the demo sweep's own points land, the label follows the data.
    client.cache.set([(21.0, 0.010)], "demo")
    assert client.get("/api/data").json()["demo_source"] is True


def test_saved_curve_records_provenance_from_the_server_not_the_request(client):
    """The page cannot be trusted to admit that the curve on screen was
    replayed rather than measured, so the source is taken from the cache."""
    client.cache.set_demo_source(True)
    client.cache.set([(19.3, 0.006), (13.9, 0.555)], "ok")

    r = client.post("/api/save-curve", json={"label": "replayed", "measurement": "baseline"})
    assert r.status_code == 200
    saved = json.loads(Path(r.json()["path"]).read_text())
    assert saved["source"] == "firmware-replay"
    assert client.get("/api/curves").json()[0]["source"] == "firmware-replay"


def test_a_real_sweep_is_saved_as_hardware(client):
    client.cache.set([(19.3, 0.006)], "ok")
    r = client.post("/api/save-curve", json={"label": "measured", "measurement": "baseline"})
    assert json.loads(Path(r.json()["path"]).read_text())["source"] == "hardware"


def test_demo_mode_saves_as_simulated(client):
    client.cache.set_simulated(True)
    client.cache.set([(21.3, 0.006)], "demo")
    r = client.post("/api/save-curve", json={"label": "sim", "measurement": "baseline"})
    assert json.loads(Path(r.json()["path"]).read_text())["source"] == "simulated"


# ------------------------------------------------------------------
# GET /api/runs
# ------------------------------------------------------------------


def test_runs_empty_library_returns_empty_list(client):
    assert client.get("/api/runs").json() == []


def test_runs_lists_saved_records_as_summaries_without_samples(client):
    path = _save_run(client.run_dir, label="bench check", algorithm="P&O")
    entries = client.get("/api/runs").json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == path.stem
    assert entry["path"] == str(path)
    assert entry["label"] == "bench check"
    assert entry["algorithm"] == "P&O"
    assert entry["n_samples"] == 2
    assert entry["duration_s"] == pytest.approx(0.1)
    assert entry["aborted"] is False
    assert entry["curve_ref"] is None
    assert entry["notes"] == ""
    assert "samples" not in entry


def test_runs_reports_curve_ref_when_present(client):
    _save_run(client.run_dir, curve_ref="20260908T120000Z-baseline.json")
    entry = client.get("/api/runs").json()[0]
    assert entry["curve_ref"] == "20260908T120000Z-baseline.json"


def test_runs_reports_a_malformed_file_without_failing_the_whole_list(client):
    client.run_dir.mkdir(parents=True, exist_ok=True)
    (client.run_dir / "bad.json").write_text("not json")
    _save_run(client.run_dir, label="good")
    entries = client.get("/api/runs").json()
    by_label_or_error = {e.get("label", e.get("error")) for e in entries}
    assert "good" in by_label_or_error
    assert any("error" in e for e in entries)


# ------------------------------------------------------------------
# GET /api/runs/{id}
# ------------------------------------------------------------------


def test_get_run_returns_the_full_record_with_samples(client):
    path = _save_run(client.run_dir, label="bench check")
    entry = client.get(f"/api/runs/{path.stem}").json()
    assert entry["id"] == path.stem
    assert entry["label"] == "bench check"
    assert entry["n_samples"] == 2
    assert entry["downsampled"] is False
    assert entry["samples"] == [
        {"t": 0.0, "v": 20.0, "i": 0.05, "d": 0.5},
        {"t": 0.1, "v": 18.0, "i": 0.10, "d": 0.55},
    ]


def test_get_run_unknown_id_is_404(client):
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404


def test_get_run_rejects_an_id_with_disallowed_characters(client):
    # A slash itself never reaches this test: the HTTP client collapses
    # ".." dot-segments (encoded or not) during URL normalization before
    # the request is even sent, same as a browser would - see
    # test_run_path_rejects_an_id_containing_a_slash below for a direct,
    # client-independent check of _run_path's own rejection. This test
    # instead exercises the same 400 path through a real HTTP request,
    # using a character the id regex disallows but that no URL layer
    # normalizes away.
    r = client.get("/api/runs/weird id")
    assert r.status_code == 400


def test_get_run_with_an_all_dots_id_is_a_plain_404_not_a_traversal(client):
    # "." and ".." pass the id regex (it only restricts the character
    # set), but they can never escape the library directory: the id is
    # always joined as `{id}.json`, a single filename, never a path
    # segment on its own - so this can only ever miss, never traverse.
    r = client.get("/api/runs/..")
    assert r.status_code == 404


def test_get_run_downsamples_over_the_cap_but_keeps_first_and_last(client):
    samples = tuple(
        RunSample(t=float(i), voltage=20.0 - i, current=0.05, duty=0.5) for i in range(10)
    )
    path = _save_run(client.run_dir, samples=samples)

    entry = client.get(f"/api/runs/{path.stem}", params={"max_samples": 3}).json()

    assert entry["n_samples"] == 10  # true on-disk count, not the returned count
    assert entry["downsampled"] is True
    assert len(entry["samples"]) < 10
    assert entry["samples"][0] == samples[0].to_dict()
    assert entry["samples"][-1] == samples[-1].to_dict()


def test_get_run_max_samples_zero_returns_everything(client):
    samples = tuple(RunSample(t=float(i), voltage=20.0, current=0.05, duty=0.5) for i in range(10))
    path = _save_run(client.run_dir, samples=samples)

    entry = client.get(f"/api/runs/{path.stem}", params={"max_samples": 0}).json()

    assert entry["downsampled"] is False
    assert len(entry["samples"]) == 10


def test_get_run_default_cap_does_not_downsample_a_small_run(client):
    path = _save_run(client.run_dir)
    entry = client.get(f"/api/runs/{path.stem}").json()
    assert entry["downsampled"] is False
    assert len(entry["samples"]) == 2


# ------------------------------------------------------------------
# DELETE /api/runs/{id}
# ------------------------------------------------------------------


def test_delete_run_removes_the_file(client):
    path = _save_run(client.run_dir)
    r = client.delete(f"/api/runs/{path.stem}")
    assert r.status_code == 204
    assert not path.exists()
    assert client.get("/api/runs").json() == []


def test_delete_run_unknown_id_is_404(client):
    r = client.delete("/api/runs/does-not-exist")
    assert r.status_code == 404


def test_delete_run_rejects_an_id_with_disallowed_characters(client):
    r = client.delete("/api/runs/weird id")
    assert r.status_code == 400


# ------------------------------------------------------------------
# _run_path / _downsample_samples (unit-level, direct traversal checks)
# ------------------------------------------------------------------


def test_run_path_rejects_an_id_containing_a_slash(client):
    with pytest.raises(fastapi.HTTPException) as exc_info:
        _run_path("../secret")
    assert exc_info.value.status_code == 400


def test_downsample_samples_always_keeps_first_and_last():
    samples = tuple(RunSample(t=float(i), voltage=0.0, current=0.0, duty=0.0) for i in range(100))
    picked, downsampled = _downsample_samples(samples, 10)
    assert downsampled is True
    assert picked[0] == samples[0]
    assert picked[-1] == samples[-1]
    assert len(picked) < 100


def test_downsample_samples_below_the_cap_is_unchanged():
    samples = tuple(RunSample(t=float(i), voltage=0.0, current=0.0, duty=0.0) for i in range(5))
    picked, downsampled = _downsample_samples(samples, 10)
    assert downsampled is False
    assert picked == list(samples)
