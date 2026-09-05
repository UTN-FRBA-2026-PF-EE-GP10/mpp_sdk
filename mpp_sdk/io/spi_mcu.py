"""SPI-connected RP2040 Pico source — Phase 5a HIL link."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .base import SignalSource

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
    sections and plan 014 for the full byte-level design)::

        MOSI (RPi -> Pico): [ DUTY_H | DUTY_L | CHECKSUM | CMD | 0x00 x 8 ]
        MISO (Pico -> RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L
                               | TEMP_H | TEMP_L | CHECKSUM | ACK | 0x00 x 2 ]

    The duty cycle is a u16 (0 = 0 %, 65535 = 100 %). V, I, and Vout are
    calibrated millivolts/milliamperes as saturating u16 (not raw ADC
    counts - the firmware does the calibration). Temp is a big-endian
    ``i16`` in centi-Celsius, or the sentinel -32768 if no probe is
    connected (see ``temperature_c``). ``CHECKSUM`` is an XOR over the
    frame's data bytes in each direction - ``DUTY_H^DUTY_L^CMD`` for MOSI,
    the eight telemetry bytes ``^ACK`` for MISO. Both handshake bytes are
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

    Usage::

        with SpiMcuSource() as src:
            ctl = PerturbAndObserve(initial_duty=0.5)
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
            electrical crosstalk from the GPIO4 NeoPixel strip (plan 013),
            re-check that file before raising this.
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
        """
        self._spi = _spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = mode

        self._v_scale = v_scale
        self._i_scale = i_scale
        self._v_offset = v_offset
        self._i_offset = i_offset

        self._duty = float(initial_duty)
        self._v: float = 0.0
        self._i: float = 0.0
        self._vout: float = 0.0
        self._temp_raw: int = _TEMP_NOT_AVAILABLE_RAW
        self._has_read = False
        self._last_good_raw = (0, 0, 0, _TEMP_NOT_AVAILABLE_RAW, 0)

    # ── internal ──────────────────────────────────────────────────────────────

    def _xfer_checked(self, duty: float, cmd: int) -> tuple[list[int], int] | None:
        """Low-level full-duplex exchange shared by ``_transact()`` and
        ``poll_sweep_progress()``: sends *duty*/*cmd* as a normal MOSI frame
        and validates the MISO checksum, without interpreting the 8 payload
        bytes' meaning - that differs between a telemetry frame and a
        progress frame, both otherwise the same shape. Returns
        ``(payload_bytes, ack)`` on a valid frame, ``None`` on a checksum
        mismatch (a corrupted-but-complete frame, plan 014).
        """
        duty_u16 = max(0, min(65535, round(duty * 65535)))
        duty_h, duty_l = duty_u16 >> 8, duty_u16 & 0xFF
        # `cmd` participates in the checksum (matches
        # spi_slave_pio.rs's apply_duty_frame) so a corrupted frame can't
        # spoof a bulk-dump request by chance; `cmd` is 0 on every call
        # except request_sweep()'s/poll_sweep_progress()'s first, so XOR
        # with 0 leaves the normal write()/read() checksum unchanged.
        tx = [duty_h, duty_l, duty_h ^ duty_l ^ cmd, cmd] + [0] * 8
        rx = self._spi.xfer2(list(tx))

        # The MISO checksum covers the 8 payload bytes and the ack byte
        # (rx[9]) - the latter is a command to us, not a reading, so a bit
        # flip setting its top bit would otherwise send us off to clock an
        # 83-byte bulk read against firmware still sending telemetry. It
        # sits after the checksum byte in the frame; that is only byte
        # order, both sides XOR it in the same way.
        expected_checksum = rx[9]
        for byte in rx[0:8]:
            expected_checksum ^= byte
        if rx[8] != expected_checksum:
            return None
        return rx[0:8], rx[9]

    def _transact(self, duty: float, cmd: int = 0) -> tuple[int, int, int, int, int]:
        """Send *duty* (and, if given, a curve-tracer bulk-read *cmd* byte).

        Returns ``(v_raw, i_raw, vout_raw, temp_raw, ack)`` - ``ack`` is the
        curve-tracer bulk-read handshake byte: 0 in normal operation,
        ``0x80 | point_count`` on the frame acking a
        ``_CMD_REQUEST_BULK_DUMP``. Returns the last-good V/I/Vout/temp
        instead if the MISO checksum doesn't match - a corrupted-but-complete
        frame must not be applied as if it were real telemetry (plan 014).
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
        """Return the (V, I) received in the last ``write()`` transaction."""
        if not self._has_read:
            raise RuntimeError("SpiMcuSource.read() called before the first write()")
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        """Send *duty_cycle* to the Pico and capture the returned telemetry.

        The duty cycle is clamped to [0.0, 1.0]. V/I/Vout/temperature are
        available via ``read()``/``vout``/``temperature_c`` afterward.
        """
        self._duty = max(0.0, min(1.0, duty_cycle))
        self._send_cmd()

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

    def release_relay(self) -> None:
        """Ask the firmware to disconnect the panel from the tracer's
        bleed path and hand it back to the SEPIC.

        The relay otherwise stays engaged across any number of sweeps
        started via ``start_sweep()`` or the physical ``But1`` press - it
        is no longer released automatically when a sweep ends.
        """
        self._send_cmd(cmd=_CMD_RELEASE_RELAY)

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
