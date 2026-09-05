"""Unit tests for SpiMcuSource.

`spidev` is a real Linux-only C-backed module and isn't installed in the
base dev environment (it's the optional ``[hardware]`` extra) - a minimal
fake is injected into ``sys.modules`` before importing
``mpp_sdk.io.spi_mcu`` so these tests run everywhere.
"""

import sys
import types

import pytest


class _FakeSpiDev:
    """Stands in for `spidev.SpiDev`. `next_rx`, if set, is returned by the
    next `xfer2()` call (and cleared); otherwise `responses` (if non-empty)
    is popped from the front; otherwise an all-zero 12-byte MISO frame is
    returned (its XOR checksum is trivially 0, so it validates)."""

    def __init__(self) -> None:
        self.max_speed_hz: int | None = None
        self.mode: int | None = None
        self.closed = False
        self.sent: list[list[int]] = []
        self.next_rx: list[int] | None = None
        self.responses: list[list[int]] = []
        self.raise_on_xfer: Exception | None = None

    def open(self, bus: int, device: int) -> None:
        self.bus, self.device = bus, device

    def xfer2(self, tx: list[int]) -> list[int]:
        if self.raise_on_xfer is not None:
            raise self.raise_on_xfer
        self.sent.append(list(tx))
        if self.next_rx is not None:
            rx, self.next_rx = self.next_rx, None
            return rx
        if self.responses:
            return self.responses.pop(0)
        return [0] * 12

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def spi_mcu_source(monkeypatch):
    """Import `SpiMcuSource` with a fake `spidev` module installed, and
    return the class - each test constructs its own instance so it gets
    its own `_FakeSpiDev`."""
    fake_module = types.ModuleType("spidev")
    fake_module.SpiDev = _FakeSpiDev
    monkeypatch.setitem(sys.modules, "spidev", fake_module)

    # `mpp_sdk.io.spi_mcu` may already be cached in sys.modules - e.g. from
    # another test file's own (differently-faked, or real) `spidev` import
    # earlier in the same pytest session. `import ... as _spidev` binds a
    # name once at that first import and a cached module isn't re-executed,
    # so without evicting it here, this fixture's fake would silently not
    # take effect and every test would fail against whichever `spidev` got
    # bound first. Force a fresh import so it binds to *this* fixture's fake.
    monkeypatch.delitem(sys.modules, "mpp_sdk.io.spi_mcu", raising=False)

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    return SpiMcuSource


def _miso_frame(
    v_raw: int, i_raw: int, vout_raw: int, temp_raw: int, *, ack: int = 0, corrupt: bool = False
) -> list[int]:
    data = [
        (v_raw >> 8) & 0xFF,
        v_raw & 0xFF,
        (i_raw >> 8) & 0xFF,
        i_raw & 0xFF,
        (vout_raw >> 8) & 0xFF,
        vout_raw & 0xFF,
        (temp_raw >> 8) & 0xFF,
        temp_raw & 0xFF,
    ]
    # ack participates in the checksum (see firmware's build_tx_frame) so
    # a flipped ack bit can't spoof "sweep ready" at the Pi.
    checksum = ack
    for byte in data:
        checksum ^= byte
    if corrupt:
        checksum ^= 0x01
    return [*data, checksum, ack, 0, 0]


# Mirrors spi_mcu.py's private _TRACER_SWEEP_POINTS/_BULK_MAGIC/
# _BULK_FRAME_LEN constants - must match firmware/pipico_board/src/
# spi_slave_pio.rs's bulk-read frame shape exactly.
_TEST_TRACER_SWEEP_POINTS = 20
_TEST_BULK_MAGIC = 0xC5
_TEST_BULK_FRAME_LEN = 2 + _TEST_TRACER_SWEEP_POINTS * 4 + 1


def _bulk_frame(
    points: list[tuple[int, int]],
    *,
    magic: int = _TEST_BULK_MAGIC,
    count_override: int | None = None,
    corrupt: bool = False,
) -> list[int]:
    count = len(points) if count_override is None else count_override
    data = [magic, count]
    for v_raw, i_raw in points:
        data += [(v_raw >> 8) & 0xFF, v_raw & 0xFF, (i_raw >> 8) & 0xFF, i_raw & 0xFF]
    data += [0] * (2 + _TEST_TRACER_SWEEP_POINTS * 4 - len(data))
    checksum = 0
    for byte in data:
        checksum ^= byte
    if corrupt:
        checksum ^= 0x01
    return [*data, checksum]


# ------------------------------------------------------------------
# Byte-order round-trip
# ------------------------------------------------------------------


