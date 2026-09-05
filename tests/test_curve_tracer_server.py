"""Unit tests for scripts/curve_tracer_server.py's FastAPI routes.

`fastapi` (and its `httpx2`-backed `TestClient`) live behind the optional
``[web]`` extra - skip cleanly if it isn't installed, same convention this
repo already uses for pvlib-dependent tests. No hardware/`spidev` needed:
`create_app()` takes a `_SweepCache`/command queue directly, and only
`_poll_loop` (never called here) touches `SpiMcuSource`.
"""

import queue
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mpp_sdk.curves import CurveRecord, PanelSetup, save  # noqa: E402
from mpp_sdk.curves.record import now_utc  # noqa: E402
from scripts.curve_tracer_server import _SweepCache, create_app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient against a fresh, hardware-free app: `default_dir()`
    (via `MPP_SDK_CURVE_DIR`) points at an isolated tmp_path, and the
    returned `cache` lets a test drive `/api/data` directly, the same way
    `_poll_loop` would."""
    monkeypatch.setenv("MPP_SDK_CURVE_DIR", str(tmp_path))
    cache = _SweepCache()
    commands: queue.Queue[str] = queue.Queue()
    app = create_app(cache, commands)
    with TestClient(app) as test_client:
        test_client.cache = cache  # type: ignore[attr-defined]
        test_client.commands = commands  # type: ignore[attr-defined]
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


# ------------------------------------------------------------------
# GET /api/measurement-kinds
# ------------------------------------------------------------------


def test_measurement_kinds_returns_the_seed_vocabulary(client):
    r = client.get("/api/measurement-kinds")
    assert r.status_code == 200
    assert "baseline" in r.json()
    assert "partial-shade" in r.json()


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


def test_curves_reports_a_malformed_file_without_failing_the_whole_list(client, tmp_path):
    (tmp_path / "bad.json").write_text("not json")
    _save(tmp_path, label="good")
    entries = client.get("/api/curves").json()
    by_label_or_error = {e.get("label", e.get("error")) for e in entries}
    assert "good" in by_label_or_error
    assert any("error" in e for e in entries)


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
