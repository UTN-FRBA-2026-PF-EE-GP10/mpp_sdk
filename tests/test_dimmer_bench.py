"""`scripts/dimmer_bench.py`: judgement functions and the runner, with a fake source and clock."""

from __future__ import annotations

import json
import math
import signal

import pytest

from mpp_sdk.io.dimmer import DimmerStatus
from scripts import dimmer_bench as b


def st(**kw) -> DimmerStatus:
    base = dict(
        link_ok=True,
        mains=False,
        locked=False,
        timed_out=False,
        set_alpha_deg=180.0,
        applied_alpha_deg=None,
        age_s=0.1,
        tripped=False,
        budget_s=120,
    )
    base.update(kw)
    return DimmerStatus(**base)


# ---------------------------------------------------------------------------
# Judgement functions
# ---------------------------------------------------------------------------


def test_judge_link():
    ok = [(i * 0.5, st()) for i in range(6)]
    assert b.judge_link(ok).status == b.PASS
    assert b.judge_link([*ok[:-1], (3.0, None)]).status == b.FAIL
    assert b.judge_link([*ok[:-1], (3.0, st(link_ok=False))]).status == b.FAIL
    assert b.judge_link([*ok[:-1], (3.0, st(mains=True))]).status == b.FAIL
    assert b.judge_link(ok[:2]).status == b.FAIL


def test_judge_alpha_readback():
    on = [(0, st(set_alpha_deg=90.0)), (1, st(set_alpha_deg=90.0))]
    assert b.judge_alpha_readback(on, 90.0).status == b.PASS
    assert b.judge_alpha_readback(on, 45.0).status == b.FAIL
    fired = [(0, st(set_alpha_deg=90.0, applied_alpha_deg=90.0))]
    assert b.judge_alpha_readback(fired, 90.0).status == b.FAIL
    assert b.judge_alpha_readback(fired, 90.0, mains=True).status == b.PASS


def test_judge_stable():
    good = [(i, st(age_s=0.5)) for i in range(10)]
    assert b.judge_stable(good).status == b.PASS
    assert b.judge_stable([*good, (11, st(age_s=3.0))]).status == b.FAIL
    assert b.judge_stable([*good, (11, None)]).status == b.FAIL


def test_judge_pico_timeout():
    seq = [(t, st(set_alpha_deg=90.0)) for t in (10, 11)]
    seq += [(t, st(set_alpha_deg=180.0)) for t in (12, 13, 14)]
    assert b.judge_pico_timeout(seq, 10.0).status == b.PASS
    assert b.judge_pico_timeout(seq, 5.0).status == b.FAIL  # 7 s is too late
    assert b.judge_pico_timeout(seq[:2], 10.0).status == b.FAIL
    back = [*seq, (15, st(set_alpha_deg=90.0))]
    assert b.judge_pico_timeout(back, 10.0).status == b.FAIL


def test_judge_link_loss_and_recovery():
    seq = [(0, st()), (1, st()), (2, st(link_ok=False))]
    assert b.judge_link_loss(seq, 0.0).status == b.PASS
    assert b.judge_link_loss(seq, 0.0, limit_s=1.0).status == b.FAIL
    assert b.judge_link_loss(seq[:2], 0.0).status == b.FAIL
    assert b.judge_recovered(seq).status == b.PASS
    assert b.judge_recovered([(0, st(link_ok=False))]).status == b.FAIL


def test_judge_stays_off_and_timed_out():
    assert b.judge_stays_off([(i, st()) for i in range(4)]).status == b.PASS
    assert b.judge_stays_off([(i, st(set_alpha_deg=90.0)) for i in range(4)]).status == b.FAIL
    assert b.judge_timed_out_seen([(0, st(timed_out=True))]).status == b.PASS
    assert b.judge_timed_out_seen([(0, st())]).status == b.INCONCLUSIVE


def test_judge_budget_slope():
    fall = [(t, st(budget_s=100 - t)) for t in range(0, 11)]
    assert b.judge_budget_slope(fall, "fall").status == b.PASS
    assert b.judge_budget_slope(fall, "rise").status == b.FAIL
    flat = [(t, st(budget_s=100)) for t in range(0, 11)]
    assert b.judge_budget_slope(flat, "fall").status == b.FAIL
    rise = [(t, st(budget_s=100 + t)) for t in range(0, 11)]
    assert b.judge_budget_slope(rise, "rise").status == b.PASS
    full = [(t, st(budget_s=120)) for t in range(0, 11)]
    assert b.judge_budget_slope(full, "rise").status == b.INCONCLUSIVE
    assert b.judge_budget_slope(fall[:3], "fall").status == b.FAIL


