"""The `lamp` option of sweep and run requests: lamp on only around the measurement.

Fake lamp source, no hardware. Times are real but short (warm-ups of a few tenths
of a second)."""

import queue
import threading
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import scripts.curve_tracer.cache as cache_module  # noqa: E402
import scripts.curve_tracer.routes_hardware as hardware_module  # noqa: E402
from mpp_sdk.io.dimmer_sim import SimulatedDimmer  # noqa: E402
from scripts.curve_tracer.lamp import _LampController, _LampHolder  # noqa: E402
from scripts.curve_tracer.lamp_step import _LampStepRunner  # noqa: E402
from scripts.curve_tracer_server import (  # noqa: E402
    _LiveRunCache,
    _poll_loop,
    _SweepCache,
    create_app,
)
from tests.test_curve_tracer_lamp import FakeLampSource  # noqa: E402


class Rig:
    def __init__(self, source, tmp_path, monkeypatch, *, max_power=1.0, demo=True):
        monkeypatch.setenv("MPP_SDK_RUN_DIR", str(tmp_path / "runs"))
        monkeypatch.setenv("MPP_SDK_CURVE_DIR", str(tmp_path / "curves"))
        monkeypatch.setenv("MPP_SDK_PANEL_DIR", str(tmp_path / "panels"))
        monkeypatch.setenv("MPP_SDK_SESSION_DIR", str(tmp_path / "sessions"))
        self.source = source
        self.holder = _LampHolder()
        if source is not None:
            self.holder.set(source)
        self.lamp = _LampController(self.holder, max_power=max_power, refresh_s=3600.0)
        self.cache = _SweepCache()
        self.commands: queue.Queue = queue.Queue()
        self.run_cache = _LiveRunCache()
        self.run_requests: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        app = create_app(
            self.cache,
            self.commands,
            demo=demo,
            run_cache=self.run_cache,
            run_requests=self.run_requests,
            stop_event=self.stop_event,
            lamp=self.lamp,
        )
        self.client = TestClient(app)

    @staticmethod
    def run_body(**kw):
        return {
            "algorithm": "P&O",
            "simulated": True,
            "duration_s": 0.4,
            "lamp": {"power": 0.3, "warmup_s": 0.2},
            **kw,
        }

    def phase(self, what="run"):
        url = "/api/data" if what == "sweep" else "/api/runs/live"
        return self.client.get(url).json()["lamp_phase"]

    def run_status(self):
        return self.run_cache.snapshot(0)["status"]


@pytest.fixture
def make(tmp_path, monkeypatch):
    rigs = []

    def build(source="default", **kw):
        src = FakeLampSource() if source == "default" else source
        r = Rig(src, tmp_path, monkeypatch, **kw)
        r.client.__enter__()
        rigs.append(r)
        return r

    yield build
    for r in rigs:
        r.client.__exit__(None, None, None)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def lamp_off(r):
    return r.source.alpha is None


def offs(r):
    return [c for c in r.source.calls if c == ("off",)]


def untouched(r):
    assert r.source.calls == []
    assert r.commands.empty() and r.run_requests.empty()
    assert r.run_status() == "idle"
    assert not r.cache.sweep_pending()


# -- refusals: nothing started, the lamp untouched -----------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"duration_s": 103, "lamp": {"power": 0.3}},  # 3 + 103 + 5 = 111 > 110
        {"duration_s": 90, "lamp": {"power": 0.3, "warmup_s": 30}},
        {"lamp": {"power": 0.3, "warmup_s": 31}},
        {"lamp": {"power": 0.3, "alpha_deg": 60}},
        {"lamp": {"power": 0}},
        {"lamp": {"alpha_deg": 180}},
        {"lamp": {}},
    ],
)
def test_run_refusals_422(make, kw):
    r = make()
    resp = r.client.post("/api/runs/start", json=r.run_body(**kw))
    assert resp.status_code == 422
    untouched(r)


def test_422_message_states_the_limit_and_the_numbers(make):
    r = make()
    resp = r.client.post("/api/runs/start", json=r.run_body(duration_s=103, lamp={"power": 0.3}))
    text = resp.json()["detail"]
    assert "111" in text and "110" in text and "103" in text and "warm-up 3" in text


