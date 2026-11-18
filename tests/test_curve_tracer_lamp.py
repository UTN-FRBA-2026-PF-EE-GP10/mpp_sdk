"""Lamp dimmer routes of the curve-tracer server, with a fake source (no hardware)."""

import json
import queue
import threading
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import scripts.curve_tracer.poll as poll_module  # noqa: E402
from mpp_sdk.io.dimmer import DimmerRefused, DimmerStatus  # noqa: E402
from mpp_sdk.io.dimmer_sim import SimulatedDimmer  # noqa: E402
from scripts.curve_tracer.lamp import _LampController, _LampHolder  # noqa: E402
from scripts.curve_tracer_server import (  # noqa: E402
    _LiveRunCache,
    _poll_loop,
    _SweepCache,
    create_app,
)

KEYS = {
    "available", "state", "power", "alpha_deg", "applied_alpha_deg", "window_left_s",
    "max_on_s", "budget_s", "tripped", "mains", "locked", "timed_out", "link_ok",
    "max_power", "error",
}  # fmt: skip


class FakeLampSource:
    def __init__(self):
        self.calls = []
        self.alpha = None
        self.window = None
        self.link_ok = True
        self.tripped = False
        self.budget_s = 120
        self.refuse = False
        self.set_error = None
        self.status_error = None
        self.off_error = None
        self.status_none = False
        self.frozen_window = None
        self.status_hook = None
        self.link_down_threads = set()

    def set_dimmer_power(self, power, *, max_on_s):
        self.calls.append(("power", power, max_on_s))
        self._set(90.0, max_on_s)

    def set_dimmer_alpha(self, alpha, *, max_on_s):
        self.calls.append(("alpha", alpha, max_on_s))
        self._set(alpha, max_on_s)

    def _set(self, alpha, max_on_s):
        if self.refuse:
            raise DimmerRefused("refused by dimmer")
        if self.set_error:
            raise self.set_error
        self.alpha, self.window = alpha, max_on_s

    def dimmer_off(self):
        self.calls.append(("off",))
        if self.off_error:
            raise self.off_error
        self.alpha = self.window = None

    def dimmer_window_left_s(self):
        if self.frozen_window is not None and threading.current_thread().name == "refresher":
            return self.frozen_window
        return self.window

    def dimmer_status(self):
        if self.status_error:
            raise self.status_error
        if self.status_none:
            return None
        link_ok = self.link_ok and threading.current_thread().name not in self.link_down_threads
        if self.tripped and self.alpha is not None:
            self.dimmer_off()  # the acknowledgment of the Python layer
        status = DimmerStatus(
            link_ok=link_ok,
            mains=True,
            locked=True,
            timed_out=False,
            set_alpha_deg=self.alpha if self.alpha is not None else 180.0,
            applied_alpha_deg=self.alpha,
            age_s=0.1,
            tripped=self.tripped,
            budget_s=self.budget_s,
        )
        if self.status_hook is not None:
            self.status_hook()
        return status


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make_client(source=None, *, max_power=1.0, clock=None):
    holder = _LampHolder()
    if source is not None:
        holder.set(source)
    kwargs = {"clock": clock} if clock else {}
    lamp = _LampController(holder, max_power=max_power, refresh_s=3600.0, **kwargs)
    app = create_app(_SweepCache(), queue.Queue(), lamp=lamp)
    return TestClient(app), lamp, holder


@pytest.fixture
def source():
    return FakeLampSource()


def test_get_with_no_board_is_unavailable_with_every_key():
    with make_client()[0] as client:
        body = client.get("/api/dimmer").json()
    assert set(body) == KEYS
    assert body["state"] == "unavailable" and body["available"] is False
    assert body["error"] and body["max_on_s"] == 120 and body["max_power"] == 1.0


def test_post_power_returns_the_status_object(source):
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5, "max_on_s": 20})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == KEYS
        assert body["state"] == "on" and body["window_left_s"] == 20
        assert body["power"] is not None and body["error"] is None
        assert source.calls[0] == ("power", 0.5, 20.0)
        # The page polls the cache, which the command refreshed.
        assert client.get("/api/dimmer").json()["state"] == "on"


