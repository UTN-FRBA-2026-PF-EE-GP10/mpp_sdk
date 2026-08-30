"""Send a duty cycle to the Pico SPI slave and print V/I back.

Usage:
    uv run python3 scripts/spi_test.py            # loop at 50 % duty
    uv run python3 scripts/spi_test.py --duty 0.3 # set duty (0.0-1.0)
    uv run python3 scripts/spi_test.py --once     # single frame then exit
"""

import argparse
import time

import spidev

BUS, DEVICE = 0, 0
# 8 MHz is unreliable on the breadboard HIL wiring (GPIO input synchronizer
# latency eats too much of the 125 ns bit period, on top of jumper-wire
# signal integrity) - 1 MHz was the validated speed during plan 004
# bring-up. After wiring in the GPIO4 NeoPixel strip (plan 013), 1 MHz
# started producing corrupted-but-complete MISO frames (e.g. I_raw reading
# exactly 0x8000 - one bit, not random noise), most likely electrical
# crosstalk from the NeoPixels' fast switching onto nearby breadboard
# wiring. 200 kHz is bench-confirmed clean with the NeoPixels active.
SPEED_HZ = 200_000
# Firmware reports V/I/Vout in millivolts/milliamperes as raw u16
# (firmware/pipico_board/README.md "Sensing"), not raw ADC counts.
V_SCALE = 1e-3
I_SCALE = 1e-3
# Sentinel for "no temperature probe" (MAX31865 disabled on the firmware
# side) - matches firmware's `TEMP_NOT_AVAILABLE_CC = i16::MIN` exactly.
TEMP_NOT_AVAILABLE_CC = -32768


def make_frame(duty: float) -> list[int]:
    d = max(0, min(65535, round(duty * 65535)))
    checksum = (d >> 8) ^ (d & 0xFF)
    return [d >> 8, d & 0xFF, checksum] + [0] * 9


def parse_response(rx: list[int]) -> tuple[int, int, int, int, bool]:
    """Return (v_raw, i_raw, vout_raw, temp_raw_signed, checksum_ok)."""
    # Covers the 8 telemetry bytes plus the curve-tracer ack byte (rx[9]),
    # matching firmware's build_tx_frame and SpiMcuSource._transact.
    expected_checksum = rx[9]
    for byte in rx[0:8]:
        expected_checksum ^= byte
    checksum_ok = rx[8] == expected_checksum

    v_raw = (rx[0] << 8) | rx[1]
    i_raw = (rx[2] << 8) | rx[3]
    vout_raw = (rx[4] << 8) | rx[5]
    temp_raw = (rx[6] << 8) | rx[7]
    temp_raw_signed = temp_raw - 65536 if temp_raw >= 32768 else temp_raw
    return v_raw, i_raw, vout_raw, temp_raw_signed, checksum_ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duty", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    spi = spidev.SpiDev()
    spi.open(BUS, DEVICE)
    spi.max_speed_hz = SPEED_HZ
    spi.mode = 0

    tx = make_frame(args.duty)
    print(f"duty={args.duty:.2f}  tx={[f'{b:02X}' for b in tx[:3]]}")
    print(
        f"{'#':>5}  {'V_raw':>6}  {'I_raw':>6}  {'Vout_raw':>8}  {'Temp_C':>7}  "
        f"{'V (V)':>7}  {'I (A)':>7}  {'Vout (V)':>8}  ok?  crc?"
    )
    print("-" * 78)

    n = 0
    try:
        while True:
            rx = spi.xfer2(list(tx))
            v_raw, i_raw, vout_raw, temp_raw, checksum_ok = parse_response(rx)
            # Board is designed for <= 40 V / <= 1 A on the panel input
            # (docs/general_information.md); flag readings outside that.
            ok = "✓" if (0 <= v_raw <= 40_000 and 0 <= i_raw <= 1_000) else "✗"
            crc = "✓" if checksum_ok else "✗"
            v_str = f"{v_raw * V_SCALE:>7.3f}"
            i_str = f"{i_raw * I_SCALE:>7.3f}"
            vout_str = f"{vout_raw * V_SCALE:>8.3f}"
            temp_str = "  n/a  " if temp_raw == TEMP_NOT_AVAILABLE_CC else f"{temp_raw / 100:>7.2f}"
            print(
                f"{n:>5}  {v_raw:>6}  {i_raw:>6}  {vout_raw:>8}  {temp_str:>7}  "
                f"{v_str}  {i_str}  {vout_str}  {ok}    {crc}"
            )
            n += 1
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        spi.close()


if __name__ == "__main__":
    main()