def test_power_above_the_cap_is_422(make):
    r = make(max_power=0.4)
    assert r.client.post("/api/runs/start", json=r.run_body(lamp={"power": 0.5})).status_code == 422
    untouched(r)
    assert r.client.post("/api/start-sweep", json={"lamp": {"alpha_deg": 0}}).status_code == 422
    untouched(r)


def test_run_409_when_tripped(make):
    src = FakeLampSource()
    src.tripped, src.budget_s = True, 42
    r = make(src)
    resp = r.client.post("/api/runs/start", json=r.run_body())
    assert resp.status_code == 409 and "42" in resp.json()["detail"]
    untouched(r)


def test_run_and_sweep_409_when_budget_is_too_small(make):
    src = FakeLampSource()
    src.budget_s = 5
    r = make(src)
    resp = r.client.post("/api/runs/start", json=r.run_body())  # needs 0.2 + 0.4 + 5
    assert resp.status_code == 409 and "wait" in resp.json()["detail"]
    untouched(r)
    resp = r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3}})  # needs 3 + 15 + 5
    assert resp.status_code == 409
    untouched(r)


def test_503_without_a_confirmed_link(make):
    src = FakeLampSource()
    src.link_ok = False
    r = make(src)
    assert r.client.post("/api/runs/start", json=r.run_body()).status_code == 503
    untouched(r)
    assert r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3}}).status_code == 503
    untouched(r)


def test_503_with_no_board(make):
    r = make(None)
    assert r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3}}).status_code == 503
    assert r.commands.empty()


def test_sweep_422_when_total_too_long(make, monkeypatch):
    r = make()
    monkeypatch.setattr(hardware_module, "_SWEEP_PENDING_TIMEOUT_S", 80.0)  # 30 + 80 + 5
    resp = r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 30}})
    assert resp.status_code == 422 and "115" in resp.json()["detail"]
    untouched(r)


def test_no_body_sweep_still_works_and_never_touches_the_lamp(make):
    r = make()
    assert r.client.post("/api/start-sweep").status_code == 204
    assert r.commands.get_nowait() == "start_sweep"
    assert r.client.post("/api/start-sweep", json={}).status_code == 204
    assert r.source.calls == []
    assert r.phase("sweep") is None


# -- the run: phases, record, every end path ----------------------------------------


def saved_run(r):
    return r.client.get("/api/runs/" + r.run_cache.snapshot(0)["saved_run_id"]).json()


def test_run_phases_record_and_lamp_off_at_the_end(make):
    r = make()
    assert r.phase() is None
    resp = r.client.post("/api/runs/start", json=r.run_body(duration_s=0.5))
    assert resp.status_code == 200
    live = r.client.get("/api/runs/live").json()
    assert live["lamp_phase"] == "warming" and 0 < live["lamp_warmup_left_s"] <= 0.2
    assert r.source.calls[0][0] == "power" and not lamp_off(r)
    assert wait_for(lambda: r.phase() == "measuring")
    assert r.client.get("/api/runs/live").json()["lamp_warmup_left_s"] is None
    assert wait_for(lambda: r.run_status() == "done")
    assert wait_for(lambda: r.phase() == "off")
    assert lamp_off(r) and len(offs(r)) >= 1
    # The lamp window is warm-up + duration + margin.
    assert r.source.calls[0] == ("power", 0.3, pytest.approx(0.2 + 0.5 + 5.0))
    assert saved_run(r)["settings"]["lamp"] == {"power": 0.3, "warmup_s": 0.2}


def test_run_record_keeps_alpha_when_alpha_was_asked(make):
    r = make()
    body = r.run_body(lamp={"alpha_deg": 60, "warmup_s": 0})
    assert r.client.post("/api/runs/start", json=body).status_code == 200
    assert wait_for(lambda: r.run_status() == "done")
    assert saved_run(r)["settings"]["lamp"] == {"alpha_deg": 60, "warmup_s": 0}


def test_a_run_without_the_lamp_option_records_no_lamp(make):
    r = make()
    r.client.post("/api/runs/start", json=r.run_body(lamp=None, duration_s=0.2))
    assert wait_for(lambda: r.run_status() == "done")
    assert "lamp" not in saved_run(r)["settings"]
    assert r.source.calls == [] and r.phase() is None