def test_post_alpha_and_default_window(source):
    client, _, _ = make_client(source)
    with client:
        assert client.post("/api/dimmer", json={"alpha_deg": 60}).status_code == 200
    assert source.calls[0] == ("alpha", 60, 30.0)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"power": 0.5, "alpha_deg": 60},
        {"power": 1.01},
        {"power": -0.1},
        {"power": True},
        {"power": "0.5"},
        {"power": float("nan")},
        {"alpha_deg": 181},
        {"alpha_deg": -1},
        {"alpha_deg": False},
        {"power": 0.5, "max_on_s": 0},
        {"power": 0.5, "max_on_s": -5},
        {"power": 0.5, "max_on_s": 120.5},
        {"power": 0.5, "max_on_s": True},
        {"power": 0.5, "max_on_s": float("nan")},
    ],
)
def test_invalid_bodies_are_422_and_never_reach_the_source(source, body):
    client, _, _ = make_client(source)
    with client:
        # A bare NaN literal (what a JS client could not send but curl can) must be rejected.
        raw = json.dumps(body, allow_nan=True)
        resp = client.post("/api/dimmer", content=raw, headers={"content-type": "application/json"})
        assert resp.status_code == 422
        assert source.calls == []


def test_max_on_s_of_exactly_120_is_accepted(source):
    client, _, _ = make_client(source)
    with client:
        assert client.post("/api/dimmer", json={"power": 1, "max_on_s": 120}).status_code == 200


def test_power_above_the_server_cap_is_422(source):
    client, _, _ = make_client(source, max_power=0.4)
    with client:
        assert client.get("/api/dimmer").json()["max_power"] == 0.4
        assert client.post("/api/dimmer", json={"power": 0.41}).status_code == 422
        assert client.post("/api/dimmer", json={"power": 0.4}).status_code == 200


@pytest.mark.parametrize("body", [{"power": 0}, {"alpha_deg": 180}])
def test_power_zero_and_alpha_180_mean_off(source, body):
    client, _, _ = make_client(source)
    with client:
        client.post("/api/dimmer", json={"power": 0.5})
        resp = client.post("/api/dimmer", json=body)
    assert resp.status_code == 200 and resp.json()["state"] == "off"
    assert source.calls[-1] == ("off",)


def test_tripped_dimmer_is_409_and_state_shows_tripped(source):
    source.tripped, source.budget_s = True, 42
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5})
        assert resp.status_code == 409 and "42" in resp.json()["detail"]
        body = client.get("/api/dimmer").json()
    assert body["state"] == "tripped" and body["tripped"] is True and body["budget_s"] == 42
    assert source.alpha is None  # the acknowledgment OFF was sent


def test_state_stays_tripped_until_the_dimmer_reports_it_cleared(source):
    client, lamp, _ = make_client(source)
    with client:
        client.post("/api/dimmer", json={"power": 0.5})
        source.tripped = True
        lamp.refresh_once()
        assert client.get("/api/dimmer").json()["state"] == "tripped"
        lamp.refresh_once()  # the lamp is already off, state still tripped
        assert client.get("/api/dimmer").json()["state"] == "tripped"
        source.tripped = False
        lamp.refresh_once()
        assert client.get("/api/dimmer").json()["state"] == "off"


def test_dimmer_refused_is_409_with_the_reason(source):
    source.refuse = True
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5})
    assert resp.status_code == 409 and "refused by dimmer" in resp.json()["detail"]


def test_on_with_no_board_is_503():
    client, _, _ = make_client()
    with client:
        assert client.post("/api/dimmer", json={"power": 0.5}).status_code == 503


def test_on_with_unconfirmed_link_is_503_and_switches_off(source, monkeypatch):
    monkeypatch.setattr("scripts.curve_tracer.lamp._CONFIRM_S", 0.0)
    source.link_ok = False
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5})
    assert resp.status_code == 503
    assert source.calls[-1] == ("off",) and source.alpha is None


def test_on_when_the_command_fails_is_503_and_switches_off(source):
    source.set_error = OSError("spi gone")
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5})
    assert resp.status_code == 503 and "spi gone" in resp.json()["detail"]
    assert ("off",) in source.calls


def test_off_never_fails_with_no_board():
    client, _, _ = make_client()
    with client:
        resp = client.post("/api/dimmer/off")
    assert resp.status_code == 200 and resp.json()["state"] == "unavailable"


def test_off_with_unknown_link_still_sends_off(source):
    source.link_ok = False
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer/off")
        assert source.calls == [("off",)]
    assert resp.status_code == 200 and resp.json()["state"] == "unavailable"
    body = resp.json()
    assert body["budget_s"] is None and body["tripped"] is None and body["mains"] is None


