"""Tests for the dimmer helpers and the SpiMcuSource dimmer methods (fake spidev)."""

import contextlib
import inspect
import math
import re
import threading
import time
from pathlib import Path

import pytest

from mpp_sdk.io.dimmer import (
    DEFAULT_LAMP_WINDOW_S,
    MAX_LAMP_WINDOW_S,
    DimmerRefused,
    DimmerStatus,
    alpha_for_power,
    alpha_to_wire,
    lamp_power_fraction,
    parse_status_frame,
)
from mpp_sdk.io.spi_crc import crc8
from tests.test_spi_mcu import _miso_frame, spi_mcu_source  # noqa: F401


def _status_frame(
    flags=0x0F, set_cd=9000, applied=9100, age=3, magic=0xD2, corrupt=False, budget=0
):
    data = [magic, flags, set_cd >> 8, set_cd & 0xFF, applied >> 8, applied & 0xFF, age, budget]
    crc = crc8([*data, 0, 0])
    return [*data, crc ^ (1 if corrupt else 0), 0, 0, 0]


def test_alpha_to_wire_rounds_and_validates():
    assert alpha_to_wire(90.0) == 9000
    assert alpha_to_wire(0.004) == 0
    assert alpha_to_wire(180.0) == 18000
    for bad in (-0.1, 180.01, math.nan, math.inf):
        with pytest.raises(ValueError):
            alpha_to_wire(bad)


def test_power_round_trip():
    assert lamp_power_fraction(0.0) == pytest.approx(1.0)
    assert lamp_power_fraction(180.0) == pytest.approx(0.0, abs=1e-12)
    assert lamp_power_fraction(90.0) == pytest.approx(0.5)
    assert alpha_for_power(0.0) == 180.0
    assert alpha_for_power(1.0) == 0.0
    for p in (0.1, 0.25, 0.5, 0.9):
        assert lamp_power_fraction(alpha_for_power(p)) == pytest.approx(p, abs=1e-9)
    with pytest.raises(ValueError):
        alpha_for_power(1.5)


def test_parse_good_status():
    status = parse_status_frame(_status_frame())
    assert status == DimmerStatus(True, True, True, True, 90.0, 91.0, pytest.approx(0.3))


def test_parse_not_firing():
    assert parse_status_frame(_status_frame(applied=0xFFFF)).applied_alpha_deg is None


def test_parse_rejects_bad_crc_and_magic():
    assert parse_status_frame(_status_frame(corrupt=True)) is None
    assert parse_status_frame(_status_frame(magic=0xB4)) is None
    assert parse_status_frame([0] * 5) is None


