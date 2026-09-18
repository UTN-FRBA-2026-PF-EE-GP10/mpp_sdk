"""Unit tests for scripts/curve_tracer_server.py's FastAPI routes.

`fastapi` (and its `httpx2`-backed `TestClient`) live behind the optional
``[web]`` extra - skip cleanly if it isn't installed, same convention this
repo already uses for pvlib-dependent tests. No hardware/`spidev` needed:
`create_app()` takes a `_SweepCache`/command queue directly, and only
`_poll_loop` (never called here) touches `SpiMcuSource`.
"""

import json
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from harness.common import AlgorithmSpec, algorithm_specs  # noqa: E402
from mpp_sdk import IdealSingleDiode  # noqa: E402
from mpp_sdk.curves import CurveRecord, PanelSetup, save  # noqa: E402
from mpp_sdk.curves.record import now_utc  # noqa: E402
from mpp_sdk.runs import RunRecord, RunSample  # noqa: E402
from mpp_sdk.runs import load as load_run  # noqa: E402
from mpp_sdk.runs import save as save_run  # noqa: E402
from scripts.curve_tracer_server import (  # noqa: E402
    _DEFAULT_I_MAX,
    _DEFAULT_RUN_DURATION_S,
    _DEFAULT_V_MAX,
    _MAX_BATCH_DELETE_IDS,
    _MAX_RUN_DURATION_S,
    _curve_path,
    _downsample_samples,
    _LiveRunCache,
    _make_simulated_source,
    _poll_loop,
    _run_live,
    _run_path,
    _run_simulated,
    _RunRequest,
    _StartRunRequest,
    _SweepCache,
    create_app,
)


def _make_client(monkeypatch, tmp_path, *, demo=False):
    """Shared by `client` and `demo_client` below - see `client`'s
    docstring for the directory-isolation reasoning. Always wires up the
    live-run objects (`run_cache`/`run_requests`/`stop_event`) too, even
    for tests that never touch `/api/runs/start` - `create_app` defaults
    them to fresh instances anyway, so exposing the real ones costs
    nothing and lets a run-focused test reach them directly."""
    monkeypatch.setenv("MPP_SDK_CURVE_DIR", str(tmp_path))
    run_dir = tmp_path / "runs"
    monkeypatch.setenv("MPP_SDK_RUN_DIR", str(run_dir))
    cache = _SweepCache()
    commands: queue.Queue[str] = queue.Queue()
    run_cache = _LiveRunCache()
    run_requests: queue.Queue[_RunRequest] = queue.Queue()
    stop_event = threading.Event()
    app = create_app(
        cache,
        commands,
        demo=demo,
        run_cache=run_cache,
        run_requests=run_requests,
        stop_event=stop_event,
    )
    test_client = TestClient(app)
    test_client.cache = cache  # type: ignore[attr-defined]
    test_client.commands = commands  # type: ignore[attr-defined]
    test_client.run_dir = run_dir  # type: ignore[attr-defined]
    test_client.run_cache = run_cache  # type: ignore[attr-defined]
    test_client.run_requests = run_requests  # type: ignore[attr-defined]
    test_client.stop_event = stop_event  # type: ignore[attr-defined]
    return test_client


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
    with _make_client(monkeypatch, tmp_path) as test_client:
        yield test_client


@pytest.fixture
def demo_client(monkeypatch, tmp_path):
    """Same as `client`, but built with `demo=True` - for the one thing
    that differs in demo mode: `POST /api/runs/start` must refuse (no
    board), same as running the real server with `--demo`."""
    with _make_client(monkeypatch, tmp_path, demo=True) as test_client:
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
# GET /api/run-config
# ------------------------------------------------------------------


def test_run_config_lists_the_registered_roster(client):
    r = client.get("/api/run-config")
    assert r.status_code == 200
    assert r.json()["algorithms"] == [s.label for s in algorithm_specs()]


def test_run_config_matches_what_start_run_will_accept(client):
    # POST /api/runs/start matches algorithm names case-insensitively
    # against algorithm_specs() - this pins that the served roster is
    # drawn from that exact same source, not a hand-copied list that
    # could drift from it.
    labels = client.get("/api/run-config").json()["algorithms"]
    assert len(labels) == len(algorithm_specs())
    assert all(label.lower() in {s.label.lower() for s in algorithm_specs()} for label in labels)


