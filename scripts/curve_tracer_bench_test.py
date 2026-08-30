"""Bench test: trigger curve-tracer sweeps from the Pi, fetch each I-V
curve, plot them together, then release the tracer relay.

Exercises the SPI-trigger + explicit-release path end to end on real
hardware - `start_sweep()` (not the physical But1 button), poll for the
result, repeat, `release_relay()`. A first on-target check that the relay
really does stay engaged across multiple sweeps and only releases when
asked, and that both curves come back sane.

Usage::

    uv run python scripts/curve_tracer_bench_test.py
    # or: mpp-sdk curve-tracer-bench-test
    # writes curve_tracer_bench_test.png with both curves overlaid
"""

import argparse

from mpp_sdk.io.spi_mcu import SpiMcuSource


def run_sweep_and_fetch(
    src: SpiMcuSource, timeout_s: float, poll_interval_s: float
) -> list[tuple[float, float]]:
    """Trigger one sweep from the Pi and block until its result is ready.

    Must be a single `request_sweep()` call with `poll_attempts` sized to
    cover the whole wait - the bulk-read handshake advances a step on
    every frame the Pi sends it (see spi_slave_pio.rs's `BulkState`), so
    retrying with a small `poll_attempts` in an external loop desyncs it:
    an ack that only becomes visible on a call's *second* frame gets
    dropped if that call returns before checking it, and the next call's
    differently-shaped frame then doesn't match what the firmware is
    expecting next, discarding the result on the resulting timeout/reset.

    `poll_interval_s` must also stay under the firmware's 100 ms frame
    timeout, or the firmware times out between our polls and resets the
    handshake - see `request_sweep()`'s own docstring.
    """
    src.start_sweep()
    poll_attempts = max(1, round(timeout_s / poll_interval_s))
    result = src.request_sweep(poll_attempts=poll_attempts, poll_interval_s=poll_interval_s)
    if result is None:
        raise TimeoutError(f"sweep result not ready within {timeout_s}s")
    return result


def plot_curves(curves: list[list[tuple[float, float]]], out_path: str) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    for idx, curve in enumerate(curves, start=1):
        v = [p[0] for p in curve]
        i_ma = [p[1] * 1000.0 for p in curve]
        ax.plot(v, i_ma, marker="o", label=f"sweep {idx} ({len(curve)} pts)")
    ax.set_xlabel("V (V)")
    ax.set_ylabel("I (mA)")
    ax.set_title("Curve tracer - Pi-triggered sweeps")
    ax.legend()
    ax.grid(True)
    fig.savefig(out_path)
    print(f"Saved plot to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--spi-speed-hz", type=int, default=200_000)
    parser.add_argument("--sweeps", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=15.0)
    # Must stay under the firmware's 100 ms FRAME_TIMEOUT - see
    # run_sweep_and_fetch()/request_sweep().
    parser.add_argument("--poll-interval-s", type=float, default=0.05)
    parser.add_argument("--out", default="curve_tracer_bench_test.png")
    args = parser.parse_args()

    curves = []
    with SpiMcuSource(bus=args.spi_bus, device=args.spi_device, speed_hz=args.spi_speed_hz) as src:
        for n in range(1, args.sweeps + 1):
            print(f"Starting sweep {n}/{args.sweeps} from the Pi...")
            curve = run_sweep_and_fetch(src, args.timeout_s, args.poll_interval_s)
            print(f"  sweep {n}: {len(curve)} points")
            curves.append(curve)

        print("Releasing tracer relay...")
        src.release_relay()

    plot_curves(curves, args.out)


if __name__ == "__main__":
    main()