def test_judge_trip_refusal_and_rearm():
    seq = [(t, st(tripped=t >= 120, budget_s=60 if t >= 120 else 0)) for t in range(100, 130)]
    assert b.judge_trip(seq, 0.0, 120.0).status == b.PASS
    assert b.judge_trip(seq, 0.0, 60.0).status == b.FAIL
    assert b.judge_trip([(0, st())], 0.0, 120.0).status == b.FAIL
    hot = [(t, st(tripped=True, budget_s=50)) for t in range(4)]
    assert b.judge_refused(hot).status == b.PASS
    assert b.judge_refused([*hot, (5, st())]).status == b.FAIL
    fired = [(t, st(tripped=True, applied_alpha_deg=90.0)) for t in range(4)]
    assert b.judge_refused(fired).status == b.FAIL
    cool = [(t, st(tripped=t < 180)) for t in range(150, 200)]
    assert b.judge_cooldown_rearm(cool, 120.0, 60.0).status == b.PASS
    assert b.judge_cooldown_rearm(cool, 120.0, 30.0).status == b.FAIL  # too late
    assert b.judge_cooldown_rearm(cool, 120.0, 100.0).status == b.FAIL  # too early
    assert b.judge_cooldown_rearm([(0, st(tripped=True))], 0.0, 60.0).status == b.FAIL


def test_judge_no_restart_and_cleared():
    assert b.judge_no_restart(st(tripped=True, budget_s=0)).status == b.PASS
    assert b.judge_no_restart(st(tripped=False)).status == b.FAIL
    assert b.judge_no_restart(st(tripped=True, budget_s=7)).status == b.INCONCLUSIVE
    assert b.judge_no_restart(None).status == b.FAIL
    assert b.judge_cleared([(0, st(tripped=True)), (1, st())]).status == b.PASS
    assert b.judge_cleared([(0, st(tripped=True)), (1, st(tripped=True))]).status == b.FAIL
    assert b.judge_on_accepted([(0, st())]).status == b.PASS
    assert b.judge_on_accepted([(0, st(tripped=True))]).status == b.FAIL


def test_judge_reset_cleared():
    assert b.judge_reset_cleared(st(budget_s=70), st(budget_s=120)).status == b.PASS
    assert b.judge_reset_cleared(st(budget_s=70), st(budget_s=70)).status == b.FAIL
    assert b.judge_reset_cleared(st(budget_s=120), st()).status == b.INCONCLUSIVE
    assert b.judge_reset_cleared(st(tripped=True, budget_s=0), st()).status == b.PASS
    assert b.judge_reset_cleared(st(budget_s=70), None).status == b.FAIL


def test_judge_mains_checks():
    locked = [(i, st(mains=True, locked=True)) for i in range(5)]
    assert b.judge_mains_locked(locked).status == b.PASS
    assert b.judge_mains_locked([(i, st(mains=True)) for i in range(5)]).status == b.FAIL
    good = [
        (a, st(mains=True, applied_alpha_deg=max(25.0, min(a, 153.0)))) for a in (10.0, 90.0, 170.0)
    ]
    assert b.judge_applied(good).status == b.PASS
    assert b.judge_applied([(90.0, st(mains=True, applied_alpha_deg=100.0))]).status == b.FAIL
    assert b.judge_applied([(90.0, st(mains=True))]).status == b.FAIL
    assert b.judge_applied([(10.0, st(mains=True, applied_alpha_deg=5.0))]).status == b.FAIL
    assert b.judge_dark([(0, st())]).status == b.PASS
    assert b.judge_dark([(0, st(applied_alpha_deg=90.0))]).status == b.FAIL


def test_exit_code_and_select_checks():
    ok, bad, maybe = (b.CheckResult("x", s, "") for s in (b.PASS, b.FAIL, b.INCONCLUSIVE))
    assert b.exit_code([ok]) == 0
    assert b.exit_code([ok, maybe]) == 2
    assert b.exit_code([ok, maybe, bad]) == 1
    assert [c[0] for c in b.select_checks(["trip"], mains=False, auto_only=False)] == ["trip"]
    assert all(not c[1] for c in b.select_checks(None, mains=False, auto_only=True))
    assert [c[0] for c in b.select_checks(None, mains=True, auto_only=False)][0] == "mains-lock"
    with pytest.raises(ValueError):
        b.select_checks(["nope"], mains=False, auto_only=False)
    with pytest.raises(ValueError):
        b.select_checks(["mains-lock"], mains=False, auto_only=False)