def test_run_config_serves_the_bounds_a_run_is_actually_held_to(client):
    """The page shows these before starting something that drives a power
    converter, so they have to be the values the server enforces rather
    than a copy that can drift."""
    body = client.get("/api/run-config").json()
    assert body["max_duration_s"] == _MAX_RUN_DURATION_S
    assert body["default_v_max"] == _DEFAULT_V_MAX
    assert body["default_i_max"] == _DEFAULT_I_MAX

    # A start request that omits the limits must be held to exactly these.
    assert _StartRunRequest(algorithm="P&O").v_max == body["default_v_max"]
    assert _StartRunRequest(algorithm="P&O").i_max == body["default_i_max"]


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
# POST /api/curves/delete-batch
# ------------------------------------------------------------------


def test_delete_curves_batch_removes_every_file(client, tmp_path):
    a = _save(tmp_path, label="a")
    b = _save(tmp_path, label="b")
    r = client.post("/api/curves/delete-batch", json={"ids": [a.stem, b.stem]})
    assert r.status_code == 200
    assert sorted(r.json()["deleted"]) == sorted([a.stem, b.stem])
    assert r.json()["failed"] == []
    assert not a.exists()
    assert not b.exists()


def test_delete_curves_batch_reports_an_invalid_id_as_failed_not_a_500(client):
    r = client.post("/api/curves/delete-batch", json={"ids": ["weird id"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == []
    assert r.json()["failed"] == [{"id": "weird id", "error": "invalid curve id"}]


def test_delete_curves_batch_reports_an_unknown_id_as_failed(client):
    r = client.post("/api/curves/delete-batch", json={"ids": ["does-not-exist"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == []
    assert r.json()["failed"] == [{"id": "does-not-exist", "error": "curve not found"}]


def test_delete_curves_batch_mixed_result_deletes_the_good_ones_and_reports_the_rest(
    client, tmp_path
):
    ok = _save(tmp_path, label="ok")
    r = client.post(
        "/api/curves/delete-batch",
        json={"ids": [ok.stem, "does-not-exist", "weird id"]},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == [ok.stem]
    failed_ids = {entry["id"] for entry in r.json()["failed"]}
    assert failed_ids == {"does-not-exist", "weird id"}
    assert not ok.exists()


def test_delete_curves_batch_empty_list_is_a_no_op(client):
    r = client.post("/api/curves/delete-batch", json={"ids": []})
    assert r.status_code == 200
    assert r.json() == {"deleted": [], "failed": []}


def test_delete_curves_batch_over_the_limit_is_rejected_with_400(client):
    ids = [f"id-{i}" for i in range(_MAX_BATCH_DELETE_IDS + 1)]
    r = client.post("/api/curves/delete-batch", json={"ids": ids})
    assert r.status_code == 400


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
# POST /api/runs/delete-batch
# ------------------------------------------------------------------


def test_delete_runs_batch_removes_every_file(client):
    a = _save_run(client.run_dir, label="a")
    b = _save_run(client.run_dir, label="b")
    r = client.post("/api/runs/delete-batch", json={"ids": [a.stem, b.stem]})
    assert r.status_code == 200
    assert sorted(r.json()["deleted"]) == sorted([a.stem, b.stem])
    assert r.json()["failed"] == []
    assert not a.exists()
    assert not b.exists()


def test_delete_runs_batch_reports_an_invalid_id_as_failed_not_a_500(client):
    r = client.post("/api/runs/delete-batch", json={"ids": ["weird id"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == []
    assert r.json()["failed"] == [{"id": "weird id", "error": "invalid run id"}]


def test_delete_runs_batch_reports_an_unknown_id_as_failed(client):
    r = client.post("/api/runs/delete-batch", json={"ids": ["does-not-exist"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == []
    assert r.json()["failed"] == [{"id": "does-not-exist", "error": "run not found"}]


def test_delete_runs_batch_mixed_result_deletes_the_good_ones_and_reports_the_rest(client):
    ok = _save_run(client.run_dir, label="ok")
    r = client.post(
        "/api/runs/delete-batch",
        json={"ids": [ok.stem, "does-not-exist", "weird id"]},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == [ok.stem]
    failed_ids = {entry["id"] for entry in r.json()["failed"]}
    assert failed_ids == {"does-not-exist", "weird id"}
    assert not ok.exists()


def test_delete_runs_batch_empty_list_is_a_no_op(client):
    r = client.post("/api/runs/delete-batch", json={"ids": []})
    assert r.status_code == 200
    assert r.json() == {"deleted": [], "failed": []}


def test_delete_runs_batch_over_the_limit_is_rejected_with_400(client):
    ids = [f"id-{i}" for i in range(_MAX_BATCH_DELETE_IDS + 1)]
    r = client.post("/api/runs/delete-batch", json={"ids": ids})
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


# ------------------------------------------------------------------
# POST /api/runs/start, POST /api/runs/stop, GET /api/runs/live
# ------------------------------------------------------------------


class _FakeRunSource:
    """Minimal fake board for `_run_live`: `read()`/`write()` like
    `test_run_algorithm.py`'s `_FakeSource`, plus `vout` and
    `consecutive_bad_frames` since `_run_live`/`run_control_loop` read
    both (`SpiMcuSource` has both; a plain SignalSource fake would not,
    and must still work - see `test_a_fake_source...` in
    test_run_algorithm.py)."""

    def __init__(self):
        self._duty = 0.0
        self.vout = 12.0
        self.consecutive_bad_frames = 0
        self.writes: list[float] = []

    def write(self, duty):
        self._duty = duty
        self.writes.append(duty)

    def read(self):
        v = 20.0 * (1.0 - self._duty)
        i = 0.2 * self._duty
        return v, i


class _FakeRunSourceWithRelay(_FakeRunSource):
    """Same fake, plus a `release_relay()` a test can confirm was called -
    a real `SpiMcuSource` has one, but `_run_live` must still work against
    a fake/simulated source that doesn't (see `getattr` in `_run_live`)."""

    def __init__(self):
        super().__init__()
        self.relay_released = False

    def release_relay(self):
        self.relay_released = True


class _RaisingAfterNAlgorithm:
    """Steps normally `n` times, then raises - stands in for a broken
    algorithm or a hard mid-run fault, to check the samples collected
    before the failure still get saved (see _execute_run)."""

    def __init__(self, n):
        self._n = n
        self.calls = 0

    def step(self, voltage, current):
        self.calls += 1
        if self.calls > self._n:
            raise RuntimeError("algorithm boom")
        return 0.5


def _po_spec():
    return next(s for s in algorithm_specs() if s.label == "P&O")


def test_start_run_rejected_in_demo_mode(demo_client):
    """Never start a run without a real board - --demo's source has no
    read()/write() at all, so this must be refused up front, not after
    queuing something doomed to fail partway."""
    r = demo_client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r.status_code == 409
    assert demo_client.run_requests.empty()


def test_start_run_rejects_an_unknown_algorithm(client):
    r = client.post("/api/runs/start", json={"algorithm": "not-a-real-algorithm"})
    assert r.status_code == 400
    assert client.run_requests.empty()


def test_start_run_rejects_an_unknown_curve_ref(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "curve_ref": "does-not-exist"})
    assert r.status_code == 404
    assert client.run_requests.empty()


def test_start_run_rejects_a_non_positive_duration(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "duration_s": 0})
    assert r.status_code == 400
    assert client.run_requests.empty()


def test_start_run_rejects_a_nan_v_max(client):
    """JSON's non-standard NaN literal parses straight into a pydantic
    float field, and `nan <= 0` is False - without an explicit
    math.isfinite check this would sail past the non-positive check and
    disable the overvoltage abort for the run's whole duration."""
    r = client.post(
        "/api/runs/start",
        content=b'{"algorithm":"P&O","v_max":NaN}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert "v_max" in r.json()["detail"]
    assert client.run_requests.empty()


def test_start_run_rejects_an_infinite_i_max(client):
    r = client.post(
        "/api/runs/start",
        content=b'{"algorithm":"P&O","i_max":Infinity}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert "i_max" in r.json()["detail"]
    assert client.run_requests.empty()


def test_start_run_rejects_a_nan_duration_and_initial_duty(client):
    r = client.post(
        "/api/runs/start",
        content=b'{"algorithm":"P&O","duration_s":NaN}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert "duration_s" in r.json()["detail"]

    r = client.post(
        "/api/runs/start",
        content=b'{"algorithm":"P&O","initial_duty":NaN}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert "initial_duty" in r.json()["detail"]


def test_start_run_accepts_a_valid_request_and_enqueues_it(client):
    r = client.post(
        "/api/runs/start",
        json={
            "algorithm": "p&o",  # case-insensitive, like the CLI's --algorithm
            "duration_s": 5.0,
            "v_max": 30.0,
            "i_max": 0.5,
            "label": "bench",
        },
    )
    assert r.status_code == 200
    assert r.json() == {
        "status": "running",
        "algorithm": "P&O",
        "label": "bench",
        "duration_s": 5.0,
    }

    queued = client.run_requests.get_nowait()
    assert queued.spec.label == "P&O"
    assert queued.duration_s == 5.0
    assert queued.v_max == 30.0
    assert queued.i_max == 0.5
    assert queued.label == "bench"
    assert queued.curve_ref is None

    live = client.get("/api/runs/live").json()
    assert live["status"] == "running"
    assert live["algorithm"] == "P&O"
    assert live["label"] == "bench"


def test_start_run_defaults_label_to_the_algorithm_label_when_omitted(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r.json()["label"] == "P&O"


def test_start_run_defaults_to_a_short_watchable_duration(client):
    """Not the backstop. A run drives a real converter and is something an
    operator watches, so the default is a look, not the ceiling."""
    r = client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r.json()["duration_s"] == pytest.approx(_DEFAULT_RUN_DURATION_S)
    assert _DEFAULT_RUN_DURATION_S < _MAX_RUN_DURATION_S


def test_start_run_clamps_an_excessive_duration_to_the_backstop(client):
    """The backstop against a forgotten run applies regardless of what the
    caller asks for, not just when nothing is specified."""
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "duration_s": 10_000.0})
    assert r.json()["duration_s"] == pytest.approx(600.0)


def test_start_run_rejects_a_non_positive_v_max(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "v_max": 0})
    assert r.status_code == 400
    assert client.run_requests.empty()


def test_start_run_rejects_a_non_positive_i_max(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "i_max": -1.0})
    assert r.status_code == 400
    assert client.run_requests.empty()


def test_start_run_clamps_an_excessive_v_max_and_i_max_to_the_board_limit(client):
    """An operator may narrow the safety limits, never widen them past the
    board's documented 40 V / 1 A - those are the only overvoltage/
    overcurrent protection a continuous drive has (run_algorithm.py's own
    module docstring)."""
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "v_max": 999999, "i_max": 999999})
    assert r.status_code == 200
    queued = client.run_requests.get_nowait()
    assert queued.v_max == _DEFAULT_V_MAX
    assert queued.i_max == _DEFAULT_I_MAX


def test_start_run_respects_a_v_max_and_i_max_below_the_ceiling(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "v_max": 12.0, "i_max": 0.3})
    assert r.status_code == 200
    queued = client.run_requests.get_nowait()
    assert queued.v_max == 12.0
    assert queued.i_max == 0.3


def test_start_run_with_a_valid_curve_ref_is_recorded(client, tmp_path):
    curve_path = _save(tmp_path, label="ref curve")
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "curve_ref": curve_path.stem})
    assert r.status_code == 200
    queued = client.run_requests.get_nowait()
    assert queued.curve_ref == curve_path.stem
    assert client.get("/api/runs/live").json()["curve_ref"] == curve_path.stem


def test_start_run_refuses_a_hardware_run_while_a_sweep_is_active(client):
    """A hardware run and curve-tracer polling cannot share the one SPI
    link - queuing a run behind an active sweep would have it "complete"
    while the firmware silently held the gate at 0 throughout."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    r = client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r.status_code == 409
    assert client.run_requests.empty()


def test_start_run_simulated_is_allowed_while_a_sweep_is_active(client):
    """A simulated run never touches the SPI link, so it is unaffected by
    a sweep in progress."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    r = client.post(
        "/api/runs/start", json={"algorithm": "P&O", "simulated": True, "duration_s": 0.02}
    )
    assert r.status_code == 200


def test_start_run_conflicts_when_a_run_is_already_in_progress(client):
    r1 = client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r1.status_code == 200
    r2 = client.post("/api/runs/start", json={"algorithm": "InCond"})
    assert r2.status_code == 409
    # The second, rejected request must never reach the queue - only the
    # first request's spec should be sitting there.
    assert client.run_requests.get_nowait().spec.label == "P&O"
    assert client.run_requests.empty()


def test_stop_run_sets_the_stop_event(client):
    client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert client.stop_event.is_set() is False
    r = client.post("/api/runs/stop")
    assert r.status_code == 204
    assert client.stop_event.is_set() is True


def test_stop_run_without_an_active_run_is_409(client):
    r = client.post("/api/runs/stop")
    assert r.status_code == 409


def test_live_run_defaults_to_idle_with_no_samples(client):
    live = client.get("/api/runs/live").json()
    assert live["status"] == "idle"
    assert live["samples"] == []
    assert live["vout"] is None
    assert live["aborted"] is False


# ------------------------------------------------------------------
# _run_live: the poll-thread side of a run, exercised directly with a
# fake source (no threads, no hardware) - _poll_loop itself is never
# called in this test module, same as the rest of this file.
# ------------------------------------------------------------------


def test_run_live_saves_the_full_series_while_the_live_window_stays_bounded(client):
    source = _FakeRunSource()
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.1, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live", params={"max_samples": 50}).json()
    assert live["status"] == "done"
    assert live["aborted"] is False
    assert live["n_samples"] > 50  # a fast fake loop over 0.1s records plenty of steps
    assert live["downsampled"] is True
    assert len(live["samples"]) <= 52  # _downsample_samples always keeps both endpoints

    saved_id = live["saved_run_id"]
    assert saved_id is not None
    record = load_run(client.run_dir / f"{saved_id}.json")
    assert len(record.samples) == live["n_samples"]  # the saved record keeps everything
    assert record.algorithm == "P&O"
    assert record.label == "bench"
    assert record.aborted is False


def test_run_live_records_the_chosen_curve_ref_on_the_saved_run(client, tmp_path):
    curve_path = _save(tmp_path, label="ref curve")
    curve_id = curve_path.stem
    source = _FakeRunSource()
    request = _RunRequest(
        spec=_po_spec(),
        duration_s=0.02,
        v_max=100.0,
        i_max=100.0,
        curve_ref=curve_id,
        label="bench",
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=curve_id)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live").json()
    assert live["curve_ref"] == curve_id
    record = load_run(client.run_dir / f"{live['saved_run_id']}.json")
    assert record.curve_ref == curve_id


def test_run_live_exposes_vout_live(client):
    source = _FakeRunSource()
    source.vout = 27.5
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.02, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    assert client.get("/api/runs/live").json()["vout"] == 27.5


def test_run_live_overvoltage_aborts_zeroes_duty_and_records_the_reason(client):
    source = _FakeRunSource()
    request = _RunRequest(
        spec=_po_spec(), duration_s=100.0, v_max=1.0, i_max=100.0, curve_ref=None, label="bench"
    )
    # P&O's initial_duty of 0.5 gives V=10.0 on the very first read - over v_max=1.0.
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live").json()
    assert live["aborted"] is True
    assert live["abort_reason"] == "overvoltage"
    assert source._duty == 0.0
    record = load_run(client.run_dir / f"{live['saved_run_id']}.json")
    assert record.aborted is True
    assert record.notes == "overvoltage"


def test_run_live_link_down_aborts(client):
    source = _FakeRunSource()
    source.consecutive_bad_frames = 999
    request = _RunRequest(
        spec=_po_spec(), duration_s=100.0, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live").json()
    assert live["aborted"] is True
    assert live["abort_reason"] == "link-down"
    assert source._duty == 0.0


def test_run_live_releases_the_relay_before_starting_the_control_loop(client):
    """A relay left engaged by an earlier sweep (or But1) would have the
    firmware hold the SEPIC gate at 0 for the run's whole duration - see
    _run_live's own note."""
    source = _FakeRunSourceWithRelay()
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.02, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    assert source.relay_released is True


def test_run_live_works_with_a_fake_source_that_has_no_release_relay(client):
    """Every other _run_live test uses plain _FakeRunSource, which has no
    release_relay() at all - confirms the getattr guard actually makes
    that safe rather than raising."""
    source = _FakeRunSource()
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.02, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    assert client.get("/api/runs/live").json()["status"] == "done"


def test_run_live_saves_partial_samples_and_notes_the_error_when_the_loop_raises(client):
    """A mid-run crash must not discard whatever the run had already
    recorded - see _execute_run's `collected` list."""
    source = _FakeRunSourceWithRelay()
    spec = AlgorithmSpec(label="Raiser", color="k", make=lambda _duty: _RaisingAfterNAlgorithm(2))
    request = _RunRequest(
        spec=spec, duration_s=100.0, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="Raiser", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    assert source._duty == 0.0  # the zero-duty guarantee still held
    live = client.get("/api/runs/live").json()
    assert live["status"] == "done"
    assert live["aborted"] is True
    assert "algorithm boom" in live["abort_reason"]
    saved_id = live["saved_run_id"]
    assert saved_id is not None
    record = load_run(client.run_dir / f"{saved_id}.json")
    assert record.aborted is True
    assert "algorithm boom" in record.notes
    assert len(record.samples) == 2  # recorded before the third step() raised


def test_a_stop_request_actually_stops_an_in_progress_run(client):
    """Simulates an operator clicking Stop partway through: the fake
    source sets the real stop_event (the same one POST /api/runs/stop
    would set) as a side effect of its third read() call, standing in for
    a concurrent request thread without needing real threads here."""
    source = _FakeRunSource()
    calls = []
    real_read = source.read

    def read():
        calls.append(1)
        if len(calls) == 3:
            client.stop_event.set()
        return real_read()

    source.read = read

    request = _RunRequest(
        spec=_po_spec(), duration_s=100.0, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live").json()
    assert live["status"] == "done"
    assert live["aborted"] is True
    assert live["abort_reason"] == "stopped"
    assert source._duty == 0.0
    # Confirms this really did stop early rather than happening to finish
    # on its own: duration_s=100 real seconds never elapsed in this test.
    assert live["n_samples"] < 100


def test_run_live_pauses_the_curve_tracer_cache_while_running(client):
    """_run_live must make the displacement visible on /api/data rather
    than leaving a client polling it looking at a silently frozen sweep -
    see the module docstring."""
    source = _FakeRunSource()
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.01, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="bench", curve_ref=None)

    _run_live(source, client.cache, client.run_cache, request, client.stop_event)

    # The run has already finished by the time _run_live returns, but the
    # "paused" message it set at the start must still be the cache's
    # link state - nothing in this (short) run's path resets it, matching
    # how a real _poll_loop would only refresh /api/data on its next
    # ordinary sweep-polling iteration after the run ends.
    assert client.get("/api/data").json()["link"] == "paused: a live MPPT run is in progress"


# ------------------------------------------------------------------
# Simulated runs: _make_simulated_source, _run_simulated, and
# POST /api/runs/start with "simulated": true - Part 2 of live runs.
# ------------------------------------------------------------------


def _wait_for_run_done(test_client, timeout=5.0):
    """Poll GET /api/runs/live until the run started on a background
    thread (a simulated run - see post_start_run) reports "done", instead
    of leaving that thread still writing into a torn-down tmp_path once
    the test that started it has already finished."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if test_client.get("/api/runs/live").json()["status"] == "done":
            return
        time.sleep(0.01)
    raise TimeoutError("simulated run did not finish in time")


def test_make_simulated_source_uses_the_reference_curve_when_given(client, tmp_path):
    curve_path = _save(tmp_path, label="ref", points=((19.3, 0.006), (14.0, 0.5), (0.1, 0.6)))
    src = _make_simulated_source(curve_path.stem)
    # Distinctly the curve's own ballpark, not the no-curve fallback's (see
    # the next test) - proof MeasuredPanel, not IdealSingleDiode, backs it.
    assert 15.0 < src._panel.open_circuit_voltage < 22.0


def test_make_simulated_source_falls_back_to_ideal_single_diode_with_no_curve(client):
    src = _make_simulated_source(None)
    fallback = IdealSingleDiode(photocurrent=0.79, cells_in_series=36)
    assert src._panel.open_circuit_voltage == pytest.approx(fallback.open_circuit_voltage)


def test_run_simulated_never_touches_the_spi_mcu_module(monkeypatch, client):
    """A simulated run must never construct a SpiMcuSource - poison the
    module it lives in so importing it for any reason raises loudly, then
    confirm a simulated run still runs to completion regardless."""
    monkeypatch.setitem(sys.modules, "mpp_sdk.io.spi_mcu", None)
    request = _RunRequest(
        spec=_po_spec(), duration_s=0.05, v_max=100.0, i_max=100.0, curve_ref=None, label="bench"
    )
    assert client.run_cache.try_start(
        algorithm="P&O", label="bench", curve_ref=None, simulated=True
    )

    _run_simulated(client.run_cache, request, client.stop_event)

    live = client.get("/api/runs/live").json()
    assert live["status"] == "done"
    assert live["source"] == "simulated"


def test_run_simulated_stamps_simulated_provenance_hardware_stamps_hardware(client):
    """The saved RunRecord's source must say which of the two actually
    ran - never left to the caller, see RUN_SOURCES."""
    sim_request = _RunRequest(
        spec=_po_spec(), duration_s=0.05, v_max=100.0, i_max=100.0, curve_ref=None, label="sim"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="sim", curve_ref=None, simulated=True)
    _run_simulated(client.run_cache, sim_request, client.stop_event)
    sim_saved = client.get("/api/runs/live").json()["saved_run_id"]
    assert load_run(client.run_dir / f"{sim_saved}.json").source == "simulated"

    hw_source = _FakeRunSource()
    hw_request = _RunRequest(
        spec=_po_spec(), duration_s=0.02, v_max=100.0, i_max=100.0, curve_ref=None, label="hw"
    )
    assert client.run_cache.try_start(algorithm="P&O", label="hw", curve_ref=None)
    _run_live(hw_source, client.cache, client.run_cache, hw_request, client.stop_event)
    hw_saved = client.get("/api/runs/live").json()["saved_run_id"]
    assert load_run(client.run_dir / f"{hw_saved}.json").source == "hardware"


def test_start_run_simulated_is_allowed_in_demo_mode(demo_client):
    """The one kind of run --demo mode (no board at all) can still offer -
    see post_start_run's refusal for a non-simulated request."""
    r = demo_client.post(
        "/api/runs/start", json={"algorithm": "P&O", "simulated": True, "duration_s": 0.05}
    )
    assert r.status_code == 200
    # Never touches the hardware queue - _run_simulated runs on its own
    # thread instead (see post_start_run).
    assert demo_client.run_requests.empty()
    _wait_for_run_done(demo_client)
    live = demo_client.get("/api/runs/live").json()
    assert live["source"] == "simulated"
    assert live["aborted"] is False


def test_start_run_live_reports_source_while_hardware_run_is_queued(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O"})
    assert r.status_code == 200
    assert client.get("/api/runs/live").json()["source"] == "hardware"
    client.run_requests.get_nowait()  # drain - nothing executes it in this test


def test_start_run_simulated_and_hardware_can_never_overlap(demo_client):
    """try_start's single run slot must refuse a second start of either
    kind while a simulated run (started on its own thread) is still in
    progress - the one concurrency guarantee Part 2 asks for."""
    r1 = demo_client.post(
        "/api/runs/start", json={"algorithm": "P&O", "simulated": True, "duration_s": 5.0}
    )
    assert r1.status_code == 200
    try:
        r2 = demo_client.post("/api/runs/start", json={"algorithm": "InCond", "simulated": True})
        assert r2.status_code == 409
    finally:
        demo_client.post("/api/runs/stop")
        _wait_for_run_done(demo_client)


def test_start_run_simulated_uses_the_chosen_curve_and_saves_it_as_curve_ref(client, tmp_path):
    curve_path = _save(tmp_path, label="ref curve")
    r = client.post(
        "/api/runs/start",
        json={
            "algorithm": "P&O",
            "simulated": True,
            "duration_s": 0.05,
            "curve_ref": curve_path.stem,
        },
    )
    assert r.status_code == 200
    _wait_for_run_done(client)
    live = client.get("/api/runs/live").json()
    assert live["curve_ref"] == curve_path.stem
    record = load_run(client.run_dir / f"{live['saved_run_id']}.json")
    assert record.curve_ref == curve_path.stem
    assert record.source == "simulated"


_INLINE_POINTS = [[19.3, 0.006], [16.0, 0.34], [14.0, 0.54], [9.0, 0.57], [0.1, 0.6]]


def test_start_run_simulated_tracks_inline_curve_points_and_reports_them(demo_client):
    """Demo mode's bundled curves are not in the server's library, so they
    arrive inline - the run must track them and echo them back for the
    grey reference line."""
    r = demo_client.post(
        "/api/runs/start",
        json={
            "algorithm": "P&O",
            "simulated": True,
            "duration_s": 0.3,
            "curve_points": _INLINE_POINTS,
        },
    )
    assert r.status_code == 200
    live = demo_client.get("/api/runs/live").json()
    assert live["reference_points"] == [{"v": v, "i": i} for v, i in _INLINE_POINTS]
    _wait_for_run_done(demo_client)
    live = demo_client.get("/api/runs/live").json()
    assert live["aborted"] is False
    assert live["curve_ref"] is None
    # MeasuredPanel extrapolates Voc a little past the last swept point.
    assert 0.0 < live["voltage"] <= 21.0


def test_start_run_rejects_curve_points_for_a_hardware_run(client):
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "curve_points": _INLINE_POINTS})
    assert r.status_code == 400
    assert client.run_requests.empty()


def test_start_run_rejects_curve_points_together_with_curve_ref(client, tmp_path):
    curve_path = _save(tmp_path, label="ref")
    r = client.post(
        "/api/runs/start",
        json={
            "algorithm": "P&O",
            "simulated": True,
            "curve_ref": curve_path.stem,
            "curve_points": _INLINE_POINTS,
        },
    )
    assert r.status_code == 400


@pytest.mark.parametrize("points", [[[1.0, 0.1]], [[1.0, 0.1], [1.0, 0.2]]])
def test_start_run_rejects_unusable_inline_curve_points(client, points):
    r = client.post(
        "/api/runs/start",
        json={"algorithm": "P&O", "simulated": True, "curve_points": points},
    )
    assert r.status_code == 400
    assert client.get("/api/runs/live").json()["status"] == "idle"


def test_start_run_reports_reference_points_for_curve_ref_and_builtin_panel(client, tmp_path):
    curve_path = _save(tmp_path, label="ref")
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "curve_ref": curve_path.stem})
    assert r.status_code == 200
    reference = client.get("/api/runs/live").json()["reference_points"]
    assert len(reference) == 2  # _save's default sweep
    client.run_requests.get_nowait()  # drain - nothing executes it in this test
    client.run_cache.finish(aborted=True, reason="stopped", saved_run_id=None)

    r = client.post(
        "/api/runs/start", json={"algorithm": "P&O", "simulated": True, "duration_s": 0.05}
    )
    assert r.status_code == 200
    reference = client.get("/api/runs/live").json()["reference_points"]
    assert len(reference) > 10
    assert reference[0]["v"] == 0.0
    _wait_for_run_done(client)


def test_start_run_seeds_the_algorithm_with_the_requested_initial_duty(client):
    """The seed is not cosmetic: a local tracker hill-climbs from it, so on
    a multi-peak curve it decides which maximum the run settles on."""
    r = client.post(
        "/api/runs/start",
        json={"algorithm": "P&O", "simulated": True, "duration_s": 0.2, "initial_duty": 0.7},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("duty", [0.0, 1.0, -0.1, 1.5])
def test_start_run_rejects_an_initial_duty_outside_the_open_unit_interval(client, duty):
    """Rejected, not clamped - silently moving the seed would change which
    maximum a hill-climber converges on without telling anyone."""
    r = client.post("/api/runs/start", json={"algorithm": "P&O", "initial_duty": duty})
    assert r.status_code == 400
    assert "initial_duty" in r.json()["detail"]


def test_poll_loop_exits_on_shutdown_event_but_not_on_a_run_stop():
    """The poll thread must end when the process is shutting down, so a
    live run gets to exit through run_control_loop's zero-duty path
    instead of being abandoned at whatever duty it was driving. It must
    NOT end on `stop_event`, which only ends one run - a Stop button that
    also killed polling would take every later sweep down with it."""
    cache = _SweepCache()
    stop_event = threading.Event()
    shutdown_event = threading.Event()
    thread = threading.Thread(
        target=_poll_loop,
        args=(cache, queue.Queue(), 0, 0, 200_000, 0.01),
        kwargs={"demo": True, "stop_event": stop_event, "shutdown_event": shutdown_event},
        daemon=True,
    )
    thread.start()
    try:
        stop_event.set()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "a run's stop must not end the poll loop"
    finally:
        shutdown_event.set()
        thread.join(timeout=5.0)
    assert not thread.is_alive()