def test_run_aborted_by_the_safety_limits_switches_the_lamp_off(make):
    r = make()
    r.client.post("/api/runs/start", json=r.run_body(duration_s=5, i_max=1e-6))
    assert wait_for(lambda: r.run_status() == "done")
    assert r.run_cache.snapshot(0)["aborted"]
    assert wait_for(lambda: lamp_off(r) and r.phase() == "off")


def test_stop_during_measurement_switches_the_lamp_off(make):
    r = make()
    body = r.run_body(duration_s=30, lamp={"power": 0.3, "warmup_s": 0})
    r.client.post("/api/runs/start", json=body)
    assert wait_for(lambda: r.phase() == "measuring")
    assert r.client.post("/api/runs/stop").status_code == 204
    assert wait_for(lambda: r.run_status() == "done")
    assert wait_for(lambda: lamp_off(r) and r.phase() == "off")


def test_stop_during_warmup_cancels_the_measurement_and_switches_off(make):
    r = make()
    body = r.run_body(duration_s=5, lamp={"power": 0.3, "warmup_s": 20})
    assert r.client.post("/api/runs/start", json=body).status_code == 200
    assert r.phase() == "warming"
    assert r.client.post("/api/runs/stop").status_code == 204
    assert wait_for(lambda: r.phase() == "off")
    snap = r.run_cache.snapshot(0)
    assert snap["status"] == "done" and snap["aborted"] and snap["n_samples"] == 0
    assert "warm-up" in snap["abort_reason"] and snap["saved_run_id"] is None
    assert lamp_off(r) and len(offs(r)) >= 1


def test_hardware_run_is_queued_only_after_the_warmup(make):
    r = make(demo=False)
    body = r.run_body(simulated=False, lamp={"power": 0.3, "warmup_s": 0.3})
    assert r.client.post("/api/runs/start", json=body).status_code == 200
    assert r.run_requests.empty()  # still warming
    request = r.run_requests.get(timeout=5)
    assert request.lamp == {"power": 0.3, "warmup_s": 0.3}
    assert r.phase() == "measuring" and not lamp_off(r)
    r.run_cache.finish(aborted=False, reason=None, saved_run_id=None)  # the poll thread's end
    assert wait_for(lambda: lamp_off(r) and r.phase() == "off")


def test_a_run_that_never_finishes_is_stopped_at_the_deadline_and_the_lamp_off(make):
    r = make()
    runner = _LampStepRunner(r.lamp, tick_s=0.01)
    cancel = threading.Event()
    runner.begin(
        "run", runner.plan(0.3, None, 0.0), 6.0, cancel=cancel, start=lambda: None,
        is_done=lambda: False, on_abort=lambda _: None, measure_deadline_s=0.2,
    )  # fmt: skip
    assert wait_for(lambda: lamp_off(r) and not runner.active())
    assert cancel.is_set()


def test_an_exception_in_the_orchestration_switches_the_lamp_off(make):
    r = make()
    runner = _LampStepRunner(r.lamp, tick_s=0.01)
    aborted = []

    def boom():
        raise RuntimeError("queue broke")

    runner.begin(
        "run", runner.plan(0.3, None, 0.0), 6.0, cancel=threading.Event(), start=boom,
        is_done=lambda: True, on_abort=aborted.append, measure_deadline_s=1.0,
    )  # fmt: skip
    assert wait_for(lambda: lamp_off(r) and not runner.active())
    assert len(aborted) == 1 and "queue broke" in aborted[0]
    assert runner.snapshot("run")["lamp_phase"] == "off"


def test_an_exception_while_watching_the_measurement_still_switches_off(make):
    r = make()
    runner = _LampStepRunner(r.lamp, tick_s=0.01)

    def is_done():
        raise RuntimeError("poll died")

    cancel = threading.Event()
    runner.begin(
        "run", runner.plan(0.3, None, 0.0), 6.0, cancel=cancel, start=lambda: None,
        is_done=is_done, on_abort=lambda _: None, measure_deadline_s=1.0,
    )  # fmt: skip
    assert wait_for(lambda: lamp_off(r) and not runner.active())
    assert cancel.is_set()


def test_lamp_command_failure_returns_the_error_and_releases_the_slot(make):
    src = FakeLampSource()
    src.set_error = RuntimeError("spi down")
    r = make(src)
    assert r.client.post("/api/runs/start", json=r.run_body()).status_code == 503
    assert r.run_status() == "idle" and r.run_requests.empty()
    src.set_error = None
    assert r.client.post("/api/runs/start", json=r.run_body(duration_s=0.2)).status_code == 200


