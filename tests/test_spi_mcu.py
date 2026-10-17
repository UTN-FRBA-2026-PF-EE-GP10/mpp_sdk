"""Unit tests for SpiMcuSource.

`spidev` is a real Linux-only C-backed module and isn't installed in the
base dev environment (it's the optional ``[hardware]`` extra) - a minimal
fake is injected into ``sys.modules`` before importing
``mpp_sdk.io.spi_mcu`` so these tests run everywhere.
"""

import math
import sys
import types

import pytest


class _FakeSpiDev:
    """Stands in for `spidev.SpiDev`. `next_rx`, if set, is returned by the
    next `xfer2()` call (and cleared); otherwise `responses` (if non-empty)
    is popped from the front; otherwise an all-zero 12-byte MISO frame is
    returned. That frame does *not* validate - CRC-8 over nine zero bytes
    is 0x0F, not 0x00 - so it stands in for "link says nothing usable",
    which is what the tests using it expect."""

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
            self._last_rx = rx
            return rx
        if self.responses:
            rx = self.responses.pop(0)
            self._last_rx = rx
            return rx
        if hasattr(self, "_last_rx"):
            return self._last_rx
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

    def _factory(*args, settling_time_s: float = 0.0, **kwargs):
        return SpiMcuSource(*args, settling_time_s=settling_time_s, **kwargs)

    return _factory


def _miso_frame(
    v_raw: int,
    i_raw: int,
    vout_raw: int,
    temp_raw: int,
    *,
    ack: int = 0,
    corrupt: bool = False,
    settled: int = 1,
) -> list[int]:
    # Imported here, not at module scope: `mpp_sdk.io.spi_mcu` pulls in
    # `spidev`, which only exists once the `spi_mcu_source` fixture has
    # installed its fake. Every caller of this helper takes that fixture.
    from mpp_sdk.io.spi_mcu import crc8

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
    checksum = crc8([*data, ack, settled])
    if corrupt:
        checksum ^= 0x01
    return [*data, checksum, ack, settled, 0]


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
    from mpp_sdk.io.spi_mcu import crc8

    assert src._spi.sent[-1][:4] == [0x80, 0x00, crc8([0x80, 0x00, 0x00]), 0x00]


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
# Checksum rejection
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


@pytest.mark.parametrize("requested", [float("nan"), float("inf"), float("-inf")])
def test_write_sends_zero_duty_for_a_non_finite_request(spi_mcu_source, requested):
    """min(1.0, nan) is 1.0, so a plain clamp would send full duty."""
    src = spi_mcu_source()
    src.write(requested)
    assert src.duty == 0.0
    duty_h, duty_l = src._spi.sent[-1][0], src._spi.sent[-1][1]
    assert (duty_h, duty_l) == (0, 0)


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
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src.request_sweep(poll_attempts=0)
    # duty defaults to 0.0 -> duty_h=duty_l=0; cmd is byte index 3 and
    # participates in the checksum (index 2), so checksum = crc8(0, 0, 0xB1).
    assert src._spi.sent[0][:4] == [0x00, 0x00, crc8([0x00, 0x00, 0xB1]), 0xB1]


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
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src.start_sweep()
    # duty defaults to 0.0 -> duty_h=duty_l=0; checksum = crc8(0, 0, 0xB2).
    assert src._spi.sent[-1][:4] == [0x00, 0x00, crc8([0x00, 0x00, 0xB2]), 0xB2]


def test_release_relay_sends_cmd_byte(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src.release_relay()
    # duty defaults to 0.0 -> duty_h=duty_l=0; checksum = crc8(0, 0, 0xB3).
    assert src._spi.sent[-1][:4] == [0x00, 0x00, crc8([0x00, 0x00, 0xB3]), 0xB3]


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
    from mpp_sdk.io.spi_mcu import crc8

    # ack is 0 on a progress frame, but still covered - matches firmware's
    # build_progress_frame.
    checksum = crc8([*data, 0, 0])
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


# ------------------------------------------------------------------
# Missing-board detection
# ------------------------------------------------------------------


def test_consecutive_bad_frames_counts_invalid_frames_and_resets(spi_mcu_source):
    """SPI has no presence detection: with no board attached MISO floats,
    every frame fails its checksum, and `_transact` keeps serving
    last-good telemetry without raising. The count is the only signal
    that nothing is on the other end."""
    src = spi_mcu_source()
    assert src.consecutive_bad_frames == 0

    # A floating MISO line reads all-ones or all-zeros; neither matches
    # the CRC of its own payload.
    src._spi.responses = [[0xFF] * 12, [0x00] * 12, [0xFF] * 12]
    for _ in range(3):
        src.write(0.0)
    assert src.consecutive_bad_frames == 3

    src._spi.next_rx = _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)
    src.write(0.0)
    assert src.consecutive_bad_frames == 0