# ---------------------------------------------------------------------------
# Runner with a fake dimmer and a fake clock
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class FakeDimmer:
    """The exposure rules of the design, and the host OFF acknowledgment of SpiMcuSource."""

    def __init__(self, clock, mains=False):
        self.clock = clock
        self.mains = mains
        self.t = clock()
        self.heat = 0.0
        self.tripped = False
        self.off_seen = False
        self.wire_on = False
        self.set_deg = 180.0
        self.deadline = None
        self.killed_at = None
        self.max_on = []
        self.closed = False

    def _commanded(self):
        return self.wire_on and not self.tripped

    def _advance(self):
        now = self.clock()
        dt, self.t = now - self.t, now
        if self.killed_at is not None and now - self.killed_at >= 3.0:
            self.wire_on, self.set_deg, self.killed_at = False, 180.0, None
        if self.wire_on and self.deadline is not None and now > self.deadline:
            self.wire_on, self.set_deg = False, 180.0
        if self._commanded():
            on = min(dt, 120.0 - self.heat)
            self.heat += on
            if self.heat >= 120.0:
                self.tripped, self.off_seen = True, False
            dt -= on
        self.heat = max(0.0, self.heat - dt)
        if self.tripped and self.heat <= 60.0 and self.off_seen:
            self.tripped = False

    def set_dimmer_alpha(self, alpha, *, max_on_s):
        self.max_on.append(max_on_s)
        self._advance()
        self.wire_on = True
        self.set_deg = alpha
        self.deadline = self.clock() + max_on_s

    def dimmer_off(self):
        self._advance()
        self.wire_on, self.set_deg, self.off_seen, self.deadline = False, 180.0, True, None

    def close(self):
        self.closed = True
        self.dimmer_off()

    def dimmer_status(self):
        self._advance()
        budget = math.ceil(max(0.0, self.heat - 60.0)) if self.tripped else int(120 - self.heat)
        fired = self.mains and self._commanded() and self.set_deg < 180.0
        status = st(
            mains=self.mains,
            locked=self.mains,
            set_alpha_deg=self.set_deg,
            applied_alpha_deg=max(25.0, min(self.set_deg, 153.0)) if fired else None,
            tripped=self.tripped,
            budget_s=budget,
        )
        if self.tripped and self.wire_on:
            self.dimmer_off()
        return status

    def holder(self, alpha):
        self.set_dimmer_alpha(alpha, max_on_s=40.0)
        dimmer = self

        class Holder:
            def kill(self):
                if dimmer.killed_at is None and dimmer.wire_on:
                    dimmer.killed_at = dimmer.clock()

        return Holder()


def make_bench(mains=False, answers=(), **kw):
    clock = Clock()
    dimmer = FakeDimmer(clock, mains=mains)
    queue = list(answers)
    log = []
    bench = b.Bench(
        dimmer,
        mains=mains,
        clock=clock,
        sleep=clock.sleep,
        ask=lambda prompt: queue.pop(0) if queue else "",
        out=log.append,
        spawn_holder=dimmer.holder,
        **kw,
    )
    return bench, dimmer, log


@pytest.mark.parametrize(
    "name",
    ["c_link", "c_alpha", "c_host_timeout", "c_budget_fall", "c_trip", "c_no_restart"],
)
def test_check_passes_on_a_good_fake(name):
    bench, dimmer, _ = make_bench()
    result = bench.run_check(name, getattr(bench, name))
    assert result.status == b.PASS, result.detail
    assert dimmer.wire_on is False  # always left off
    assert all(0 < m <= 120 for m in dimmer.max_on)


def test_budget_rise_after_fall():
    bench, _, _ = make_bench()
    assert bench.run_check("f", bench.c_budget_fall).status == b.PASS
    assert bench.run_check("r", bench.c_budget_rise).status == b.PASS


def test_stable_uses_the_configured_length():
    bench, _, _ = make_bench(stable_s=6.0)
    start = bench.clock()
    assert bench.run_check("s", bench.c_stable).status == b.PASS
    assert bench.clock() - start < 10


def test_unplug_check_fails_when_the_link_never_drops():
    bench, dimmer, _ = make_bench(answers=["", ""])
    assert bench.run_check("i", bench.c_i2c_unplug).status == b.FAIL
    assert dimmer.wire_on is False