# -- sweeps ----------------------------------------------------------------------------


def test_sweep_phases_and_lamp_off_when_the_result_lands(make):
    r = make()
    resp = r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 0.3}})
    assert resp.status_code == 204
    data = r.client.get("/api/data").json()
    assert data["lamp_phase"] == "warming" and data["lamp_warmup_left_s"] > 0
    assert r.commands.empty()  # the start command waits for the warm-up
    assert r.source.calls[0] == ("power", 0.3, pytest.approx(0.3 + 15.0 + 5.0))
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    assert r.commands.get_nowait() == "start_sweep" and r.cache.sweep_pending()
    assert not lamp_off(r)
    r.cache.set([(1.0, 0.1)], "ok")  # the result lands
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert lamp_off(r)
    # A plain sweep afterwards shows no lamp phase.
    r.client.post("/api/start-sweep")
    assert r.phase("sweep") is None


def test_sweep_that_never_reports_times_out_and_the_lamp_goes_off(make, monkeypatch):
    monkeypatch.setattr(cache_module, "_SWEEP_PENDING_TIMEOUT_S", 0.3)
    monkeypatch.setattr(hardware_module, "_SWEEP_PENDING_TIMEOUT_S", 0.3)
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 0.1}})
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert lamp_off(r)


def test_a_plain_sweep_or_second_step_is_refused_while_a_step_is_active(make):
    r = make(demo=False)
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 5}})
    assert r.client.post("/api/start-sweep").status_code == 409
    assert r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3}}).status_code == 409
    assert r.client.post("/api/runs/start", json=r.run_body(simulated=False)).status_code == 409


def test_server_shutdown_during_the_warmup_switches_the_lamp_off(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 25}})
    assert not lamp_off(r)
    r.client.__exit__(None, None, None)  # lifespan shutdown
    assert lamp_off(r) and r.commands.empty()
    r.client.__enter__()  # so the fixture can exit it again


# -- manual OFF and newer manual windows ------------------------------------------------


def test_manual_off_during_the_warmup_cancels_the_sweep(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 1}})
    assert r.client.post("/api/dimmer/off").status_code == 200
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert r.commands.empty() and lamp_off(r)
    assert "warm-up" in r.client.get("/api/data").json()["command_error"]
    time.sleep(0.2)
    assert r.commands.empty()


def test_manual_off_during_the_measurement_ends_the_lamp_phase_only(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 0}})
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    r.client.post("/api/dimmer/off")
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert r.cache.sweep_pending() and lamp_off(r)  # the measurement itself goes on
    r.cache.set([(1.0, 0.1)], "ok")
    assert wait_for(lambda: r.client.post("/api/start-sweep").status_code == 204)


def test_a_newer_manual_window_is_not_switched_off_by_the_step(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 0}})
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    assert r.client.post("/api/dimmer", json={"power": 0.8, "max_on_s": 20}).status_code == 200
    assert wait_for(lambda: r.phase("sweep") == "off")
    r.cache.set([(1.0, 0.1)], "ok")
    assert wait_for(lambda: r.client.post("/api/start-sweep").status_code == 204)
    assert not lamp_off(r)  # the operator's window stays
    assert r.source.calls[-1][0] == "power"


# -- demo mode --------------------------------------------------------------------------


def test_demo_mode_end_to_end(tmp_path, monkeypatch):
    r = Rig(None, tmp_path, monkeypatch)
    shutdown = threading.Event()
    thread = threading.Thread(
        target=_poll_loop,
        args=(r.cache, r.commands, 0, 0, 1000, 0.01),
        kwargs={
            "demo": True, "run_requests": r.run_requests, "run_cache": r.run_cache,
            "stop_event": r.stop_event, "shutdown_event": shutdown, "lamp_holder": r.holder,
        },
        daemon=True,
    )  # fmt: skip
    thread.start()
    try:
        with r.client as client:
            assert wait_for(lambda: isinstance(r.holder.get(), SimulatedDimmer))
            body = {"lamp": {"power": 0.5, "warmup_s": 0.2}}
            assert client.post("/api/start-sweep", json=body).status_code == 204
            assert client.get("/api/dimmer").json()["state"] == "on"
            assert wait_for(lambda: r.phase("sweep") == "measuring")
            assert wait_for(lambda: client.get("/api/data").json()["seq"] >= 1, 15)
            assert wait_for(lambda: r.phase("sweep") == "off")
            r.lamp.refresh_once()
            assert client.get("/api/dimmer").json()["state"] == "off"
            # A simulated run with the lamp works in demo mode too.
            assert client.post("/api/runs/start", json=r.run_body()).status_code == 200
            assert wait_for(lambda: r.run_status() == "done")
            assert wait_for(lambda: r.phase() == "off")
            r.lamp.refresh_once()
            assert client.get("/api/dimmer").json()["state"] == "off"
    finally:
        shutdown.set()
        thread.join(5.0)


