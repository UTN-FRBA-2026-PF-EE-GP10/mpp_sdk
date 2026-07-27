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
    next `xfer2()` call (and cleared); otherwise an all-zero 12-byte MISO
    frame is returned (its XOR checksum is trivially 0, so it validates)."""

    def __init__(self) -> None:
        self.max_speed_hz: int | None = None
        self.mode: int | None = None
        self.closed = False
        self.sent: list[list[int]] = []
        self.next_rx: list[int] | None = None
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

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    return SpiMcuSource


def _miso_frame(
    v_raw: int, i_raw: int, vout_raw: int, temp_raw: int, *, corrupt: bool = False
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
    checksum = 0
    for byte in data:
        checksum ^= byte
    if corrupt:
        checksum ^= 0x01
    return [*data, checksum, 0, 0, 0]


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

    def _raise(_duty):
        raise RuntimeError("simulated SPI fault")

    monkeypatch.setattr(src, "_transact", _raise)

    with pytest.raises(RuntimeError):
        src.__exit__(None, None, None)
    assert src._spi.closed