def test_write_encodes_duty_and_mosi_checksum(spi_mcu_source):
    src = spi_mcu_source()
    src.write(0.5)
    # duty_u16 = round(0.5 * 65535) = 32768 = 0x8000
    assert src._spi.sent[-1][:3] == [0x80, 0x00, 0x80]  # checksum = 0x80 ^ 0x00


def test_read_decodes_calibrated_miso_frame(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)
    src.write(0.5)
    v, i = src.read()
    assert v == pytest.approx(5.0)
    assert i == pytest.approx(0.25)
    assert src.vout == pytest.approx(3.3)
    assert src.temperature_c == pytest.approx(0.0)


def test_temperature_sentinel_reads_as_none(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=-32768 & 0xFFFF)
    src.write(0.0)
    assert src.temperature_c is None


# ------------------------------------------------------------------
# Checksum rejection (plan 014)
# ------------------------------------------------------------------


def test_corrupted_miso_frame_keeps_last_good_values(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)
    src.write(0.5)

    src._spi.next_rx = _miso_frame(v_raw=1234, i_raw=999, vout_raw=8888, temp_raw=500, corrupt=True)
    src.write(0.5)

    v, i = src.read()
    assert v == pytest.approx(5.0)
    assert i == pytest.approx(0.25)
    assert src.vout == pytest.approx(3.3)


def test_transact_reports_ack_zero_on_checksum_failure_not_stale_cache(spi_mcu_source):
    """A corrupted frame must not replay a stale *armed* ack - unlike
    V/I/Vout/temp (legitimately held over from the last good frame), ack
    is an edge-triggered handshake signal: replaying a stale value could
    spuriously re-trigger `_bulk_read()` against an already-consumed (or
    never-existent) sweep."""
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=1000, i_raw=100, vout_raw=0, temp_raw=0, ack=0x85)
    _, _, _, _, ack = src._transact(0.0)
    assert ack == 0x85

    src._spi.next_rx = _miso_frame(
        v_raw=2000, i_raw=200, vout_raw=0, temp_raw=0, ack=0x85, corrupt=True
    )
    v_raw, _, _, _, ack = src._transact(0.0)
    assert ack == 0
    assert v_raw == 1000  # telemetry still replays the last-good frame


# ------------------------------------------------------------------
# Duty clamping
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0.0, 0.0), (1.0, 1.0), (-0.5, 0.0), (1.5, 1.0)],
)
def test_write_clamps_duty(spi_mcu_source, requested, expected):
    src = spi_mcu_source()
    src.write(requested)
    assert src.duty == pytest.approx(expected)


# ------------------------------------------------------------------
# read() before write()
# ------------------------------------------------------------------


def test_read_before_write_raises(spi_mcu_source):
    src = spi_mcu_source()
    with pytest.raises(RuntimeError):
        src.read()


def test_read_after_write_succeeds(spi_mcu_source):
    src = spi_mcu_source()
    src.write(0.5)
    src.read()  # does not raise


# ------------------------------------------------------------------
# __exit__ teardown
# ------------------------------------------------------------------


def test_exit_closes_even_if_soft_stop_raises(spi_mcu_source, monkeypatch):
    src = spi_mcu_source()

    def _raise(_duty, cmd=0):
        raise RuntimeError("simulated SPI fault")

    monkeypatch.setattr(src, "_transact", _raise)

    with pytest.raises(RuntimeError):
        src.__exit__(None, None, None)
    assert src._spi.closed


# ------------------------------------------------------------------
# request_sweep() - curve-tracer bulk-read protocol
# ------------------------------------------------------------------


def test_request_sweep_sends_cmd_byte(spi_mcu_source):
    src = spi_mcu_source()
    src.request_sweep(poll_attempts=0)
    # duty defaults to 0.0 -> duty_h=duty_l=0; cmd is byte index 3 and
    # participates in the checksum (index 2), so checksum = 0 ^ 0 ^ 0xB1.
    assert src._spi.sent[0][:4] == [0x00, 0x00, 0xB1, 0xB1]


def test_request_sweep_returns_none_when_never_armed(spi_mcu_source):
    src = spi_mcu_source()
    # Every response is a plain (ack=0) telemetry frame - never armed.
    result = src.request_sweep(poll_attempts=3, poll_interval_s=0)
    assert result is None


def test_request_sweep_resends_cmd_on_every_poll(spi_mcu_source):
    """Asking once and then polling with bare frames can never arm a sweep
    that is still running when the first ask goes out - the firmware only
    replies "ready" to a request that arrives *after* the result lands."""
    src = spi_mcu_source()
    src.request_sweep(poll_attempts=3, poll_interval_s=0)
    # 1 initial ask + 3 polls, every one carrying the request byte.
    assert len(src._spi.sent) == 4
    for frame in src._spi.sent:
        assert frame[3] == 0xB1


