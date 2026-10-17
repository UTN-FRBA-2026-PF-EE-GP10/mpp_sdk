"""SPI-connected RP2040 Pico source — Phase 5a HIL link."""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from .base import SignalSource
from .board import (
    CUTOFF_I_MAX_CEILING_MA,
    CUTOFF_V_MAX_CEILING_MV,
    PSU_VOUT_TARGET_CEILING_MV,
)

# spidev is Linux-only and lives in the optional [hardware] extra.
try:
    import spidev as _spidev
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "spidev is required for SpiMcuSource. Install it with: uv add 'mpp-sdk[hardware]'"
    ) from exc

# Bit pattern for "no temperature reading available" (MAX31865 disabled on
# the firmware side, no compatible probe) - matches firmware/pipico_board's
# `TEMP_NOT_AVAILABLE_CC = i16::MIN` sentinel exactly.
_TEMP_NOT_AVAILABLE_RAW = 0x8000
_TEMP_NOT_AVAILABLE_CC = -32768

# MPPT synchronous measurement protocol commands (matching spi_slave_pio.rs)
_CMD_SET_DUTY = 0x01
_CMD_READ_MEASUREMENT = 0x02

# Dynamic configuration protocol commands (matching spi_slave_pio.rs)
_CMD_SET_CONFIG_JUMPERS = 0xC1
_CMD_SET_CONFIG_MAX31865 = 0xC2
_CMD_SET_CONFIG_CUTOFF_I = 0xC3
_CMD_SET_CONFIG_CUTOFF_V = 0xC4
_CMD_SET_CONFIG_PSU = 0xC5
_CMD_SET_CONFIG_PSU_TARGET = 0xC6
_CMD_SET_CONFIG_FIXED_DUTY = 0xC7
_CMD_SET_CONFIG_RON = 0xC8
_CMD_RESET_CUTOFF = 0xC9

# Jumper divider ranges
_DIVIDER_RANGE_MAP: dict[str | int, int] = {
    "full": 0,
    "mid": 1,
    "low": 2,
    0: 0,
    1: 1,
    2: 2,
}

# Curve-tracer bulk-read protocol - must match
# firmware/pipico_board/src/spi_slave_pio.rs's constants of the same name
# and mode_curve_tracer::TRACER_SWEEP_POINTS exactly.
_CMD_REQUEST_BULK_DUMP = 0xB1
_BULK_MAGIC = 0xC5
_TRACER_SWEEP_POINTS = 20
_BULK_FRAME_LEN = 2 + _TRACER_SWEEP_POINTS * 4 + 1

# Curve-tracer sweep-trigger/relay-release commands - must match
# spi_slave_pio.rs's constants of the same name exactly.
_CMD_START_SWEEP = 0xB2
_CMD_RELEASE_RELAY = 0xB3

# Curve-tracer streaming-progress poll - must match spi_slave_pio.rs's
# CMD_STREAM_POLL and mode_curve_tracer.rs's SweepProgress/PROGRESS_FLAG_*
# exactly.
_CMD_STREAM_POLL = 0xB4

# Replay a curve stored in the firmware instead of sweeping a real panel -
# one byte per stored curve. Must match spi_slave_pio.rs's
# CMD_DEMO_SWEEP_DIM/CMD_DEMO_SWEEP_BRIGHT.
_CMD_DEMO_SWEEP = {False: 0xB5, True: 0xB6}

_PROGRESS_NO_SWEEP_INDEX = 0xFF
_PROGRESS_FLAG_ACTIVE = 0b01
_PROGRESS_FLAG_FINAL = 0b10

# Pause between reading an armed ack and clocking the bulk transaction,
# giving the firmware time to re-arm its DMA for the larger frame - see
# _bulk_read(). Microseconds would do; this is generous and costs nothing
# on a once-per-sweep transfer.
_BULK_READ_ARM_DELAY_S = 0.002

# Upper bound on request_sweep()'s poll interval: the firmware drops a
# frame it has waited on for longer than its own FRAME_TIMEOUT (100 ms,
# spi_slave_pio.rs) and resyncs, so polling slower than that leaves it
# timing out between our frames instead of exchanging with us. Kept a
# little under 100 ms for margin.
_MAX_POLL_INTERVAL_S = 0.08

# read() after a duty change: the firmware waits 2 ms, then up to 80 ms for
# Vin to settle, then takes 25 samples. So the first poll waits a little,
# and the timeout covers the worst case with margin.
_SETTLE_FIRST_POLL_S = 0.015
_SETTLE_POLL_INTERVAL_S = 0.004
_SETTLE_TIMEOUT_S = 0.150
_SETTLE_MAX_BAD_FRAMES = 20


def crc8(data: Sequence[int]) -> int:
    """CRC-8 (polynomial 0x07, init 0xFF) over *data* - the checksum on
    both 12-byte SPI frame directions. Must match `spi_slave_pio.rs`'s
    `crc8` exactly.

    Not an XOR, because an XOR is position-blind and a MOSI frame at duty
    0 is all zeros but the command byte: a byte-shifted copy of it XORs to
    the same value and is accepted. Measured on the bench - a
    2-byte-shifted start-sweep frame validated cleanly and applied 69%
    duty to the SEPIC gate against a commanded 0. A CRC's feedback makes
    it order-dependent, so a shifted frame fails.
    """
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _to_signed_i16(raw: int) -> int:
    return raw - 65536 if raw >= 32768 else raw