def test_off_failure_is_200_with_an_error_after_retries(source):
    source.off_error = OSError("spi gone")
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer/off")
        assert source.calls.count(("off",)) == 3
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "unavailable" and "spi gone" in body["error"]


def test_off_is_idempotent(source):
    client, _, _ = make_client(source)
    with client:
        a = client.post("/api/dimmer/off").json()
        b = client.post("/api/dimmer/off").json()
    assert a == b and a["state"] == "off"


def test_status_older_than_3_s_is_unavailable_not_the_last_on(source):
    clock = Clock()
    client, lamp, _ = make_client(source, clock=clock)
    with client:
        client.post("/api/dimmer", json={"power": 0.5, "max_on_s": 60})
        clock.t += 1.0
        body = client.get("/api/dimmer").json()
        assert body["state"] == "on" and body["window_left_s"] == pytest.approx(59.0)
        clock.t += 2.5
        body = client.get("/api/dimmer").json()
    assert body["state"] == "unavailable" and "stale" in body["error"]
    assert body["window_left_s"] is None and body["power"] is None


def test_failed_refresh_is_unavailable_with_an_error(source):
    client, lamp, _ = make_client(source)
    with client:
        client.post("/api/dimmer", json={"power": 0.5})
        source.status_error = OSError("link down")
        lamp.refresh_once()
        body = client.get("/api/dimmer").json()
    assert body["state"] == "unavailable" and "link down" in body["error"]
    assert body["available"] is True


def test_unreadable_status_is_unavailable(source):
    client, lamp, _ = make_client(source)
    with client:
        source.status_none = True
        lamp.refresh_once()
        assert client.get("/api/dimmer").json()["state"] == "unavailable"


def test_get_never_touches_the_source(source):
    client, lamp, _ = make_client(source)
    with client:
        lamp.refresh_once()
        source.calls.clear()
        source.status_error = AssertionError("GET must not read the source")
        for _ in range(3):
            assert client.get("/api/dimmer").json()["state"] == "off"
        assert source.calls == []


def test_refresh_thread_runs_with_the_app(source):
    holder = _LampHolder()
    holder.set(source)
    lamp = _LampController(holder, refresh_s=0.05)
    with TestClient(create_app(_SweepCache(), queue.Queue(), lamp=lamp)) as client:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if client.get("/api/dimmer").json()["state"] == "off":
                break
            time.sleep(0.02)
        assert client.get("/api/dimmer").json()["state"] == "off"


def test_shutdown_switches_the_lamp_off(source):
    client, _, _ = make_client(source)
    with client:
        client.post("/api/dimmer", json={"power": 0.5})
        assert source.alpha is not None
    # Leaving the TestClient ends the app lifespan, as SIGTERM and Ctrl-C do.
    assert source.alpha is None and source.calls[-1] == ("off",)


def test_shutdown_retries_a_failing_off(source):
    source.off_error = OSError("x")
    client, _, _ = make_client(source)
    with client:
        pass
    assert source.calls.count(("off",)) == 3


def test_lamp_commands_are_not_refused_during_a_run(source):
    holder = _LampHolder()
    holder.set(source)
    app = create_app(
        _SweepCache(),
        queue.Queue(),
        lamp=_LampController(holder, refresh_s=3600.0),
    )
    with TestClient(app) as client:
        assert client.post("/api/dimmer", json={"power": 0.5}).status_code == 200


class _FakeBoard(FakeLampSource):
    """A SpiMcuSource stand-in for the poll loop."""

    consecutive_bad_frames = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.calls.append(("closed",))

    def request_sweep(self):
        return None

    def poll_sweep_progress(self):
        return None