def test_flipped_ack_bit_does_not_trigger_a_bulk_read(spi_mcu_source):
    """A corrupted ack byte must fail the frame checksum rather than send
    us clocking an 83-byte bulk read at firmware that is still sending
    12-byte telemetry - the ack is a command to us, not a reading."""
    src = spi_mcu_source()
    frame = _miso_frame(v_raw=1000, i_raw=100, vout_raw=0, temp_raw=0, ack=0x00)
    frame[9] = 0x80  # bit flip on the wire, checksum left as-built
    src._spi.responses = [frame]
    result = src.request_sweep(poll_attempts=0)
    assert result is None
    # Only the request frame went out - no oversized bulk transaction.
    assert all(len(sent) == 12 for sent in src._spi.sent)


def test_request_sweep_rejects_poll_interval_past_firmware_timeout(spi_mcu_source):
    """Polling slower than the firmware's own frame timeout makes it time
    out between our frames and reset the handshake mid-exchange."""
    src = spi_mcu_source()
    with pytest.raises(ValueError, match="frame timeout"):
        src.request_sweep(poll_attempts=3, poll_interval_s=0.2)


def test_request_sweep_still_updates_telemetry_while_polling(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [_miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)]
    src.request_sweep(poll_attempts=0)
    v, i = src.read()
    assert v == pytest.approx(5.0)
    assert i == pytest.approx(0.25)


def test_request_sweep_fetches_points_when_armed(spi_mcu_source):
    src = spi_mcu_source()
    points = [(1000 * n, 100 * n) for n in range(5)]
    # 1) response to the request-carrying frame itself: never armed yet
    #    (the firmware only acks on the *next* frame - see spi_slave_pio.rs's
    #    BulkState doc comment).
    # 2) the following normal poll: now armed, ack = 0x80 | count.
    # 3) the bulk-read transaction's response.
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0x80 | len(points)),
        _bulk_frame(points),
    ]
    result = src.request_sweep(poll_attempts=5, poll_interval_s=0)
    assert result == [pytest.approx((v / 1000, i / 1000)) for v, i in points]
    # The bulk-read transaction is a distinct, larger transfer.
    assert len(src._spi.sent[-1]) == _TEST_BULK_FRAME_LEN


def test_request_sweep_raises_on_bad_magic(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0x81),
        _bulk_frame([(1, 1)], magic=0x00),
    ]
    with pytest.raises(RuntimeError, match="magic"):
        src.request_sweep(poll_attempts=5, poll_interval_s=0)


def test_request_sweep_raises_on_bulk_checksum_mismatch(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0x81),
        _bulk_frame([(1, 1)], corrupt=True),
    ]
    with pytest.raises(RuntimeError, match="checksum"):
        src.request_sweep(poll_attempts=5, poll_interval_s=0)


def test_request_sweep_raises_on_point_count_mismatch(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0),
        # Ack says 3 points ready...
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0x83),
        # ...but the bulk frame itself says 2 - a corruption signal.
        _bulk_frame([(1, 1), (2, 2)], count_override=2),
    ]
    with pytest.raises(RuntimeError, match="point-count mismatch"):
        src.request_sweep(poll_attempts=5, poll_interval_s=0)


def test_request_sweep_raises_on_implausible_point_count(spi_mcu_source):
    src = spi_mcu_source()
    # ack and bulk-frame counts agree (so the mismatch check above doesn't
    # catch it) but both say 30 - more than _TEST_TRACER_SWEEP_POINTS (20),
    # which would index past the frame if not checked explicitly.
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, ack=0x80 | 30),
        _bulk_frame([(1, 1), (2, 2)], count_override=30),
    ]
    with pytest.raises(RuntimeError, match="implausible point count"):
        src.request_sweep(poll_attempts=5, poll_interval_s=0)


# ------------------------------------------------------------------
# start_sweep()/release_relay() - SPI-triggered sweeps
# ------------------------------------------------------------------


def test_start_sweep_sends_cmd_byte(spi_mcu_source):
    src = spi_mcu_source()
    src.start_sweep()
    # duty defaults to 0.0 -> duty_h=duty_l=0; checksum = 0 ^ 0 ^ 0xB2.
    assert src._spi.sent[-1][:4] == [0x00, 0x00, 0xB2, 0xB2]