@dataclass(frozen=True)
class SweepProgress:
    """One in-progress-sweep update, from ``SpiMcuSource.poll_sweep_progress()``.

    ``voltage``/``current`` are already scaled to physical units, same
    convention as ``read()``. ``active`` goes ``False`` on the one extra
    update published when a sweep ends (see ``final_point``) - a consumer
    should stop drawing further updates and trust the next bulk-read
    result instead once it sees that.
    """

    index: int
    voltage: float
    current: float
    active: bool
    final_point: bool


class SpiMcuSource(SignalSource):
    """SignalSource backed by the RP2040 Pico over SPI (HIL mode).

    The Pico firmware acts as SPI slave on SPI1 (GPIO10-13). Every
    ``write()`` call sends a 12-byte full-duplex frame (see
    ``firmware/pipico_board/README.md``'s "Operating Modes"/"Sensing"
    sections for the full byte-level design)::

        MOSI (RPi -> Pico): [ DUTY_H | DUTY_L | CHECKSUM | CMD | 0x00 x 8 ]
        MISO (Pico -> RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L
                               | TEMP_H | TEMP_L | CHECKSUM | ACK | SETTLED | 0x00 ]

    The duty cycle is a u16 (0 = 0 %, 65535 = 100 %). V, I, and Vout are
    calibrated millivolts/milliamperes as saturating u16 (not raw ADC
    counts - the firmware does the calibration). Temp is a big-endian
    ``i16`` in centi-Celsius, or the sentinel -32768 if no probe is
    connected (see ``temperature_c``). ``CHECKSUM`` is a CRC-8 (polynomial
    0x07, init 0xFF; see ``crc8()`` above) over the frame's data bytes in
    each direction - ``DUTY_H``, ``DUTY_L``, ``CMD`` for MOSI, the eight
    telemetry bytes plus ``ACK`` and ``SETTLED`` for MISO. Both handshake bytes are
    covered because each is a command to the other side rather than a
    reading. A mismatched frame is corrupted-but-complete (passed the
    firmware's own frame-timeout check) and is rejected - the last-good
    V/I/Vout/temp are kept instead, while ``ack`` reports 0 rather than
    replaying a stale value (see ``_transact()``). ``CMD``/``ACK`` are the
    curve-tracer bulk-read handshake bytes (see ``request_sweep()``) -
    both 0 in normal operation, so plain ``read()``/``write()`` usage is
    unaffected. ``poll_sweep_progress()`` uses the same ``CMD``/``ACK``
    bytes for a different, one-exchange-lag handshake (see its docstring) -
    the two are mutually exclusive per exchange, never both at once.

    Its sweep-control methods (``start_sweep``, ``release_relay``,
    ``request_sweep``, ``poll_sweep_progress``) plus the context-manager
    protocol satisfy ``mpp_sdk.io.sweep_source.SweepSource``.

    Usage::

        with SpiMcuSource() as src:
            ctl = PerturbAndObserve(initial_duty=0.5, min_duty=0.1, max_duty=0.9)
            for _ in range(500):
                v, i = src.read()
                src.write(ctl.step(v, i))
    """

    _FRAME_LEN = 12

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        speed_hz: int = 200_000,
        mode: int = 0,
        v_scale: float = 1e-3,
        i_scale: float = 1e-3,
        v_offset: float = 0.0,
        i_offset: float = 0.0,
        initial_duty: float = 0.0,
        settling_time_s: float = 0.03,
        oversample_count: int = 0,
    ) -> None:
        """
        Parameters
        ----------
        bus, device:
            SPI bus and chip-select index (``/dev/spidevBUS.DEVICE``).
            On RPi5 the default SPI0 CE0 is bus=0, device=0.
        speed_hz:
            SPI clock frequency. 200 kHz is the current bench-validated
            speed (see ``scripts/spi_test.py``) - higher speeds have shown
            electrical crosstalk from the GPIO4 NeoPixel strip, re-check
            that file before raising this.
        mode:
            SPI mode (0-3). Must match firmware (default 0: CPOL=0, CPHA=0).
        v_scale, i_scale:
            Millivolt/milliamp -> physical-unit conversion factors (V/mV,
            A/mA). Default 1e-3 matches the firmware's calibrated output;
            override only if a different unit convention is wanted.
            ``v_scale`` also applies to ``vout``.
        v_offset, i_offset:
            Additive offset applied after scaling.
        initial_duty:
            Duty cycle sent on the first ``write()`` (0.0 - 1.0).
        settling_time_s:
            When > 0 (default), read() after a duty change waits for the
            firmware's settled measurement, up to ``_SETTLE_TIMEOUT_S``, and
            returns NaN if none arrives. When <= 0, read() returns the
            telemetry of the last frame without waiting.
        oversample_count:
            Deprecated parameter retained for backwards compatibility.
        """
        self._spi = _spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = mode

        self._v_scale = v_scale
        self._i_scale = i_scale
        self._v_offset = v_offset
        self._i_offset = i_offset

        self._settling_time_s = settling_time_s

        self._duty = float(initial_duty)
        self._v: float = 0.0
        self._i: float = 0.0
        self._vout: float = 0.0
        self._temp_raw: int = _TEMP_NOT_AVAILABLE_RAW
        self._has_read = False
        self._last_good_raw = (0, 0, 0, _TEMP_NOT_AVAILABLE_RAW, 0)
        # Frames validated since the last good one. A missing board is
        # otherwise invisible from this side: SPI has no presence
        # detection, so with nothing attached MISO simply floats, every
        # frame fails its checksum, and `_transact` quietly serves the
        # last-good telemetry forever. Counting the failures is what lets
        # a caller tell "the board is talking" from "nothing is there".
        self._consecutive_bad_frames = 0
        self._settled = True
        self._duty_changed = False
        self._last_write_time: float = 0.0

        # Dynamic configuration tracking (initialized to firmware defaults)
        self._vin_range: str | int = "low"
        self._vout_range: str | int = "low"
        self._ron_mohm: int = 6
        self._max31865_enabled: bool = False
        self._cutoff_i_max_ma: int = 1000
        self._cutoff_v_max_mv: int = 40000
        self._psu_enabled: bool = False
        self._psu_open_loop: bool = False
        self._psu_vout_target_mv: int = 5000
        self._psu_fixed_duty: float = 0.5

    # ── internal ──────────────────────────────────────────────────────────────

    def _xfer_raw(self, payload_u16: int, cmd: int) -> tuple[list[int], int] | None:
        """Low-level full-duplex exchange sending raw 16-bit payload and command byte."""
        val = max(0, min(65535, int(payload_u16)))
        byte_h, byte_l = val >> 8, val & 0xFF
        tx = [byte_h, byte_l, crc8([byte_h, byte_l, cmd]), cmd] + [0] * 8
        rx = self._spi.xfer2(list(tx))

        # The settled byte (rx[10]) is covered too: a frame with it set is
        # taken as the one measurement for the new duty.
        if rx[8] != crc8(rx[0:8] + [rx[9], rx[10]]):
            self._consecutive_bad_frames += 1
            return None
        self._consecutive_bad_frames = 0
        self._settled = bool(rx[10] & 0x01)
        return rx[0:8], rx[9]

    def _xfer_checked(self, duty: float, cmd: int) -> tuple[list[int], int] | None:
        """Low-level full-duplex exchange shared by ``_transact()`` and
        ``poll_sweep_progress()``: sends *duty*/*cmd* as a normal MOSI frame
        and validates the MISO checksum, without interpreting the 8 payload
        bytes' meaning - that differs between a telemetry frame and a
        progress frame, both otherwise the same shape. Returns
        ``(payload_bytes, ack)`` on a valid frame, ``None`` on a checksum
        mismatch (a corrupted-but-complete frame).
        """
        duty_u16 = round(duty * 65535)
        return self._xfer_raw(duty_u16, cmd)

    def _send_config_cmd(self, cmd: int, payload_u16: int = 0) -> int:
        """Send a configuration command with a 16-bit payload, update telemetry, and return ack."""
        result = self._xfer_raw(payload_u16, cmd)
        if result is None:
            v_raw, i_raw, vout_raw, temp_raw, _stale_ack = self._last_good_raw
            return 0
        payload, ack = result
        v_raw = (payload[0] << 8) | payload[1]
        i_raw = (payload[2] << 8) | payload[3]
        vout_raw = (payload[4] << 8) | payload[5]
        temp_raw = (payload[6] << 8) | payload[7]
        self._last_good_raw = (v_raw, i_raw, vout_raw, temp_raw, ack)
        self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)
        return ack

    def _transact(self, duty: float, cmd: int = 0) -> tuple[int, int, int, int, int]:
        """Send *duty* (and, if given, a curve-tracer bulk-read *cmd* byte).

        Returns ``(v_raw, i_raw, vout_raw, temp_raw, ack)`` - ``ack`` is the
        curve-tracer bulk-read handshake byte: 0 in normal operation,
        ``0x80 | point_count`` on the frame acking a
        ``_CMD_REQUEST_BULK_DUMP``. Returns the last-good V/I/Vout/temp
        instead if the MISO checksum doesn't match - a corrupted-but-complete
        frame must not be applied as if it were real telemetry.
        ``ack`` is different: it's an edge-triggered handshake signal, not a
        physical reading, so replaying a stale cached value (possibly from
        an already-consumed sweep, or from before any sweep existed) risks
        spuriously re-triggering ``_bulk_read()`` - a checksum failure
        always reports ``ack=0`` ("nothing new this frame") instead.
        """
        result = self._xfer_checked(duty, cmd)
        if result is None:
            v_raw, i_raw, vout_raw, temp_raw, _stale_ack = self._last_good_raw
            return v_raw, i_raw, vout_raw, temp_raw, 0

        payload, ack = result
        v_raw = (payload[0] << 8) | payload[1]
        i_raw = (payload[2] << 8) | payload[3]
        vout_raw = (payload[4] << 8) | payload[5]
        temp_raw = (payload[6] << 8) | payload[7]
        self._last_good_raw = (v_raw, i_raw, vout_raw, temp_raw, ack)
        return self._last_good_raw

    # ── SignalSource interface ────────────────────────────────────────────────

    def read(self) -> tuple[float, float]:
        """Return the (V, I) measurement, waiting for hardware settling if duty changed.

        Flow:
          1. Wait hardware settling window (~15 ms since duty was written).
          2. Send _CMD_READ_MEASUREMENT over SPI to query the settled measurement.
          3. Pico returns the settled measurement frame (is_settled=1).
        """
        if not self._has_read and not self._duty_changed:
            raise RuntimeError("SpiMcuSource.read() called before the first write()")

        if self._duty_changed and self._settling_time_s > 0:
            elapsed = time.monotonic() - self._last_write_time
            if elapsed < _SETTLE_FIRST_POLL_S:
                time.sleep(_SETTLE_FIRST_POLL_S - elapsed)

            deadline = time.monotonic() + _SETTLE_TIMEOUT_S
            settled = False
            while True:
                # Only a frame with the settled flag carries the new
                # measurement. The firmware zeroes its telemetry on a duty
                # change, so an unsettled frame reads as 0 V / 0 A.
                self._settled = False
                v_raw, i_raw, vout_raw, temp_raw, _ack = self._transact(
                    self._duty, cmd=_CMD_READ_MEASUREMENT
                )
                if self._settled:
                    self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)
                    settled = True
                    break
                if self._consecutive_bad_frames >= _SETTLE_MAX_BAD_FRAMES:
                    break
                if time.monotonic() > deadline:
                    break
                time.sleep(_SETTLE_POLL_INTERVAL_S)
            if settled:
                self._duty_changed = False
            else:
                # NaN, not the last value: the caller must see that this
                # step has no measurement (run_control_loop aborts on a
                # sustained invalid reading). _duty_changed stays set, so
                # the next read() asks again.
                self._v = math.nan
                self._i = math.nan

        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        """Send *duty_cycle* to the Pico.

        The duty cycle is clamped to [0.0, 1.0]. A value that is not a
        finite number is sent as 0.0: ``min(1.0, nan)`` is 1.0, so a plain
        clamp would turn a NaN into full duty.

        The firmware applies the duty, clears its old measurement, waits for
        the converter to settle and takes one filtered measurement. If the
        duty changed, the next ``read()`` asks for that measurement.
        """
        if not math.isfinite(duty_cycle):
            duty_cycle = 0.0
        new_duty = max(0.0, min(1.0, duty_cycle))
        duty_changed = abs(new_duty - self._duty) > 1e-4
        self._duty = new_duty
        self._send_cmd()

        if duty_changed:
            self._duty_changed = True
            self._settled = False
            self._last_write_time = time.monotonic()

    # ── extras ───────────────────────────────────────────────────────────────

    def soft_stop(self) -> None:
        """Drive duty cycle to zero (safe shutdown)."""
        self.write(0.0)

    def request_sweep(
        self, poll_attempts: int = 20, poll_interval_s: float = 0.05
    ) -> list[tuple[float, float]] | None:
        """Fetch the firmware's curve-tracer sweep result, if any.

        Three-step protocol: sends a bulk-dump request riding on a normal
        12-byte frame (current ``duty`` unchanged - a sweep already reroutes
        the panel off the SEPIC path firmware-side, so this doesn't disturb
        anything), polls subsequent normal frames for the ack (each still a
        real telemetry exchange - ``read()``/``vout``/``temperature_c``
        reflect it same as any ``write()``), then issues the distinct
        ``_BULK_FRAME_LEN``-byte transaction. Returns a list of ``(V, I)``
        tuples in the same physical units as ``read()``/``vout`` (scaled by
        ``v_scale``/``i_scale``), or ``None`` if no sweep result was ready
        to fetch within ``poll_attempts``.

        The request byte is re-sent on *every* poll, not just the first, so
        this also covers "a sweep is still running, wait for it" - the
        firmware answers "nothing ready" (ack 0) until its result lands,
        and only an ask that arrives after that gets armed. Asking once and
        then polling with a bare frame would silently never retry.

        ``poll_interval_s`` must stay below the firmware's own frame
        timeout (``FRAME_TIMEOUT``, 100 ms in ``spi_slave_pio.rs``):
        polling slower than that lets the firmware time out *between* the
        Pi's frames, which resets its handshake state machine mid-exchange
        and (before the matching firmware fix) dropped the very result
        being fetched. ``_MAX_POLL_INTERVAL_S`` enforces the ceiling.

        Raises ``RuntimeError`` if the bulk-read frame's magic byte or
        checksum doesn't match, or its point count disagrees with the ack's
        - a real link fault, not a "nothing ready yet" case.
        """
        if poll_interval_s > _MAX_POLL_INTERVAL_S:
            raise ValueError(
                f"poll_interval_s={poll_interval_s} exceeds the firmware's frame timeout "
                f"({_MAX_POLL_INTERVAL_S}s) - the firmware would time out between polls and "
                f"reset the bulk-read handshake, so the fetch could never complete"
            )

        ack = self._send_cmd(cmd=_CMD_REQUEST_BULK_DUMP)

        for _ in range(poll_attempts):
            if ack & 0x80:
                return self._bulk_read(ack & 0x7F)
            time.sleep(poll_interval_s)
            ack = self._send_cmd(cmd=_CMD_REQUEST_BULK_DUMP)
        return None

    def poll_sweep_progress(self) -> SweepProgress | None:
        """Poll the firmware's in-progress sweep state, for point-by-point
        drawing instead of waiting for a sweep to finish.

        Two-exchange protocol, mirroring the one-iteration lag in
        ``spi_slave_pio.rs``'s ``BulkState`` machine: the first exchange's
        MOSI carries ``_CMD_STREAM_POLL`` (its MISO is still whatever the
        firmware's previous state held - ordinary telemetry, applied via
        ``_apply_telemetry`` same as any other command byte); the *second*
        exchange's MISO carries the progress frame the firmware built in
        response, which is **not** telemetry-shaped and must not be passed
        to ``_apply_telemetry``.

        Returns ``None`` if no sweep has ever run yet, if either exchange's
        checksum fails, or if the payload doesn't look like a progress frame
        at all (see below) - this is a lossy, best-effort read (the bulk
        read remains authoritative once a sweep completes), so a dropped
        update is not reported as an error. Otherwise returns a
        ``SweepProgress`` - once a sweep has run, this keeps returning its
        final state (``active=False``) until the next sweep starts, since
        the firmware peeks rather than consumes.
        """
        self._send_cmd(cmd=_CMD_STREAM_POLL)
        result = self._xfer_checked(self._duty, cmd=0)
        if result is None:
            return None

        payload, _ack = result
        index = payload[0]
        flags = payload[5]
        final_point = bool(flags & _PROGRESS_FLAG_FINAL)

        if index == _PROGRESS_NO_SWEEP_INDEX:
            # 0xFF is also what a sweep that captured zero points (e.g.
            # auto_range() aborted immediately) reports as its one real
            # "sweep is over" update - there's no last point to give it a
            # real index, but it's not the same as "no sweep has ever run"
            # and must not be swallowed as one, or a consumer's `active`
            # state never gets the memo that the sweep ended. `final_point`
            # is what tells the two apart on the wire.
            if not final_point:
                return None
        elif index >= _TRACER_SWEEP_POINTS:
            # Not a valid point index, and not the no-sweep-yet sentinel
            # either. Most likely our CMD_STREAM_POLL request itself was
            # dropped (e.g. a MOSI checksum failure on that first exchange)
            # so the firmware never left Idle, and this second exchange's
            # MISO is just ordinary telemetry rather than a progress reply -
            # unlike the bulk-read handshake, there is no ack bit here to
            # confirm the reply is really what was asked for, so treat an
            # out-of-range index as "not trustworthy" rather than risk
            # rendering a bogus point built from misread V/I bytes.
            return None

        v_raw = (payload[1] << 8) | payload[2]
        i_raw = (payload[3] << 8) | payload[4]
        return SweepProgress(
            index=index,
            voltage=v_raw * self._v_scale + self._v_offset,
            current=i_raw * self._i_scale + self._i_offset,
            active=bool(flags & _PROGRESS_FLAG_ACTIVE),
            final_point=final_point,
        )

    def start_sweep(self) -> None:
        """Ask the firmware to start a curve-tracer sweep.

        Fire-and-forget - no ack, unlike ``request_sweep()``'s bulk-dump
        handshake. The relay may already be engaged from a previous sweep
        (multiple sweeps can run without releasing between them, see
        ``release_relay()``). Poll ``request_sweep()`` afterward to fetch
        the result once the sweep completes.
        """
        self._send_cmd(cmd=_CMD_START_SWEEP)

    def start_demo_sweep(self, bright: bool = False) -> None:
        """Ask the firmware to replay one of its two stored curves instead
        of sweeping a real panel.

        Same progress and bulk-read path as ``start_sweep()``, so the Pi,
        the server and the web UI are exercised over real SPI - but with
        no panel, no lamp and nothing dissipating in the bleed path. Use
        it to work on the loop away from a lit bench. Unlike the server's
        ``--demo`` flag, which fakes the source Pi-side, this still needs
        a board and does test the link.
        """
        self._send_cmd(cmd=_CMD_DEMO_SWEEP[bright])

    def release_relay(self) -> None:
        """Ask the firmware to disconnect the panel from the tracer's
        bleed path and hand it back to the SEPIC.

        The relay otherwise stays engaged across any number of sweeps
        started via ``start_sweep()`` or the physical ``But1`` press - it
        is no longer released automatically when a sweep ends.
        """
        self._send_cmd(cmd=_CMD_RELEASE_RELAY)

    # ── dynamic configuration ────────────────────────────────────────────────

    def set_divider_ranges(
        self,
        vin_range: str | int = "low",
        vout_range: str | int = "low",
    ) -> None:
        """Configure the ADC voltage divider jumper settings for Vin and Vout dynamically.

        Parameters
        ----------
        vin_range, vout_range:
            Divider range setting: 'low' (~27.3V), 'mid' (~51.5V), 'full' (~75.6V),
            or raw integer 2, 1, 0. Defaults to 'low'.
        """
        vin_key = vin_range.lower() if isinstance(vin_range, str) else vin_range
        vout_key = vout_range.lower() if isinstance(vout_range, str) else vout_range
        if vin_key not in _DIVIDER_RANGE_MAP:
            raise ValueError(
                f"Invalid vin_range '{vin_range}'. Expected 'full', 'mid', 'low', or 0, 1, 2"
            )
        if vout_key not in _DIVIDER_RANGE_MAP:
            raise ValueError(
                f"Invalid vout_range '{vout_range}'. Expected 'full', 'mid', 'low', or 0, 1, 2"
            )

        vin_val = _DIVIDER_RANGE_MAP[vin_key]
        vout_val = _DIVIDER_RANGE_MAP[vout_key]
        self._vin_range = vin_range
        self._vout_range = vout_range

        payload = (vin_val << 8) | vout_val
        self._send_config_cmd(_CMD_SET_CONFIG_JUMPERS, payload)

    def set_ron(self, ron_mohm: int = 6) -> None:
        """Configure switch on-resistance in mOhm dynamically.

        Parameters
        ----------
        ron_mohm:
            Switch on-resistance in mOhm (0..65535). Default: 6 mOhm (IPP060N06N).
        """
        if not (0 <= ron_mohm <= 65535):
            raise ValueError(f"ron_mohm={ron_mohm} out of range 0..65535")
        self._ron_mohm = ron_mohm
        self._send_config_cmd(_CMD_SET_CONFIG_RON, ron_mohm)

    def set_max31865(self, enabled: bool = False) -> None:
        """Enable or disable the MAX31865 RTD temperature sensor on the fly.

        Parameters
        ----------
        enabled:
            True to enable PT100 sensor polling; False to disable. Default: False.
        """
        self._max31865_enabled = bool(enabled)
        payload = 1 if enabled else 0
        self._send_config_cmd(_CMD_SET_CONFIG_MAX31865, payload)

    def set_cutoffs(
        self,
        i_max_ma: int | None = 1000,
        v_max_mv: int | None = 40000,
    ) -> None:
        """Configure hardware safety cutoff limits dynamically.

        Parameters
        ----------
        i_max_ma:
            Maximum panel current in mA, 1..``CUTOFF_I_MAX_CEILING_MA``.
            Default: 1000 mA (1.0 A). If None, it is left unchanged.
        v_max_mv:
            Maximum panel or output voltage in mV, 1..``CUTOFF_V_MAX_CEILING_MV``.
            Default: 40000 mV (40 V). If None, it is left unchanged.

        The firmware applies the same ceilings, so a host can only make the
        cutoffs tighter, never turn them off.
        """
        if i_max_ma is not None:
            if not (1 <= i_max_ma <= CUTOFF_I_MAX_CEILING_MA):
                raise ValueError(f"i_max_ma={i_max_ma} out of range 1..{CUTOFF_I_MAX_CEILING_MA}")
            self._cutoff_i_max_ma = i_max_ma
            self._send_config_cmd(_CMD_SET_CONFIG_CUTOFF_I, i_max_ma)

        if v_max_mv is not None:
            if not (1 <= v_max_mv <= CUTOFF_V_MAX_CEILING_MV):
                raise ValueError(f"v_max_mv={v_max_mv} out of range 1..{CUTOFF_V_MAX_CEILING_MV}")
            self._cutoff_v_max_mv = v_max_mv
            self._send_config_cmd(_CMD_SET_CONFIG_CUTOFF_V, v_max_mv)

    def reset_cutoff(self) -> None:
        """Reset a tripped hardware safety cutoff, restoring normal gate drive operation."""
        self._send_config_cmd(_CMD_RESET_CUTOFF, 0)

    def set_psu_target(self, vout_target_mv: int = 5000) -> None:
        """Set target output voltage in mV for power supply mode.

        Parameters
        ----------
        vout_target_mv:
            Target voltage in mV, 0..``PSU_VOUT_TARGET_CEILING_MV``.
            Default: 5000 mV (5.0 V).
        """
        if not (0 <= vout_target_mv <= PSU_VOUT_TARGET_CEILING_MV):
            raise ValueError(
                f"vout_target_mv={vout_target_mv} out of range 0..{PSU_VOUT_TARGET_CEILING_MV}"
            )
        self._psu_vout_target_mv = vout_target_mv
        self._send_config_cmd(_CMD_SET_CONFIG_PSU_TARGET, vout_target_mv)

    def set_psu_fixed_duty(self, fixed_duty: float = 0.5) -> None:
        """Set fixed duty cycle for power supply open-loop mode.

        Parameters
        ----------
        fixed_duty:
            Duty cycle (0.0..1.0). Default: 0.5 (50%).
        """
        fixed_duty = float(fixed_duty)
        if not math.isfinite(fixed_duty):
            fixed_duty = 0.0
        clamped = max(0.0, min(1.0, fixed_duty))
        self._psu_fixed_duty = clamped
        duty_u16 = round(clamped * 65535)
        self._send_config_cmd(_CMD_SET_CONFIG_FIXED_DUTY, duty_u16)

    def set_power_supply_mode(
        self,
        enabled: bool = False,
        open_loop: bool = False,
        vout_target_mv: int | None = 5000,
        fixed_duty: float | None = 0.5,
        *,
        confirm: bool = False,
    ) -> None:
        """Activate or deactivate bench power supply mode and configure its parameters.

        PowerSupply mode drives the converter with no Pi watchdog, so turning
        it on needs two checks: the caller passes ``confirm=True`` after it
        made sure the input is a bench supply and not the panel, and the
        firmware only switches after it gets the same frame twice.

        Parameters
        ----------
        enabled:
            True to activate power supply mode; False for MPPT tracker mode. Default: False.
        open_loop:
            True for open-loop (fixed duty); False for closed-loop PI regulation. Default: False.
        vout_target_mv:
            Target output voltage in mV when in closed-loop mode. Default: 5000 mV (5.0 V).
            If None, existing target is retained.
        fixed_duty:
            Duty cycle (0.0..1.0) when in open-loop mode. Default: 0.5 (50%).
            If None, existing fixed duty is retained.
        confirm:
            Must be True when ``enabled`` is True.
        """
        if enabled and not confirm:
            raise ValueError(
                "set_power_supply_mode(enabled=True) needs confirm=True: check that "
                "the input is a bench supply, not the panel"
            )
        if vout_target_mv is not None:
            self.set_psu_target(vout_target_mv)
        if fixed_duty is not None:
            self.set_psu_fixed_duty(fixed_duty)

        self._psu_enabled = bool(enabled)
        self._psu_open_loop = bool(open_loop)
        mode = 1 if enabled else 0
        loop_mode = 1 if open_loop else 0
        payload = (mode << 8) | loop_mode
        self._send_config_cmd(_CMD_SET_CONFIG_PSU, payload)
        if enabled:
            # The firmware arms on the first frame and switches on the second.
            self._send_config_cmd(_CMD_SET_CONFIG_PSU, payload)

    def configure(
        self,
        *,
        vin_range: str | int | None = None,
        vout_range: str | int | None = None,
        ron_mohm: int | None = None,
        max31865: bool | None = None,
        i_max_ma: int | None = None,
        v_max_mv: int | None = None,
        psu_enabled: bool | None = None,
        psu_open_loop: bool | None = None,
        psu_vout_target_mv: int | None = None,
        psu_fixed_duty: float | None = None,
        psu_confirm: bool = False,
    ) -> None:
        """Batch configure dynamic hardware and firmware parameters.
        ``psu_confirm`` is passed on as ``set_power_supply_mode(confirm=...)``."""
        if vin_range is not None or vout_range is not None:
            self.set_divider_ranges(
                vin_range=self._vin_range if vin_range is None else vin_range,
                vout_range=self._vout_range if vout_range is None else vout_range,
            )
        if ron_mohm is not None:
            self.set_ron(ron_mohm)
        if max31865 is not None:
            self.set_max31865(max31865)
        if i_max_ma is not None or v_max_mv is not None:
            self.set_cutoffs(i_max_ma=i_max_ma, v_max_mv=v_max_mv)
        # The mode frame goes out only when the mode is asked for, so a new
        # target or duty alone never needs the PowerSupply confirmation.
        if psu_vout_target_mv is not None:
            self.set_psu_target(psu_vout_target_mv)
        if psu_fixed_duty is not None:
            self.set_psu_fixed_duty(psu_fixed_duty)
        if psu_enabled is not None or psu_open_loop is not None:
            self.set_power_supply_mode(
                enabled=self._psu_enabled if psu_enabled is None else psu_enabled,
                open_loop=self._psu_open_loop if psu_open_loop is None else psu_open_loop,
                vout_target_mv=None,
                fixed_duty=None,
                confirm=psu_confirm,
            )

    def _send_cmd(self, cmd: int = 0) -> int:
        """Transact once at the current duty with *cmd*, apply the
        returned telemetry, and return the ack byte - the shared shape
        behind ``write()``/``start_sweep()``/``release_relay()``/
        ``request_sweep()``'s polling."""
        v_raw, i_raw, vout_raw, temp_raw, ack = self._transact(self._duty, cmd=cmd)
        self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)
        return ack

    def _apply_telemetry(self, v_raw: int, i_raw: int, vout_raw: int, temp_raw: int) -> None:
        """Update ``read()``/``vout``/``temperature_c`` state from one frame."""
        self._v = v_raw * self._v_scale + self._v_offset
        self._i = i_raw * self._i_scale + self._i_offset
        self._vout = vout_raw * self._v_scale
        self._temp_raw = temp_raw
        self._has_read = True

    def _bulk_read(self, ack_count: int) -> list[tuple[float, float]]:
        """Issue the bulk-read transaction and parse its response.

        Called only once ``request_sweep()`` has seen an armed ack -
        *ack_count* is that ack's point count, cross-checked against the
        bulk frame's own count field (a cheap corruption signal).
        """
        # The firmware only re-arms its DMA for the larger bulk frame
        # *after* the ack exchange completes, but its PIO shifts as soon
        # as we assert CS - it does not wait for the CPU. Firing the bulk
        # transaction back-to-back with the ack read (the one exchange
        # with no natural gap in front of it) can therefore start
        # clocking a transmitter that has not been armed yet, which reads
        # back as a corrupted leading byte. Found on-target: bad magic
        # bytes with the low bits shifted out.
        time.sleep(_BULK_READ_ARM_DELAY_S)
        rx = self._spi.xfer2([0] * _BULK_FRAME_LEN)

        if rx[0] != _BULK_MAGIC:
            raise RuntimeError(
                f"SpiMcuSource.request_sweep(): bad bulk-frame magic "
                f"(got {rx[0]:#04x}, expected {_BULK_MAGIC:#04x})"
            )

        data = rx[:-1]
        expected_checksum = 0
        for byte in data:
            expected_checksum ^= byte
        if rx[-1] != expected_checksum:
            raise RuntimeError("SpiMcuSource.request_sweep(): bulk-frame checksum mismatch")

        count = rx[1]
        if count != ack_count:
            raise RuntimeError(
                f"SpiMcuSource.request_sweep(): point-count mismatch "
                f"(ack said {ack_count}, bulk frame said {count})"
            )
        if count > _TRACER_SWEEP_POINTS:
            # A weak XOR checksum can pass even with multi-bit corruption -
            # a count this large would index past the frame's point data
            # (rx is only _BULK_FRAME_LEN bytes) rather than just being
            # wrong, so this is checked explicitly instead of trusting the
            # count/checksum checks above to always catch it.
            raise RuntimeError(
                f"SpiMcuSource.request_sweep(): implausible point count {count} "
                f"(max {_TRACER_SWEEP_POINTS})"
            )

        points = []
        for idx in range(count):
            base = 2 + idx * 4
            v_raw = (rx[base] << 8) | rx[base + 1]
            i_raw = (rx[base + 2] << 8) | rx[base + 3]
            points.append(
                (v_raw * self._v_scale + self._v_offset, i_raw * self._i_scale + self._i_offset)
            )
        return points

    @property
    def consecutive_bad_frames(self) -> int:
        """Frames that failed validation since the last good one.

        Zero whenever the link is healthy. A sustained non-zero count
        means no valid frame is arriving at all, which is what a
        disconnected or unpowered board looks like - see the note where
        this is reset.
        """
        return self._consecutive_bad_frames

    @property
    def duty(self) -> float:
        """Last duty cycle sent to the Pico."""
        return self._duty

    @property
    def vout(self) -> float:
        """Converter output voltage from the last ``write()`` transaction."""
        return self._vout

    @property
    def temperature_c(self) -> float | None:
        """Panel temperature in Celsius, or ``None`` if unavailable.

        The MAX31865 probe driver is disabled on the firmware side (no
        compatible probe on the bench) - this reads ``None`` until it's
        re-enabled.
        """
        signed = _to_signed_i16(self._temp_raw)
        if signed == _TEMP_NOT_AVAILABLE_CC:
            return None
        return signed / 100.0

    @property
    def vin_range(self) -> str | int:
        """Currently configured Vin ADC divider range ('low', 'mid', 'full')."""
        return self._vin_range

    @property
    def vout_range(self) -> str | int:
        """Currently configured Vout ADC divider range ('low', 'mid', 'full')."""
        return self._vout_range

    @property
    def ron_mohm(self) -> int:
        """Currently configured switch on-resistance in mOhm."""
        return self._ron_mohm

    @property
    def max31865_enabled(self) -> bool:
        """Whether MAX31865 RTD temperature sensor polling is enabled."""
        return self._max31865_enabled

    @property
    def cutoff_i_max_ma(self) -> int:
        """Current hardware cutoff limit for current in mA."""
        return self._cutoff_i_max_ma

    @property
    def cutoff_v_max_mv(self) -> int:
        """Current hardware cutoff limit for voltage in mV."""
        return self._cutoff_v_max_mv

    @property
    def psu_enabled(self) -> bool:
        """Whether power supply mode is enabled."""
        return self._psu_enabled

    @property
    def psu_open_loop(self) -> bool:
        """Whether power supply mode is in open-loop (fixed duty) mode."""
        return self._psu_open_loop

    @property
    def psu_vout_target_mv(self) -> int:
        """Target output voltage in mV for power supply closed-loop mode."""
        return self._psu_vout_target_mv

    @property
    def psu_fixed_duty(self) -> float:
        """Fixed duty cycle (0.0..1.0) for power supply open-loop mode."""
        return self._psu_fixed_duty

    # ── resource management ──────────────────────────────────────────────────

    def close(self) -> None:
        """Release the SPI device."""
        self._spi.close()

    def __enter__(self) -> SpiMcuSource:
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.soft_stop()
        finally:
            self.close()
