"""Set the lamp dimmer through the Pico SPI link.

Usage:
    uv run python3 scripts/dimmer_set.py --alpha 90          # firing angle in degrees
    uv run python3 scripts/dimmer_set.py --power 0.5         # fraction of full lamp power
    uv run python3 scripts/dimmer_set.py --off
    uv run python3 scripts/dimmer_set.py --status
    uv run python3 scripts/dimmer_set.py --alpha 90 --hold   # keep it on until Ctrl-C, then off

Without --hold the Pico switches the lamp off 3 s after the last command.
"""

import argparse
import sys
import time

from mpp_sdk.io.board import default_spi_bus


def _print_status(source) -> None:
    status = source.dimmer_status()
    if status is None:
        print("no valid status reply")
        return
    applied = (
        "does not fire"
        if status.applied_alpha_deg is None
        else f"{status.applied_alpha_deg:.2f} deg"
    )
    print(
        f"link_ok={status.link_ok} mains={status.mains} locked={status.locked} "
        f"timed_out={status.timed_out} set={status.set_alpha_deg:.2f} deg "
        f"applied={applied} age={status.age_s:.1f} s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--alpha", type=float, help="firing angle in degrees (0 full on, 180 off)")
    group.add_argument("--power", type=float, help="lamp power fraction 0-1")
    group.add_argument("--off", action="store_true")
    group.add_argument("--status", action="store_true")
    parser.add_argument(
        "--hold", action="store_true", help="keep the keepalive running until Ctrl-C"
    )
    parser.add_argument("--bus", type=int, default=default_spi_bus())
    parser.add_argument("--device", type=int, default=0)
    args = parser.parse_args()

    try:
        from mpp_sdk.io.spi_mcu import SpiMcuSource
    except ModuleNotFoundError as exc:
        sys.exit(f"{exc}\nThis script needs the spidev module on the Pi: uv sync --extra hardware")

    source = SpiMcuSource(bus=args.bus, device=args.device)
    try:
        if args.alpha is not None:
            source.set_dimmer_alpha(args.alpha)
        elif args.power is not None:
            source.set_dimmer_power(args.power)
        elif args.off:
            source.dimmer_off()
        _print_status(source)
        if args.hold and (args.alpha is not None or args.power is not None):
            print("holding, Ctrl-C to switch off")
            while True:
                time.sleep(1.0)
                _print_status(source)
    except KeyboardInterrupt:
        print("\nswitching off")
    finally:
        # close() sends the off command first.
        source.close()


if __name__ == "__main__":
    main()