def test_release_relay_sends_cmd_byte(spi_mcu_source):
    src = spi_mcu_source()
    src.release_relay()
    # duty defaults to 0.0 -> duty_h=duty_l=0; checksum = 0 ^ 0 ^ 0xB3.
    assert src._spi.sent[-1][:4] == [0x00, 0x00, 0xB3, 0xB3]


def test_start_sweep_still_updates_telemetry(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)
    src.start_sweep()
    v, i = src.read()
    assert v == pytest.approx(5.0)
    assert i == pytest.approx(0.25)


# ------------------------------------------------------------------
# poll_sweep_progress() - point-by-point streaming
# ------------------------------------------------------------------


def _progress_frame(
    index: int,
    v_mv: int,
    i_ma: int,
    *,
    active: bool,
    final_point: bool,
    corrupt: bool = False,
) -> list[int]:
    flags = (0b01 if active else 0) | (0b10 if final_point else 0)
    data = [
        index & 0xFF,
        (v_mv >> 8) & 0xFF,
        v_mv & 0xFF,
        (i_ma >> 8) & 0xFF,
        i_ma & 0xFF,
        flags,
        0,
        0,
    ]
    checksum = 0
    for byte in data:
        checksum ^= byte
    if corrupt:
        checksum ^= 0x01
    return [*data, checksum, 0, 0, 0]  # ack=0 (a progress reply never also acks a bulk request)


def test_poll_sweep_progress_sends_stream_poll_then_a_plain_frame(spi_mcu_source):
    """One-iteration-lag protocol: the poll command rides the first
    exchange, the response to it rides the second."""
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(3, 12000, 150, active=True, final_point=False),
    ]
    src.poll_sweep_progress()
    assert len(src._spi.sent) == 2
    assert src._spi.sent[0][3] == 0xB4  # CMD_STREAM_POLL
    assert src._spi.sent[1][3] == 0x00  # plain duty frame


def test_poll_sweep_progress_parses_a_mid_sweep_point(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import SweepProgress

    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(3, 12000, 150, active=True, final_point=False),
    ]
    progress = src.poll_sweep_progress()
    assert progress == SweepProgress(
        index=3,
        voltage=pytest.approx(12.0),
        current=pytest.approx(0.15),
        active=True,
        final_point=False,
    )


def test_poll_sweep_progress_first_exchange_updates_telemetry_not_progress_fields(spi_mcu_source):
    """The first exchange's response is the firmware's previous (ordinary
    telemetry) state, not the progress frame - read()/vout() must reflect
    it same as any other command byte."""
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0),
        _progress_frame(3, 12000, 150, active=True, final_point=False),
    ]
    src.poll_sweep_progress()
    v, i = src.read()
    assert v == pytest.approx(5.0)
    assert i == pytest.approx(0.25)


def test_poll_sweep_progress_no_sweep_yet_returns_none(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(0xFF, 0, 0, active=False, final_point=False),
    ]
    assert src.poll_sweep_progress() is None


def test_poll_sweep_progress_corrupted_frame_returns_none_not_garbage(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(3, 12000, 150, active=True, final_point=False, corrupt=True),
    ]
    assert src.poll_sweep_progress() is None


def test_poll_sweep_progress_reports_the_final_point_flag(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(19, 8000, 210, active=False, final_point=True),
    ]
    progress = src.poll_sweep_progress()
    assert progress.active is False
    assert progress.final_point is True
    assert progress.index == 19


def test_poll_sweep_progress_zero_point_sweep_reports_final_not_none(spi_mcu_source):
    """A sweep that captured zero points (e.g. auto_range() aborted
    immediately) still uses index 0xFF for its one real "sweep is over"
    update - same sentinel as "no sweep has ever run" - but sets
    final_point, which is what tells the two apart. Losing that distinction
    would leave a consumer's `active` state stuck forever."""
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(0xFF, 0, 0, active=False, final_point=True),
    ]
    progress = src.poll_sweep_progress()
    assert progress is not None
    assert progress.active is False
    assert progress.final_point is True


def test_poll_sweep_progress_out_of_range_index_returns_none(spi_mcu_source):
    """An index that is neither a valid point (0..TRACER_SWEEP_POINTS) nor
    the no-sweep-yet sentinel (0xFF) isn't trustworthy as a progress frame
    at all - most likely our CMD_STREAM_POLL request was dropped (a MOSI
    checksum failure on the first exchange) and this second exchange's MISO
    is just ordinary telemetry, not a progress reply."""
    src = spi_mcu_source()
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0),
        _progress_frame(42, 12000, 150, active=True, final_point=False),
    ]
    assert src.poll_sweep_progress() is None
