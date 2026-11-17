"""CRC-8 of the SPI frames, kept free of spidev so any module can use it."""

from collections.abc import Sequence


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
