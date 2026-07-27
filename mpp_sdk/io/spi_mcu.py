"""SPI-connected RP2040 Pico source — Phase 5a HIL link."""

from __future__ import annotations

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


def _to_signed_i16(raw: int) -> int:
    return raw - 65536 if raw >= 32768 else raw


class SpiMcuSource(SignalSource):
    """SignalSource backed by the RP2040 Pico over SPI (HIL mode).

    The Pico firmware acts as SPI slave on SPI1 (GPIO10-13). Every
    ``write()`` call sends a 12-byte full-duplex frame (see
    ``firmware/pipico_board/README.md``'s "Operating Modes"/"Sensing"
    sections and plan 014 for the full byte-level design)::

        MOSI (RPi -> Pico): [ DUTY_H | DUTY_L | CHECKSUM | 0x00 x 9 ]
        MISO (Pico -> RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L
                               | TEMP_H | TEMP_L | CHECKSUM | 0x00 x 3 ]

    The duty cycle is a u16 (0 = 0 %, 65535 = 100 %). V, I, and Vout are
    calibrated millivolts/milliamperes as saturating u16 (not raw ADC
    counts - the firmware does the calibration). Temp is a big-endian
    ``i16`` in centi-Celsius, or the sentinel -32768 if no probe is
    connected (see ``temperature_c``). ``CHECKSUM`` is an XOR over the
    preceding data bytes in each direction; a mismatched frame is
    corrupted-but-complete (passed the firmware's own frame-timeout check)
    and is rejected - the last-good values are kept instead.

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
        self._last_good_raw = (0, 0, 0, _TEMP_NOT_AVAILABLE_RAW)

    # ── internal ──────────────────────────────────────────────────────────────

    def _transact(self, duty: float) -> tuple[int, int, int, int]:
        """Send *duty*, return ``(v_raw, i_raw, vout_raw, temp_raw)``.

        Returns the last-good values instead if the MISO checksum doesn't
        match - a corrupted-but-complete frame must not be applied as if
        it were real telemetry (plan 014).
        """
        duty_u16 = max(0, min(65535, round(duty * 65535)))
        duty_h, duty_l = duty_u16 >> 8, duty_u16 & 0xFF
        tx = [duty_h, duty_l, duty_h ^ duty_l] + [0] * 9
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
        self._last_good_raw = (v_raw, i_raw, vout_raw, temp_raw)
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
        v_raw, i_raw, vout_raw, temp_raw = self._transact(self._duty)
        self._v = v_raw * self._v_scale + self._v_offset
        self._i = i_raw * self._i_scale + self._i_offset
        self._vout = vout_raw * self._v_scale
        self._temp_raw = temp_raw
        self._has_read = True

    # ── extras ───────────────────────────────────────────────────────────────

    def soft_stop(self) -> None:
        """Drive duty cycle to zero (safe shutdown)."""
        self.write(0.0)

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