def test_a_dimmer_that_restarts_by_itself_fails_no_restart():
    bench, dimmer, _ = make_bench()
    original = dimmer._advance

    def lax():
        dimmer.off_seen = True  # re-arms without an OFF from the host
        original()

    dimmer._advance = lax
    assert bench.run_check("n", bench.c_no_restart).status == b.FAIL


def test_always_off_after_an_error_and_after_interrupt():
    bench, dimmer, _ = make_bench()

    def boom():
        dimmer.set_dimmer_alpha(90.0, max_on_s=10.0)
        raise RuntimeError("boom")

    result = bench.run_check("boom", boom)
    assert result.status == b.FAIL and "boom" in result.detail
    assert dimmer.wire_on is False

    def stop():
        dimmer.set_dimmer_alpha(90.0, max_on_s=10.0)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        bench.run_check("stop", stop)
    assert dimmer.wire_on is False
    assert bench.results[-1].detail == "interrupted"


def test_safe_off_retries_and_warns():
    bench, dimmer, log = make_bench()
    calls = []

    def failing():
        calls.append(1)
        raise OSError("spi")

    dimmer.dimmer_off = failing
    bench.safe_off()
    assert len(calls) == 3
    assert any("cut the mains" in line for line in log)


def test_no_mains_mode_refuses_to_command_when_mains_is_present():
    bench, dimmer, _ = make_bench(mains=False)
    dimmer.mains = True  # the operator thinks it is disconnected, it is not
    result = bench.run_check("alpha", bench.c_alpha)
    assert result.status == b.FAIL and "mains" in result.detail
    assert dimmer.max_on == []  # no on-command was sent


def test_mains_mode_refuses_without_mains_and_runs_with_it():
    bench, dimmer, _ = make_bench(mains=True)
    dimmer.mains = False
    assert bench.run_check("r", bench.c_mains_range).status == b.FAIL
    assert dimmer.max_on == []
    bench, dimmer, _ = make_bench(mains=True)
    assert bench.run_check("l", bench.c_mains_lock).status == b.PASS
    assert bench.run_check("r", bench.c_mains_range).status == b.PASS
    assert dimmer.wire_on is False and all(m <= 120 for m in dimmer.max_on)


def test_mains_dark_asks_the_operator():
    bench, _, _ = make_bench(mains=True, answers=["y"])
    assert bench.run_check("d", bench.c_mains_dark).status == b.PASS
    bench, _, _ = make_bench(mains=True, answers=["n"])
    assert bench.run_check("d", bench.c_mains_dark).status == b.FAIL


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_mains_needs_the_confirmation_line():
    made = []
    code = b.main(
        ["--mains"], source_factory=lambda: made.append(1), ask=lambda p: "yes", out=lambda s: None
    )
    assert code == 3 and made == []


def test_main_refuses_when_mains_present_without_flag_and_writes_json(tmp_path):
    dimmer = FakeDimmer(Clock(), mains=True)
    out_file = tmp_path / "r.json"
    code = b.main(
        ["--auto-only", "--out", str(out_file)],
        source_factory=lambda: dimmer,
        out=lambda s: None,
    )
    assert code == 3
    assert dimmer.max_on == [] and dimmer.closed
    assert json.loads(out_file.read_text())["exit_code"] == 3


def test_main_ctrl_c_ends_with_off(tmp_path):
    clock = Clock()
    dimmer = FakeDimmer(clock)
    original = dimmer.dimmer_status
    count = []

    def status():
        count.append(1)
        if len(count) > 4:
            raise KeyboardInterrupt
        return original()

    dimmer.dimmer_status = status
    out_file = tmp_path / "r.json"
    code = b.main(
        ["--only", "alpha", "--out", str(out_file)],
        source_factory=lambda: dimmer,
        out=lambda s: None,
    )
    assert code == 130
    assert dimmer.wire_on is False and dimmer.closed
    assert json.loads(out_file.read_text())["note"] == "interrupted"


