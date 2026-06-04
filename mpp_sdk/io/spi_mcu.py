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


class SpiMcuSource(SignalSource):
    """SignalSource backed by the RP2040 Pico over SPI (HIL mode).

    The Pico firmware acts as SPI slave on SPI1 (GPIO10-13).
    Every ``write()`` call sends a 12-byte full-duplex frame:

        MOSI (RPi → Pico):  [ DUTY_H | DUTY_L | 0x00 … 0x00 ]  (12 bytes)
        MISO (Pico → RPi):  [ V_H    | V_L    | I_H  | I_L  | 0x00 … 0x00 ]

    The duty cycle is a u16 (0 = 0 %, 65535 = 100 %).
    V and I are 12-bit ADC counts converted to physical units via the
    calibration scale/offset parameters.

    Usage::

        with SpiMcuSource(v_scale=..., i_scale=...) as src:
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
        speed_hz: int = 4_000_000,
        mode: int = 0,
        v_scale: float = 3.3 / 4095.0,
        i_scale: float = 3.3 / 4095.0,
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
            SPI clock frequency. Keep below ~8 MHz for reliable slave-side
            sampling; 1 MHz is a safe starting point.
        mode:
            SPI mode (0–3). Must match firmware (default 0: CPOL=0, CPHA=0).
        v_scale, i_scale:
            ADC-count → physical-unit conversion factors (V/count, A/count).
            Default assumes a 3.3 V ADC reference with 12-bit resolution and
            no additional gain stage; update once the sense path is calibrated.
        v_offset, i_offset:
            Additive offset applied after scaling.
        initial_duty:
            Duty cycle sent on the first ``write()`` (0.0 – 1.0).
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

    # ── internal ──────────────────────────────────────────────────────────────

    def _transact(self, duty: float) -> tuple[float, float]:
        duty_u16 = max(0, min(65535, round(duty * 65535)))
        tx = [duty_u16 >> 8, duty_u16 & 0xFF] + [0] * 10
        rx = self._spi.xfer2(list(tx))
        v_raw = (rx[0] << 8) | rx[1]
        i_raw = (rx[2] << 8) | rx[3]
        return (
            v_raw * self._v_scale + self._v_offset,
            i_raw * self._i_scale + self._i_offset,
        )

    # ── SignalSource interface ────────────────────────────────────────────────

    def read(self) -> tuple[float, float]:
        """Return the (V, I) received in the last ``write()`` transaction."""
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        """Send *duty_cycle* to the Pico and capture the returned (V, I).

        The duty cycle is clamped to [0.0, 1.0].  The V/I values are
        available via the next ``read()`` call.
        """
        self._duty = max(0.0, min(1.0, duty_cycle))
        self._v, self._i = self._transact(self._duty)

    # ── extras ───────────────────────────────────────────────────────────────

    def soft_stop(self) -> None:
        """Drive duty cycle to zero (safe shutdown)."""
        self.write(0.0)

    @property
    def duty(self) -> float:
        """Last duty cycle sent to the Pico."""
        return self._duty

    # ── resource management ──────────────────────────────────────────────────

    def close(self) -> None:
        """Release the SPI device."""
        self._spi.close()

    def __enter__(self) -> SpiMcuSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.soft_stop()
        self.close()