# -- review fixes ------------------------------------------------------------------------


def test_a_simulated_run_with_the_lamp_is_refused_outside_demo_mode(make):
    r = make(demo=False)
    resp = r.client.post("/api/runs/start", json=r.run_body())
    assert resp.status_code == 422 and "simulated" in resp.json()["detail"]
    untouched(r)


def _manual_on_fails(r, how):
    if how == "refused":
        r.source.refuse = True
        code = 409
    else:
        r.source.set_error = RuntimeError("spi glitch")
        code = 503
    assert r.client.post("/api/dimmer", json={"power": 0.8, "max_on_s": 20}).status_code == code
    r.source.refuse, r.source.set_error = False, None


@pytest.mark.parametrize("how", ["refused", "failed"])
@pytest.mark.parametrize("when", ["warmup", "measuring"])
def test_a_refused_or_failed_manual_on_never_takes_over_the_lamp(make, how, when):
    r = make()
    warmup = 0.6 if when == "warmup" else 0
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": warmup}})
    if when == "measuring":
        assert wait_for(lambda: r.phase("sweep") == "measuring")
    _manual_on_fails(r, how)
    assert r.phase("sweep") in ("warming", "measuring")  # the step is still its own
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    if how == "refused":
        assert not lamp_off(r)  # a failed ON, unlike a refused one, fails closed (lamp off)
    n_before = len(offs(r))
    r.cache.set([(1.0, 0.1)], "ok")
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert wait_for(lambda: lamp_off(r) and len(offs(r)) > n_before)  # its own final OFF


def test_a_valid_manual_on_during_the_warmup_cancels_with_an_honest_message(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 1}})
    assert r.client.post("/api/dimmer", json={"power": 0.8, "max_on_s": 20}).status_code == 200
    assert wait_for(lambda: r.phase("sweep") == "off")
    assert "changed by the operator" in r.client.get("/api/data").json()["command_error"]
    assert r.commands.empty() and not lamp_off(r)  # the operator's window stays


@pytest.mark.parametrize("kind", ["sweep", "run"])
def test_a_thread_that_cannot_start_switches_the_lamp_off_and_frees_everything(
    make, monkeypatch, kind
):
    r = make()
    original = threading.Thread.start

    def start(self):
        if self.name == "lamp-step":
            raise RuntimeError("cannot start new thread")
        return original(self)

    monkeypatch.setattr(threading.Thread, "start", start)
    with pytest.raises(RuntimeError, match="cannot start"):
        if kind == "sweep":
            r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3}})
        else:
            r.client.post("/api/runs/start", json=r.run_body())
    monkeypatch.setattr(threading.Thread, "start", original)
    assert lamp_off(r) and len(offs(r)) >= 1
    assert r.run_status() == "idle"
    assert r.client.post("/api/start-sweep").status_code == 204  # the runner is not stuck
    assert r.client.post("/api/runs/start", json=r.run_body(duration_s=0.2)).status_code == 200


def test_a_failed_sweep_start_command_ends_the_step_at_once(make):
    r = make()
    r.client.post("/api/start-sweep", json={"lamp": {"power": 0.3, "warmup_s": 0}})
    assert wait_for(lambda: r.phase("sweep") == "measuring")
    r.cache.set_command_error("start_sweep failed: spi")  # what the poll thread does
    assert wait_for(lambda: r.phase("sweep") == "off", 2.0)
    assert lamp_off(r)
    assert r.cache.sweep_pending()  # the 15 s timeout has not been needed