def test_main_sigterm_handler_raises_keyboard_interrupt_and_is_restored(monkeypatch):
    before = signal.getsignal(signal.SIGTERM)
    seen = {}

    def factory():
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        return FakeDimmer(Clock())

    # Real time.sleep is patched out so the single check does not wait.
    monkeypatch.setattr(b.time, "sleep", lambda s: None)
    b.main(["--only", "link"], source_factory=factory, out=lambda s: None)
    with pytest.raises(KeyboardInterrupt):
        seen["handler"](signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == before


def test_help_works_without_spidev(capsys):
    with pytest.raises(SystemExit) as exc:
        b.main(["--help"])
    assert exc.value.code == 0
    assert "--auto-only" in capsys.readouterr().out


def test_main_mains_confirmation_with_closed_stdin_is_not_confirmed():
    def eof(prompt):
        raise EOFError

    made = []
    code = b.main(["--mains"], source_factory=lambda: made.append(1), ask=eof, out=lambda s: None)
    assert code == 3 and made == []


def test_limits_at_their_bounds():
    link = [(0.0, st()), (3.0, st(link_ok=False))]
    assert b.judge_link_loss(link, 0.0).status == b.PASS
    link = [(0.0, st()), (5.0, st(link_ok=False))]
    assert b.judge_link_loss(link, 0.0).status == b.FAIL
    off = lambda t: [(t, st(set_alpha_deg=180.0)), (t + 1, st(set_alpha_deg=180.0))]  # noqa: E731
    assert b.judge_pico_timeout(off(4.4), 0.0).status == b.PASS
    assert b.judge_pico_timeout(off(4.6), 0.0).status == b.FAIL
    cool = lambda t: [(t, st(tripped=False))]  # noqa: E731
    assert b.judge_cooldown_rearm(cool(65.9), 0.0, 60.0).status == b.PASS
    assert b.judge_cooldown_rearm(cool(66.1), 0.0, 60.0).status == b.FAIL
    assert b.judge_cooldown_rearm(cool(53.9), 0.0, 60.0).status == b.FAIL
    trip = lambda t: [(t, st(tripped=True))]  # noqa: E731
    assert b.judge_trip(trip(125.9), 0.0, 120.0).status == b.PASS
    assert b.judge_trip(trip(126.1), 0.0, 120.0).status == b.FAIL
    assert b.judge_stable([(i, st(age_s=1.5)) for i in range(6)]).status == b.PASS
    assert b.judge_stable([(i, st(age_s=1.6)) for i in range(6)]).status == b.FAIL
    assert b.judge_cleared([(0.0, st(tripped=True)), (4.0, st())]).status == b.PASS
    assert b.judge_cleared([(0.0, st(tripped=True)), (4.5, st())]).status == b.FAIL


def test_deadman_has_no_time_limit_and_is_inconclusive_not_fail():
    assert b.judge_timed_out_seen([(t, st()) for t in range(100)]).status == b.INCONCLUSIVE
    assert b.judge_timed_out_seen([(99.0, st(timed_out=True))]).status == b.PASS


def child_args(angle, mains):
    ns = type("A", (), {})()
    ns.child_hold, ns.child_mains, ns.bus, ns.device = angle, mains, 0, 0
    return ns


def test_child_refuses_without_mains_state_or_with_bad_angle(capsys):
    made = []
    factory = lambda: made.append(1)  # noqa: E731
    assert b._child_hold(child_args(90.0, None), factory) == 3
    for angle in (-1.0, 180.0, 200.0, float("nan"), float("inf")):
        assert b._child_hold(child_args(angle, 0), factory) == 3
    assert made == []


def test_child_applies_the_mains_rule():
    dimmer = FakeDimmer(Clock(), mains=True)
    assert b._child_hold(child_args(90.0, 0), lambda: dimmer) == 3
    assert dimmer.max_on == [] and dimmer.closed
    dimmer = FakeDimmer(Clock(), mains=False)
    assert b._child_hold(child_args(90.0, 1), lambda: dimmer) == 3
    assert dimmer.max_on == []


def test_child_holds_when_the_rule_is_met(monkeypatch):
    clock = Clock()
    dimmer = FakeDimmer(clock, mains=False)
    monkeypatch.setattr(b.time, "sleep", clock.sleep)
    assert b._child_hold(child_args(90.0, 0), lambda: dimmer) == 0
    assert dimmer.max_on == [b.ON_WINDOW_S + 10.0] and dimmer.closed
    assert dimmer.wire_on is False


def test_spawn_passes_the_mains_state(monkeypatch):
    seen = []
    monkeypatch.setattr(b.subprocess, "Popen", lambda cmd: seen.append(cmd) or object())
    b._spawn_holder(90.0, 0, 0, True)
    assert seen[0][seen[0].index("--child-mains") + 1] == "1"
