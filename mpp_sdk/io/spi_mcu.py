"""SPI-connected RP2040 Pico source — Phase 5a HIL link."""

from __future__ import annotations

import time

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

# Curve-tracer bulk-read protocol (plan 018) - must match
# firmware/pipico_board/src/spi_slave_pio.rs's constants of the same name
# and mode_curve_tracer::TRACER_SWEEP_POINTS exactly.
_CMD_REQUEST_BULK_DUMP = 0xB1
_BULK_MAGIC = 0xC5
_TRACER_SWEEP_POINTS = 20
_BULK_FRAME_LEN = 2 + _TRACER_SWEEP_POINTS * 4 + 1


def _to_signed_i16(raw: int) -> int:
    return raw - 65536 if raw >= 32768 else raw


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
    preceding data bytes in each direction; a mismatched frame is
    corrupted-but-complete (passed the firmware's own frame-timeout check)
    and is rejected - the last-good values are kept instead. ``CMD``/
    ``ACK`` are the curve-tracer bulk-read handshake bytes (plan 018,
    see ``request_sweep()``) - both 0 in normal operation, so plain
    ``read()``/``write()`` usage is unaffected.

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

    def _transact(self, duty: float, cmd: int = 0) -> tuple[int, int, int, int, int]:
        """Send *duty* (and, if given, a curve-tracer bulk-read *cmd* byte).

        Returns ``(v_raw, i_raw, vout_raw, temp_raw, ack)`` - ``ack`` is the
        curve-tracer bulk-read handshake byte (plan 018): 0 in normal
        operation, ``0x80 | point_count`` on the frame acking a
        ``_CMD_REQUEST_BULK_DUMP``. Returns the last-good values instead if
        the MISO checksum doesn't match - a corrupted-but-complete frame
        must not be applied as if it were real telemetry (plan 014).
        """
        duty_u16 = max(0, min(65535, round(duty * 65535)))
        duty_h, duty_l = duty_u16 >> 8, duty_u16 & 0xFF
        tx = [duty_h, duty_l, duty_h ^ duty_l, cmd] + [0] * 8
        rx = self._spi.xfer2(list(tx))

        data = rx[0:8]
        expected_checksum = 0
        for byte in data:
            expected_checksum ^= byte
        if rx[8] != expected_checksum:
            return self._last_good_raw

        v_raw = (rx[0] << 8) | rx[1]
        i_raw = (rx[2] << 8) | rx[3]
        vout_raw = (rx[4] << 8) | rx[5]
        temp_raw = (rx[6] << 8) | rx[7]
        ack = rx[9]
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
        v_raw, i_raw, vout_raw, temp_raw, _ack = self._transact(self._duty)
        self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)

    # ── extras ───────────────────────────────────────────────────────────────

    def soft_stop(self) -> None:
        """Drive duty cycle to zero (safe shutdown)."""
        self.write(0.0)

    def request_sweep(
        self, poll_attempts: int = 20, poll_interval_s: float = 0.05
    ) -> list[tuple[float, float]] | None:
        """Fetch the firmware's curve-tracer sweep result, if any (plan 018).

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

        Raises ``RuntimeError`` if the bulk-read frame's magic byte or
        checksum doesn't match, or its point count disagrees with the ack's
        - a real link fault, not a "nothing ready yet" case.
        """
        v_raw, i_raw, vout_raw, temp_raw, ack = self._transact(
            self._duty, cmd=_CMD_REQUEST_BULK_DUMP
        )
        self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)

        for _ in range(poll_attempts):
            if ack & 0x80:
                return self._bulk_read(ack & 0x7F)
            time.sleep(poll_interval_s)
            v_raw, i_raw, vout_raw, temp_raw, ack = self._transact(self._duty)
            self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)
        return None

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
        bulk frame's own count field (plan 018's "cheap corruption signal").
        """
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
