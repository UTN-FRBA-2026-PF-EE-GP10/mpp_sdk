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
SPEED_HZ = 8_000_000
V_SCALE = 3.3 / 4095.0
I_SCALE = 3.3 / 4095.0


def make_frame(duty: float) -> list[int]:
    d = max(0, min(65535, round(duty * 65535)))
    return [d >> 8, d & 0xFF] + [0] * 10


def parse_response(rx: list[int]) -> tuple[int, int]:
    return (rx[0] << 8) | rx[1], (rx[2] << 8) | rx[3]


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
    print(f"duty={args.duty:.2f}  tx={[f'{b:02X}' for b in tx[:2]]}")
    print(f"{'#':>5}  {'V_raw':>6}  {'I_raw':>6}  {'V (V)':>7}  {'I (A)':>7}  ok?")
    print("-" * 44)

    n = 0
    try:
        while True:
            rx = spi.xfer2(list(tx))
            v_raw, i_raw = parse_response(rx)
            ok = "✓" if (1500 < v_raw < 4096 and 300 < i_raw < 1000) else "✗"
            v_str = f"{v_raw * V_SCALE:>7.3f}"
            i_str = f"{i_raw * I_SCALE:>7.3f}"
            print(f"{n:>5}  {v_raw:>6}  {i_raw:>6}  {v_str}  {i_str}  {ok}")
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