def test_a_bad_frame_does_not_raise_so_the_count_is_the_only_signal(spi_mcu_source):
    """Pins the behaviour the count exists to compensate for - if this
    ever starts raising, the server's link-down check should be revisited
    rather than left as dead code."""
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(v_raw=5000, i_raw=250, vout_raw=3300, temp_raw=0)
    src.write(0.0)

    src._spi.next_rx = [0xFF] * 12
    src.write(0.0)  # must not raise
    assert src.read() == pytest.approx((5.0, 0.25))
    assert src.consecutive_bad_frames == 1


def test_read_waits_for_settled_flag_when_duty_changed(spi_mcu_source):
    src = spi_mcu_source(settling_time_s=0.05)
    src._spi.next_rx = _miso_frame(v_raw=10000, i_raw=500, vout_raw=0, temp_raw=0, settled=1)
    src.write(0.0)
    v, i = src.read()
    assert v == pytest.approx(10.0)

    src._spi.responses = [
        _miso_frame(v_raw=10000, i_raw=500, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=8000, i_raw=600, vout_raw=0, temp_raw=0, settled=1),
    ]
    src.write(0.5)
    v, i = src.read()
    assert v == pytest.approx(8.0)
    assert i == pytest.approx(0.6)


def _fast_settle_timeout(monkeypatch):
    module = sys.modules["mpp_sdk.io.spi_mcu"]
    monkeypatch.setattr(module, "_SETTLE_FIRST_POLL_S", 0.0)
    monkeypatch.setattr(module, "_SETTLE_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(module, "_SETTLE_TIMEOUT_S", 0.02)


def test_read_never_applies_an_unsettled_frame(spi_mcu_source, monkeypatch):
    """The firmware zeroes its telemetry on a duty change. Before, read()
    applied those frames and returned 0 V / 0 A as a measurement."""
    src = spi_mcu_source(settling_time_s=0.05)
    _fast_settle_timeout(monkeypatch)
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=9000, i_raw=400, vout_raw=0, temp_raw=0, settled=1),
    ]
    src.write(0.4)
    v, i = src.read()
    assert v == pytest.approx(9.0)
    assert i == pytest.approx(0.4)


def test_read_returns_nan_when_no_settled_frame_arrives_and_retries(spi_mcu_source, monkeypatch):
    src = spi_mcu_source(settling_time_s=0.05)
    _fast_settle_timeout(monkeypatch)
    src._spi.next_rx = _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0)
    src.write(0.4)
    v, i = src.read()
    assert math.isnan(v)
    assert math.isnan(i)

    # The next read asks again instead of serving the NaN for good.
    src._spi.next_rx = _miso_frame(v_raw=9000, i_raw=400, vout_raw=0, temp_raw=0, settled=1)
    v, i = src.read()
    assert v == pytest.approx(9.0)


def test_a_held_duty_still_waits_for_a_fresh_settled_measurement(spi_mcu_source, monkeypatch):
    """Found on the bench: InCond and P&O hold the duty sometimes. The
    write exchange then returned the firmware's zeroed telemetry and read()
    passed it on as 0 V / 0 A, while the scope showed no drop."""
    src = spi_mcu_source(settling_time_s=0.05)
    _fast_settle_timeout(monkeypatch)
    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=17000, i_raw=260, vout_raw=0, temp_raw=0, settled=1),
    ]
    src.write(0.42)
    assert src.read() == (pytest.approx(17.0), pytest.approx(0.26))

    src._spi.responses = [
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0),
        _miso_frame(v_raw=16900, i_raw=261, vout_raw=0, temp_raw=0, settled=1),
    ]
    src.write(0.42)  # same duty
    write_tx = src._spi.sent[-1]
    assert write_tx[3] == 0x01  # CMD_SET_DUTY: the firmware measures again
    v, i = src.read()
    assert v == pytest.approx(16.9)
    assert i == pytest.approx(0.261)