def test_off_acts_while_a_run_occupies_the_poll_thread(monkeypatch):
    board = _FakeBoard()
    monkeypatch.setattr("mpp_sdk.io.spi_mcu.SpiMcuSource", lambda **_kw: board)
    run_started, release = threading.Event(), threading.Event()

    def long_run(*_args):
        run_started.set()
        release.wait(30.0)

    monkeypatch.setattr(poll_module, "_run_live", long_run)
    holder = _LampHolder()
    lamp = _LampController(holder, refresh_s=3600.0)
    run_requests = queue.Queue()
    run_requests.put(object())
    shutdown = threading.Event()
    thread = threading.Thread(
        target=_poll_loop,
        args=(_SweepCache(), queue.Queue(), 0, 0, 1000, 0.01),
        kwargs={
            "run_requests": run_requests,
            "run_cache": _LiveRunCache(),
            "shutdown_event": shutdown,
            "stop_event": threading.Event(),
            "lamp_holder": holder,
        },
        daemon=True,
    )
    thread.start()
    try:
        assert run_started.wait(5.0)
        assert holder.get() is board  # published once the source exists
        app = create_app(_SweepCache(), queue.Queue(), lamp=lamp)
        with TestClient(app) as client:
            assert client.post("/api/dimmer", json={"power": 0.5}).status_code == 200
            start = time.monotonic()
            resp = client.post("/api/dimmer/off")
            assert time.monotonic() - start < 1.0
            assert resp.json()["state"] == "off" and board.alpha is None
    finally:
        release.set()
        shutdown.set()
        thread.join(5.0)
    assert holder.get() is None  # withdrawn before the source closed
    assert ("closed",) in board.calls


