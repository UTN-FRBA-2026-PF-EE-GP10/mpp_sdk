"""Tests for the dimmer helpers and the SpiMcuSource dimmer methods (fake spidev)."""

import math
import time

import pytest

from mpp_sdk.io.dimmer import (
    DimmerStatus,
    alpha_for_power,
    alpha_to_wire,
    lamp_power_fraction,
    parse_status_frame,
)
from mpp_sdk.io.spi_crc import crc8
from tests.test_spi_mcu import _miso_frame, spi_mcu_source  # noqa: F401


def _status_frame(flags=0x0F, set_cd=9000, applied=9100, age=3, magic=0xD2, corrupt=False):
    data = [magic, flags, set_cd >> 8, set_cd & 0xFF, applied >> 8, applied & 0xFF, age, 0]
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