def test_write_without_settling_sends_a_plain_frame(spi_mcu_source):
    src = spi_mcu_source(settling_time_s=0.0)
    src._spi.next_rx = _miso_frame(v_raw=17000, i_raw=260, vout_raw=0, temp_raw=0)
    src.write(0.42)
    assert src._spi.sent[-1][3] == 0x00
    assert src.read() == (pytest.approx(17.0), pytest.approx(0.26))


def test_read_resends_the_duty_once_when_no_settled_measurement_arrives(
    spi_mcu_source, monkeypatch
):
    """A duty frame lost on the wire leaves the firmware on the old duty with
    no new measurement. read() sends the duty again before it gives up."""
    src = spi_mcu_source(settling_time_s=0.05)
    _fast_settle_timeout(monkeypatch)
    unsettled = _miso_frame(v_raw=0, i_raw=0, vout_raw=0, temp_raw=0, settled=0)
    src._spi.next_rx = unsettled
    src.write(0.42)
    # Unsettled until the resend, then settled.
    src._spi.responses = [unsettled] * 3
    real_xfer = src._spi.xfer2

    def xfer(tx):
        if tx[3] == 0x01 and len(src._spi.sent) > 1:
            src._spi.responses = [
                unsettled,
                _miso_frame(v_raw=17000, i_raw=260, vout_raw=0, temp_raw=0, settled=1),
            ]
        return real_xfer(tx)

    src._spi.xfer2 = xfer
    v, i = src.read()
    assert v == pytest.approx(17.0)
    assert sum(1 for tx in src._spi.sent if tx[3] == 0x01) == 2


def test_default_dynamic_config_properties(spi_mcu_source):
    src = spi_mcu_source()
    assert src.vin_range == "low"
    assert src.vout_range == "low"
    assert src.ron_mohm == 6
    assert src.max31865_enabled is False
    assert src.cutoff_i_max_ma == 1000
    assert src.cutoff_v_max_mv == 40000
    assert src.psu_enabled is False
    assert src.psu_open_loop is False
    assert src.psu_vout_target_mv == 5000
    assert src.psu_fixed_duty == 0.5