def test_demo_poll_loop_publishes_a_simulated_dimmer():
    holder = _LampHolder()
    shutdown = threading.Event()
    thread = threading.Thread(
        target=_poll_loop,
        args=(_SweepCache(), queue.Queue(), 0, 0, 1000, 0.01),
        kwargs={"demo": True, "shutdown_event": shutdown, "lamp_holder": holder},
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while holder.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert isinstance(holder.get(), SimulatedDimmer)
    finally:
        shutdown.set()
        thread.join(5.0)


def test_demo_simulator_through_the_routes_trips_and_returns_409():
    now = [1000.0]
    sim = SimulatedDimmer(lambda: now[0])
    holder = _LampHolder()
    holder.set(sim)
    lamp = _LampController(holder, refresh_s=3600.0)
    with TestClient(create_app(_SweepCache(), queue.Queue(), lamp=lamp)) as client:
        assert client.post("/api/dimmer", json={"power": 1, "max_on_s": 120}).status_code == 200
        now[0] += 120.0
        lamp.refresh_once()
        body = client.get("/api/dimmer").json()
        assert body["state"] == "tripped" and body["budget_s"] == 60
        assert client.post("/api/dimmer", json={"power": 1}).status_code == 409
        now[0] += 61.0
        assert client.post("/api/dimmer/off").json()["state"] == "off"
        assert client.post("/api/dimmer", json={"power": 1, "max_on_s": 5}).status_code == 200


@pytest.mark.parametrize("text", ["0", "-0.1", "1.5", "nan", "inf"])
def test_lamp_max_power_option_rejects_out_of_range(text):
    import argparse

    from scripts.curve_tracer_server import _lamp_max_power

    with pytest.raises(argparse.ArgumentTypeError):
        _lamp_max_power(text)


def test_lamp_max_power_option_accepts_a_fraction():
    from scripts.curve_tracer_server import _lamp_max_power

    assert _lamp_max_power("0.5") == 0.5 and _lamp_max_power("1") == 1.0


class _SlowHolder(_LampHolder):
    """Delays `get()` for the thread named "late-on", so an ON can be late to the source."""

    def __init__(self, delay_s):
        super().__init__()
        self.delay_s = delay_s

    def get(self):
        if threading.current_thread().name == "late-on":
            time.sleep(self.delay_s)
        return super().get()


def _holder_with(source):
    holder = _LampHolder()
    holder.set(source)
    return holder


def test_a_late_on_cannot_follow_an_off(source):
    holder = _SlowHolder(0.3)
    holder.set(source)
    lamp = _LampController(holder, refresh_s=3600.0)
    result = {}

    def late_on():
        try:
            result["on"] = lamp.on(power=0.5, alpha_deg=None, max_on_s=60.0)
        except Exception as exc:
            result["on"] = exc

    thread = threading.Thread(target=late_on, name="late-on")
    thread.start()
    time.sleep(0.1)
    assert lamp.off()["state"] == "off"
    thread.join(5.0)
    assert getattr(result["on"], "status_code", None) == 409
    assert "Off" in result["on"].detail
    # OFF is the last frame on the wire and the lamp stays off.
    assert source.calls[-1] == ("off",) and ("power", 0.5, 60.0) not in source.calls
    assert source.alpha is None and lamp.snapshot()["state"] == "off"
    # An ON after the completed OFF still works.
    assert lamp.on(power=0.5, alpha_deg=None, max_on_s=60.0)["state"] == "on"
    assert source.alpha is not None and lamp.snapshot()["state"] == "on"


def test_off_during_the_link_confirmation_wins(source):
    # The OFF arrives after the set command, while the ON waits for the link.
    started = threading.Event()
    release = threading.Event()

    def hook():
        if threading.current_thread().name == "slow-on":
            started.set()
            release.wait(5.0)

    source.status_hook = hook
    lamp = _LampController(_holder_with(source), refresh_s=3600.0)
    result = {}

    def slow_on():
        try:
            result["on"] = lamp.on(power=0.5, alpha_deg=None, max_on_s=60.0)
        except Exception as exc:
            result["on"] = exc

    thread = threading.Thread(target=slow_on, name="slow-on")
    thread.start()
    assert started.wait(5.0)
    assert lamp.off()["state"] == "off"
    release.set()
    thread.join(5.0)
    assert getattr(result["on"], "status_code", None) == 409
    assert source.calls[-1] == ("off",) and source.alpha is None
    assert lamp.snapshot()["state"] == "off"


def test_a_failing_on_does_not_switch_off_a_newer_on(source, monkeypatch):
    monkeypatch.setattr("scripts.curve_tracer.lamp._CONFIRM_S", 0.4)
    source.link_down_threads = {"first-on"}
    lamp = _LampController(_holder_with(source), refresh_s=3600.0)
    result = {}

    def first_on():
        try:
            lamp.on(power=0.3, alpha_deg=None, max_on_s=60.0)
        except Exception as exc:
            result["first"] = exc

    thread = threading.Thread(target=first_on, name="first-on")
    thread.start()
    time.sleep(0.1)
    assert lamp.on(power=0.6, alpha_deg=None, max_on_s=60.0)["state"] == "on"
    thread.join(5.0)
    assert getattr(result["first"], "status_code", None) == 503
    assert source.calls[-1][0] == "power" and source.alpha is not None
    assert lamp.snapshot()["state"] == "on"


def test_an_older_status_read_does_not_overwrite_a_newer_one(source):
    lamp = _LampController(_holder_with(source), refresh_s=3600.0)
    lamp.on(power=0.5, alpha_deg=None, max_on_s=60.0)
    started, release = threading.Event(), threading.Event()
    source.frozen_window = 30.0  # the refresh sees "on" even after the OFF

    def hook():
        if threading.current_thread().name == "refresher":
            started.set()
            release.wait(5.0)

    source.status_hook = hook
    thread = threading.Thread(target=lamp.refresh_once, name="refresher")
    thread.start()
    assert started.wait(5.0)
    assert lamp.off()["state"] == "off"
    release.set()
    thread.join(5.0)
    assert lamp.snapshot()["state"] == "off"


def test_a_value_error_from_the_source_is_503_and_switches_off(source):
    source.set_error = ValueError("bad alpha")
    client, _, _ = make_client(source)
    with client:
        resp = client.post("/api/dimmer", json={"power": 0.5})
        assert source.calls.count(("off",)) == 1
    assert resp.status_code == 503 and "bad alpha" in resp.json()["detail"]


def test_a_huge_integer_is_422(source):
    client, _, _ = make_client(source)
    with client:
        raw = '{"power": 1' + "0" * 400 + "}"
        resp = client.post("/api/dimmer", content=raw, headers={"content-type": "application/json"})
        assert resp.status_code == 422
        assert source.calls == []


def test_alpha_is_capped_like_power(source):
    client, _, _ = make_client(source, max_power=0.5)
    with client:
        assert client.post("/api/dimmer", json={"alpha_deg": 0}).status_code == 422
        assert client.post("/api/dimmer", json={"alpha_deg": 89}).status_code == 422
        assert source.calls == []
        # 90 degrees gives exactly half power: at the cap is allowed.
        assert client.post("/api/dimmer", json={"alpha_deg": 90}).status_code == 200
        assert client.post("/api/dimmer", json={"alpha_deg": 91}).status_code == 200
        # 180 degrees is OFF, always allowed.
        resp = client.post("/api/dimmer", json={"alpha_deg": 180})
        assert resp.status_code == 200 and resp.json()["state"] == "off"


def test_alpha_at_the_cap_for_a_general_power(source):
    from mpp_sdk.io.dimmer import alpha_for_power

    client, _, _ = make_client(source, max_power=0.37)
    with client:
        alpha = alpha_for_power(0.37)
        assert client.post("/api/dimmer", json={"alpha_deg": alpha}).status_code == 200
        assert client.post("/api/dimmer", json={"alpha_deg": alpha - 0.5}).status_code == 422
