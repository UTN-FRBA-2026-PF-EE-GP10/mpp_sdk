"""Run a registered MPPT algorithm against real hardware and record a
closed-loop run: a time series of (V, I, D) captured while the algorithm
drove the live SEPIC via `SpiMcuSource`.

Needs `mpp-sdk[hardware]` (spidev). By default also sweeps and saves a
static I-V curve first (ground truth for `scripts/plot_run.py`) - skip
that with `--no-sweep --curve <path>` to reuse an existing capture.

`FirmwareMode::MppTracker` (the firmware's default mode) already applies
whatever duty the Pi last wrote, unconditionally - there is no on-target
safety cutoff for this continuous-drive use case (unlike the curve
tracer's own `breach()` check), so this script adds a client-side abort:
if a reading ever exceeds `--v-max`/`--i-max` (defaults matching the
board's documented 40V/1A limits), duty is driven to zero and the run is
marked aborted.

Usage::

    uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check
"""

from __future__ import annotations

import argparse
import time

from harness.common import algorithm_specs
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves.library import save as curves_save
from mpp_sdk.curves.record import now_utc as curves_now_utc
from mpp_sdk.runs import RunRecord, RunSample
from mpp_sdk.runs import save as runs_save
from mpp_sdk.runs.record import now_utc as runs_now_utc


def run_control_loop(
    source,
    algorithm,
    *,
    duration_s: float,
    v_max: float,
    i_max: float,
    initial_duty: float = 0.5,
    clock=time.monotonic,
    sleep=time.sleep,
    period_s: float = 0.0,
) -> tuple[list[RunSample], bool]:
    """Run `algorithm` against `source` for `duration_s` seconds,
    recording one `RunSample` per control step. Returns
    `(samples, aborted)` - `aborted` is True if `voltage > v_max` or
    `current > i_max` fired the safety cutoff (source is driven to 0
    duty before returning). `period_s > 0` adds a `sleep()` pad between
    steps; 0 (default) runs as fast as `source.read()/write()` allow."""
    source.write(initial_duty)  # seed - SpiMcuSource.read() raises before the first write()
    samples: list[RunSample] = []
    start = clock()
    aborted = False
    while clock() - start < duration_s:
        voltage, current = source.read()
        t = clock() - start
        if voltage > v_max or current > i_max:
            source.write(0.0)
            aborted = True
            break
        duty = algorithm.step(voltage, current)
        source.write(duty)
        samples.append(RunSample(t=t, voltage=voltage, current=current, duty=duty))
        if period_s > 0:
            sleep(period_s)
    return samples, aborted


def _sweep_and_save_curve(src, *, timeout_s: float, poll_interval_s: float, label: str) -> str:
    """Trigger one sweep, save it via mpp_sdk.curves, release the relay,
    and return the saved file's name (for RunRecord.curve_ref)."""
    from scripts.curve_tracer_bench_test import run_sweep_and_fetch

    points = run_sweep_and_fetch(src, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
    record = CurveRecord(
        captured_at=curves_now_utc(),
        label=label,
        measurement="baseline",
        panels=(),
        points=tuple(points),
    )
    path = curves_save(record)
    src.release_relay()
    return path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    specs = {s.label.lower(): s for s in algorithm_specs()}
    parser.add_argument(
        "--algorithm",
        required=True,
        help=f"one of: {', '.join(s.label for s in specs.values())} (case-insensitive)",
    )
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument("--label", required=True)
    parser.add_argument("--v-max", type=float, default=40.0)
    parser.add_argument("--i-max", type=float, default=1.0)
    parser.add_argument("--no-sweep", action="store_true", help="skip the curve sweep")
    parser.add_argument("--curve", default=None, help="existing curve filename (with --no-sweep)")
    parser.add_argument("--bus", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--speed-hz", type=int, default=200_000)
    args = parser.parse_args()

    spec = specs.get(args.algorithm.lower())
    if spec is None:
        parser.error(f"unknown --algorithm {args.algorithm!r}; choices: {', '.join(specs)}")

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    with SpiMcuSource(bus=args.bus, device=args.device, speed_hz=args.speed_hz) as src:
        curve_ref = args.curve
        if not args.no_sweep:
            print("Sweeping curve...")
            curve_ref = _sweep_and_save_curve(
                src, timeout_s=15.0, poll_interval_s=0.05, label=args.label
            )
            print(f"  saved curve: {curve_ref}")

        print(f"Running {spec.label} for {args.duration_s}s...")
        algorithm = spec.make(0.5)
        samples, aborted = run_control_loop(
            src,
            algorithm,
            duration_s=args.duration_s,
            v_max=args.v_max,
            i_max=args.i_max,
        )

    record = RunRecord(
        captured_at=runs_now_utc(),
        label=args.label,
        algorithm=spec.label,
        samples=tuple(samples),
        curve_ref=curve_ref,
        aborted=aborted,
    )
    path = runs_save(record)

    print(f"\n{'steps':<10}{'aborted':<10}{'final V':<10}{'final I':<10}{'final D':<10}")
    last = samples[-1] if samples else None
    print(
        f"{len(samples):<10}{aborted!s:<10}"
        f"{last.voltage if last else 0.0:<10.3f}"
        f"{last.current if last else 0.0:<10.3f}"
        f"{last.duty if last else 0.0:<10.3f}"
    )
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