def test_set_divider_ranges(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_divider_ranges("full", "mid")
    tx = src._spi.sent[-1]
    assert tx[3] == 0xC1
    assert tx[0] == 0  # Full
    assert tx[1] == 1  # Mid
    assert tx[2] == crc8([0, 1, 0xC1])
    assert src.vin_range == "full"
    assert src.vout_range == "mid"

    # Numeric integers
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_divider_ranges(2, 0)
    tx = src._spi.sent[-1]
    assert tx[0] == 2
    assert tx[1] == 0

    with pytest.raises(ValueError, match="Invalid vin_range"):
        src.set_divider_ranges("unknown", "low")

    with pytest.raises(ValueError, match="Invalid vout_range"):
        src.set_divider_ranges("low", "unknown")


def test_set_ron(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_ron(15)
    tx = src._spi.sent[-1]
    assert tx[3] == 0xC8
    assert ((tx[0] << 8) | tx[1]) == 15
    assert tx[2] == crc8([tx[0], tx[1], 0xC8])
    assert src.ron_mohm == 15

    with pytest.raises(ValueError):
        src.set_ron(-1)
    with pytest.raises(ValueError):
        src.set_ron(70000)


def test_set_max31865(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_max31865(True)
    tx = src._spi.sent[-1]
    assert tx[3] == 0xC2
    assert tx[0] == 0
    assert tx[1] == 1
    assert tx[2] == crc8([0, 1, 0xC2])
    assert src.max31865_enabled is True

    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_max31865(False)
    tx = src._spi.sent[-1]
    assert tx[1] == 0
    assert src.max31865_enabled is False


def test_set_cutoffs_and_reset(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_cutoffs(i_max_ma=900, v_max_mv=35000)

    # Two frames sent: CMD_SET_CONFIG_CUTOFF_I and CMD_SET_CONFIG_CUTOFF_V
    tx_i = src._spi.sent[-2]
    tx_v = src._spi.sent[-1]

    assert tx_i[3] == 0xC3
    assert ((tx_i[0] << 8) | tx_i[1]) == 900
    assert tx_i[2] == crc8([tx_i[0], tx_i[1], 0xC3])
    assert src.cutoff_i_max_ma == 900

    assert tx_v[3] == 0xC4
    assert ((tx_v[0] << 8) | tx_v[1]) == 35000
    assert tx_v[2] == crc8([tx_v[0], tx_v[1], 0xC4])
    assert src.cutoff_v_max_mv == 35000

    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.reset_cutoff()
    tx_rst = src._spi.sent[-1]
    assert tx_rst[3] == 0xC9
    assert tx_rst[0] == 0
    assert tx_rst[1] == 0
    assert tx_rst[2] == crc8([0, 0, 0xC9])

    with pytest.raises(ValueError):
        src.set_cutoffs(i_max_ma=-1)
    with pytest.raises(ValueError):
        src.set_cutoffs(v_max_mv=70000)
    # 0 used to turn the firmware check off; above the ceiling was unlimited.
    with pytest.raises(ValueError):
        src.set_cutoffs(i_max_ma=0)
    with pytest.raises(ValueError):
        src.set_cutoffs(i_max_ma=1001)
    with pytest.raises(ValueError):
        src.set_cutoffs(v_max_mv=40001)


def test_power_supply_mode(spi_mcu_source):
    from mpp_sdk.io.spi_mcu import crc8

    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_power_supply_mode(
        enabled=True, open_loop=True, vout_target_mv=12000, fixed_duty=0.4, confirm=True
    )

    # 4 frames: target, fixed_duty, then the mode frame twice (the firmware
    # arms on the first and switches on the second)
    tx_mode = src._spi.sent[-1]
    assert src._spi.sent[-2] == tx_mode
    tx_duty = src._spi.sent[-3]
    tx_target = src._spi.sent[-4]

    assert tx_target[3] == 0xC6
    assert ((tx_target[0] << 8) | tx_target[1]) == 12000

    assert tx_duty[3] == 0xC7
    assert ((tx_duty[0] << 8) | tx_duty[1]) == round(0.4 * 65535)

    assert tx_mode[3] == 0xC5
    assert tx_mode[0] == 1  # enabled
    assert tx_mode[1] == 1  # open loop
    assert tx_mode[2] == crc8([1, 1, 0xC5])

    assert src.psu_enabled is True
    assert src.psu_open_loop is True
    assert src.psu_vout_target_mv == 12000
    assert src.psu_fixed_duty == 0.4


def test_power_supply_mode_needs_confirm(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    with pytest.raises(ValueError, match="confirm"):
        src.set_power_supply_mode(enabled=True)
    with pytest.raises(ValueError, match="confirm"):
        src.configure(psu_enabled=True)
    assert src._spi.sent == []
    assert src.psu_enabled is False


def test_leaving_power_supply_mode_needs_no_confirm_and_one_frame(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.set_power_supply_mode(enabled=False, vout_target_mv=None, fixed_duty=None)
    assert len(src._spi.sent) == 1
    assert src._spi.sent[0][3] == 0xC5
    assert src._spi.sent[0][0] == 0


def test_configure_psu_target_alone_sends_no_mode_frame(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.configure(psu_vout_target_mv=12000)
    assert [tx[3] for tx in src._spi.sent] == [0xC6]


def test_batch_configure(spi_mcu_source):
    src = spi_mcu_source()
    src._spi.next_rx = _miso_frame(1000, 100, 0, 0)
    src.configure(
        vin_range="mid",
        ron_mohm=12,
        max31865=True,
        i_max_ma=900,
        psu_enabled=True,
        psu_confirm=True,
    )
    assert src.vin_range == "mid"
    assert src.ron_mohm == 12
    assert src.max31865_enabled is True
    assert src.cutoff_i_max_ma == 900
    assert src.psu_enabled is True