def test_set_alpha_frame_bytes(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source()
    src.set_dimmer_alpha(90.0)
    tx = src._spi.sent[-1]
    assert tx[:4] == [0x23, 0x28, crc8([0x23, 0x28, 0xD1]), 0xD1]
    src.close()


def test_status_reads_reply_in_second_exchange(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source()
    src._spi.responses = [_miso_frame(0, 0, 0, 0), _status_frame()]
    status = src.dimmer_status()
    assert status is not None and status.set_alpha_deg == 90.0
    assert [tx[3] for tx in src._spi.sent] == [0xD2, 0]
    src.close()


def test_status_none_on_bad_reply(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source()
    assert src.dimmer_status() is None
    src.close()


def test_keepalive_resends_and_stops_on_off(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    time.sleep(0.15)
    n = sum(tx[3] == 0xD1 for tx in src._spi.sent)
    assert n >= 4
    src.dimmer_off()
    sent_after_off = len(src._spi.sent)
    assert src._spi.sent[-1][:2] == [0x46, 0x50]
    time.sleep(0.05)
    assert len(src._spi.sent) == sent_after_off
    src.close()


def test_close_sends_off_and_stops_thread(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(45.0)
    thread = src._dimmer_thread
    src.close()
    assert src._spi.closed
    assert src._spi.sent[-1][:2] == [0x46, 0x50]
    assert not thread.is_alive()


def test_keepalive_interval_limit(spi_mcu_source):  # noqa: F811
    with pytest.raises(ValueError):
        spi_mcu_source(dimmer_keepalive_s=2.5)


def test_keepalive_cannot_split_ack_and_bulk_read(spi_mcu_source):  # noqa: F811
    from mpp_sdk.io.spi_mcu import _BULK_FRAME_LEN

    src = spi_mcu_source(dimmer_keepalive_s=0.001)
    src.set_dimmer_alpha(90.0)
    ack_rx = _miso_frame(0, 0, 0, 0, ack=0x80)
    for _ in range(100):
        with src._lock:
            src._spi.responses = [ack_rx, [0xC5] + [0] * (_BULK_FRAME_LEN - 1)]
        with contextlib.suppress(RuntimeError):
            src.request_sweep(poll_attempts=1)
    sent = src._spi.sent
    for i, tx in enumerate(sent):
        if len(tx) == _BULK_FRAME_LEN:
            assert sent[i - 1][3] == 0xB1
    src.dimmer_off()
    src.close()


def test_keepalive_does_not_touch_telemetry(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.write(0.2)
    before = (src._v, src._i, src._vout)
    src._spi.responses = [_miso_frame(1234, 567, 890, 0)] * 50
    src._spi.next_rx = _miso_frame(1234, 567, 890, 0)
    src.set_dimmer_alpha(90.0)
    after_set = (src._v, src._i, src._vout)
    time.sleep(0.1)
    assert (src._v, src._i, src._vout) == after_set
    assert before != after_set
    src.dimmer_off()
    src.close()


def test_keepalive_failure_marks_inactive(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    assert src.is_dimmer_active
    src._spi.raise_on_xfer = RuntimeError("boom")
    time.sleep(0.1)
    assert not src.is_dimmer_active
    src._spi.raise_on_xfer = None
    src.close()


# ── lamp deadline, lamp_window, tripped handling ─────────────────────────────

_OFF_PREFIX = [0x46, 0x50]


@pytest.fixture
def clock(monkeypatch):
    """Monotonic clock with a manual offset, so tests need not sleep."""
    real = time.monotonic
    offset = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: real() + offset[0])

    def advance(seconds):
        offset[0] += seconds

    return advance


def _off_count(src):
    return sum(tx[:2] == _OFF_PREFIX and tx[3] == 0xD1 for tx in src._spi.sent)


def _wait(cond, timeout=1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        time.sleep(0.005)
    return cond()


def test_status_parse_new_flag_and_budget():
    status = parse_status_frame(_status_frame(flags=0x1F, budget=42))
    assert status.tripped and status.budget_s == 42
    assert not parse_status_frame(_status_frame(flags=0x0F)).tripped


def test_status_parse_old_layout_has_zero_budget():
    status = parse_status_frame(_status_frame(flags=0x0F))
    assert status.budget_s == 0 and not status.tripped


def test_status_parse_bad_crc_with_new_fields():
    assert parse_status_frame(_status_frame(flags=0x1F, budget=42, corrupt=True)) is None


@pytest.mark.parametrize(
    "bad", [0, -1, math.nan, math.inf, MAX_LAMP_WINDOW_S + 1, 120.0001, True, "5", None]
)
def test_max_on_s_validation(spi_mcu_source, bad):  # noqa: F811
    src = spi_mcu_source()
    with pytest.raises(ValueError):
        src.set_dimmer_alpha(90.0, max_on_s=bad)
    with pytest.raises(ValueError):
        src.set_dimmer_power(0.5, max_on_s=bad)
    with pytest.raises(ValueError), src.lamp_window(power=0.5, max_on_s=bad):
        pass
    assert not src._spi.sent
    src.close()


def test_deadline_sends_off_and_stops_thread(spi_mcu_source, clock):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0, max_on_s=5.0)
    thread = src._dimmer_thread
    assert src.is_dimmer_active
    assert 0.0 < src.dimmer_window_left_s() <= 5.0
    clock(6.0)
    assert _wait(lambda: not thread.is_alive())
    assert not src.is_dimmer_active
    assert src._dimmer_wire == 18000
    assert src.dimmer_window_left_s() is None
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    n = len(src._spi.sent)
    time.sleep(0.05)
    assert len(src._spi.sent) == n
    src.close()


def test_new_set_call_extends_deadline(spi_mcu_source, clock):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0, max_on_s=5.0)
    clock(4.0)
    src.set_dimmer_alpha(90.0, max_on_s=5.0)
    clock(3.0)
    time.sleep(0.05)
    assert src.is_dimmer_active
    assert _off_count(src) == 0
    clock(3.0)
    assert _wait(lambda: not src.is_dimmer_active)
    assert _off_count(src) == 1
    src.close()


def test_set_after_deadline_restarts_thread(spi_mcu_source, clock):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0, max_on_s=1.0)
    clock(2.0)
    assert _wait(lambda: not src.is_dimmer_active)
    src.set_dimmer_alpha(90.0, max_on_s=5.0)
    assert src.is_dimmer_active
    src.close()


def test_off_alpha_and_zero_power_act_like_dimmer_off(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    thread = src._dimmer_thread
    src.set_dimmer_power(0.0)
    assert not thread.is_alive()
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    assert src.dimmer_window_left_s() is None
    src.set_dimmer_alpha(90.0)
    src.set_dimmer_alpha(180.0)
    assert not src.is_dimmer_active
    src.close()


def test_default_window_is_default_constant(spi_mcu_source, clock):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.5)
    src.set_dimmer_alpha(90.0)
    assert src.dimmer_window_left_s() <= DEFAULT_LAMP_WINDOW_S
    assert src.dimmer_window_left_s() > DEFAULT_LAMP_WINDOW_S - 1.0
    src.close()


def test_keepalive_failure_at_deadline_leaves_lamp_off_state(spi_mcu_source, clock):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0, max_on_s=5.0)
    src._spi.raise_on_xfer = RuntimeError("boom")
    clock(6.0)
    assert _wait(lambda: not src.is_dimmer_active)
    assert src._dimmer_wire == 18000
    assert src._dimmer_deadline is None
    src._spi.raise_on_xfer = None
    src.close()


def _link_ok(src):
    src.dimmer_status = lambda: parse_status_frame(_status_frame(flags=0x0F))


def test_lamp_window_off_after_normal_exit(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _link_ok(src)
    with src.lamp_window(power=0.5):
        assert src.is_dimmer_active
    assert not src.is_dimmer_active
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


@pytest.mark.parametrize("exc", [RuntimeError, KeyboardInterrupt])
def test_lamp_window_off_after_exception(spi_mcu_source, exc):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _link_ok(src)
    with pytest.raises(exc), src.lamp_window(alpha_deg=90.0):
        raise exc
    assert not src.is_dimmer_active
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


def test_lamp_window_needs_exactly_one_of_power_and_alpha(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source()
    for kwargs in ({}, {"power": 0.5, "alpha_deg": 90.0}):
        with pytest.raises(ValueError), src.lamp_window(**kwargs):
            pass
    assert not src._spi.sent
    src.close()


def test_lamp_window_refused_when_tripped(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    # set command, then status request and reply
    src._spi.responses = [
        _miso_frame(0, 0, 0, 0),
        _miso_frame(0, 0, 0, 0),
        _status_frame(flags=0x1F, budget=30),
    ]
    entered = False
    with pytest.raises(DimmerRefused), src.lamp_window(power=0.5):
        entered = True
    assert not entered
    assert not src.is_dimmer_active
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


def test_status_tripped_sends_off_acknowledgment(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    thread = src._dimmer_thread
    src._spi.responses = [_miso_frame(0, 0, 0, 0), _status_frame(flags=0x1F, budget=5)]
    status = src.dimmer_status()
    assert status.tripped
    assert not thread.is_alive()
    assert not src.is_dimmer_active
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


def test_status_tripped_with_lamp_off_sends_nothing_more(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source()
    src._spi.responses = [_miso_frame(0, 0, 0, 0), _status_frame(flags=0x1F)]
    assert src.dimmer_status().tripped
    assert [tx[3] for tx in src._spi.sent] == [0xD2, 0]
    src.close()


def test_status_read_does_not_deadlock_with_keepalive(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.001)
    src.set_dimmer_alpha(90.0)
    done = threading.Event()

    def reader():
        for _ in range(20):
            src.dimmer_status()
        src.set_dimmer_alpha(90.0)
        with src._lock:
            src._spi.responses = [_miso_frame(0, 0, 0, 0), _status_frame(flags=0x1F)]
        src.dimmer_status()
        done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    assert done.wait(5.0)
    src.close()


def _rust_const(name):
    text = (Path(__file__).parent.parent / "firmware/dimmer-link/src/lib.rs").read_text()
    match = re.search(rf"pub const {name}: u32 = ([\d_]+);", text)
    assert match, name
    return int(match.group(1).replace("_", ""))


def test_timing_constants_match_firmware(spi_mcu_source):  # noqa: F811
    from mpp_sdk.io import spi_mcu

    assert _rust_const("HOST_TIMEOUT_MS") == spi_mcu._DIMMER_HOST_TIMEOUT_S * 1000
    assert _rust_const("COMMAND_TIMEOUT_MS") == spi_mcu._MAX_DIMMER_KEEPALIVE_S * 1000
    # The Pico-to-dimmer keepalive must be faster than the dimmer deadman.
    assert _rust_const("KEEPALIVE_MS") < _rust_const("COMMAND_TIMEOUT_MS")
    default = inspect.signature(spi_mcu.SpiMcuSource.__init__).parameters["dimmer_keepalive_s"]
    assert default.default * 1000 < _rust_const("COMMAND_TIMEOUT_MS")


def test_validate_accepts_numbers():
    from mpp_sdk.io.dimmer import validate_max_on_s

    assert validate_max_on_s(5) == 5.0
    assert validate_max_on_s(120.0) == 120.0


def test_dimmer_off_sends_frame_even_if_join_is_interrupted(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    thread = src._dimmer_thread
    real_join = thread.join

    def bad_join(*a, **k):
        raise KeyboardInterrupt

    thread.join = bad_join
    with pytest.raises(KeyboardInterrupt):
        src.dimmer_off()
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    assert src._dimmer_wire == 18000
    assert src.dimmer_window_left_s() is None
    real_join()


def test_lamp_window_retries_off_and_keeps_original_exception(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _link_ok(src)
    calls = []
    real = src.dimmer_off

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError("spi")
        real()

    src.dimmer_off = flaky
    with pytest.raises(ValueError, match="mine"), src.lamp_window(power=0.5):
        raise ValueError("mine")
    assert len(calls) == 3
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


def test_lamp_window_original_exception_wins_over_failing_off(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _link_ok(src)

    def always_fail():
        raise OSError("spi")

    src.dimmer_off = always_fail
    with pytest.raises(ValueError, match="mine"), src.lamp_window(power=0.5):
        raise ValueError("mine")
    src._dimmer_wire = 18000
    src.close()


def test_lamp_window_raises_when_off_fails_after_normal_body(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _link_ok(src)

    def always_fail():
        raise OSError("spi")

    src.dimmer_off = always_fail
    with pytest.raises(OSError), src.lamp_window(power=0.5):
        pass
    src._dimmer_wire = 18000
    src.close()


def test_keepalive_failure_sends_off_after_one_bad_resend(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.set_dimmer_alpha(90.0)
    thread = src._dimmer_thread
    real = src._exchange
    state = {"failed": False}

    def exchange(*a, **k):
        if not state["failed"] and a[1:] == (0xD1,) and a[0] == 9000:
            state["failed"] = True
            raise RuntimeError("boom")
        return real(*a, **k)

    src._exchange = exchange
    assert _wait(lambda: not thread.is_alive())
    assert state["failed"]
    assert src._spi.sent[-1][:2] == _OFF_PREFIX
    src.close()


def test_failed_set_leaves_lamp_off_state(spi_mcu_source):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src._spi.raise_on_xfer = OSError("spi")
    with pytest.raises(OSError):
        src.set_dimmer_alpha(90.0)
    src._spi.raise_on_xfer = None
    assert src.dimmer_window_left_s() is None
    assert not src.is_dimmer_active
    src.close()


@pytest.fixture
def fast_poll(monkeypatch):
    from mpp_sdk.io import spi_mcu

    monkeypatch.setattr(spi_mcu, "_LINK_POLL_S", 0.001)
    monkeypatch.setattr(spi_mcu, "_LINK_CONFIRM_S", 0.05)


def _refused(src, **kw):
    with pytest.raises(DimmerRefused), src.lamp_window(power=0.5, **kw):
        pytest.fail("window must not open")
    assert not src.is_dimmer_active
    assert src._spi.sent[-1][:2] == _OFF_PREFIX


def test_lamp_window_refused_without_reply(spi_mcu_source, fast_poll):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    _refused(src)
    src.close()


def test_lamp_window_refused_when_link_not_ok(spi_mcu_source, fast_poll):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.dimmer_status = lambda: parse_status_frame(_status_frame(flags=0x0E))
    _refused(src)
    src.close()


def test_lamp_window_refused_when_tripped_final_status(spi_mcu_source, fast_poll):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    src.dimmer_status = lambda: parse_status_frame(_status_frame(flags=0x1F))
    _refused(src)
    src.close()


def test_lamp_window_polls_past_bad_crc(spi_mcu_source, fast_poll):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    zero = _miso_frame(0, 0, 0, 0)
    bad = _status_frame(corrupt=True)
    # set, then (request, reply) pairs: two bad polls of two attempts, then good
    src._spi.responses = [zero] + [zero, bad] * 4 + [zero, _status_frame()]
    with src.lamp_window(power=0.5):
        assert src.is_dimmer_active
    assert not src.is_dimmer_active
    src.close()


def test_lamp_window_good_status_on_second_poll(spi_mcu_source, fast_poll):  # noqa: F811
    src = spi_mcu_source(dimmer_keepalive_s=0.01)
    answers = iter([None, parse_status_frame(_status_frame())])
    src.dimmer_status = lambda: next(answers)
    with src.lamp_window(power=0.5):
        pass
    src.close()
