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
if readings stay above `--v-max`/`--i-max` (defaults: the board limits
`BOARD_V_MAX`/`BOARD_I_MAX`), or the link looks down (a sustained
run of corrupt SPI frames - see `_BAD_FRAMES_LINK_DOWN` in `mpp_sdk/runs/loop.py`), duty is
driven to zero and the run is marked aborted. `run_control_loop` is also
what `scripts/curve_tracer_server.py` calls to drive a run started from
the web UI - one control loop, one abort path, shared by both.

Usage::

    uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check
"""

from __future__ import annotations

import argparse

from harness.common import algorithm_specs
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves.library import save as curves_save
from mpp_sdk.curves.record import now_utc as curves_now_utc
from mpp_sdk.io.board import default_spi_bus
from mpp_sdk.runs import RunRecord
from mpp_sdk.runs import save as runs_save

# The loop moved to mpp_sdk.runs.loop. These names stay importable from here
# for one release so existing `from scripts.run_algorithm import ...` lines
# keep working.
from mpp_sdk.runs.loop import (  # noqa: F401
    _BAD_FRAMES_LINK_DOWN,
    BOARD_I_MAX,
    BOARD_V_MAX,
    BOARD_V_OUT_MAX,
    MAX_CONTROL_PERIOD_MS,
    build_run_settings,
    run_control_loop,
)
from mpp_sdk.runs.record import now_utc as runs_now_utc


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
        # This script only ever runs against a real board (it needs
        # spidev), so the sweep it saves is always a measurement.
        source="hardware",
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
    parser.add_argument("--v-max", type=float, default=BOARD_V_MAX)
    parser.add_argument(
        "--i-max",
        type=float,
        default=BOARD_I_MAX,
        help="input current limit (below the INA229's 999 mA maximum reading)",
    )
    parser.add_argument(
        "--v-out-max",
        type=float,
        default=BOARD_V_OUT_MAX,
        help="converter output limit (below the ADC Low range, ~27 V)",
    )
    parser.add_argument(
        "--control-period-ms",
        type=float,
        default=None,
        help="minimum time between algorithm steps in ms (default: one step per exchange)",
    )
    parser.add_argument("--no-sweep", action="store_true", help="skip the curve sweep")
    parser.add_argument("--curve", default=None, help="existing curve filename (with --no-sweep)")
    parser.add_argument(
        "--bus", type=int, default=default_spi_bus(), help="SPI bus (default: 1 on a BBB, else 0)"
    )
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--speed-hz", type=int, default=200_000)
    parser.add_argument(
        "--settling-time-s",
        type=float,
        default=0.03,
        help="converter settling delay per step in seconds (default: 0.03s / 30ms)",
    )
    args = parser.parse_args()

    spec = specs.get(args.algorithm.lower())
    if spec is None:
        parser.error(f"unknown --algorithm {args.algorithm!r}; choices: {', '.join(specs)}")

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    with SpiMcuSource(
        bus=args.bus,
        device=args.device,
        speed_hz=args.speed_hz,
        settling_time_s=args.settling_time_s,
    ) as src:
        curve_ref = args.curve
        if not args.no_sweep:
            print("Sweeping curve...")
            curve_ref = _sweep_and_save_curve(
                src, timeout_s=15.0, poll_interval_s=0.05, label=args.label
            )
            print(f"  saved curve: {curve_ref}")

        print(f"Running {spec.label} for {args.duration_s}s...")
        algorithm = spec.make(0.5)
        run_info: dict = {}
        samples, aborted, reason = run_control_loop(
            src,
            algorithm,
            duration_s=args.duration_s,
            v_max=args.v_max,
            i_max=args.i_max,
            v_out_max=args.v_out_max,
            control_period_ms=args.control_period_ms,
            run_info=run_info,
        )
        settings = build_run_settings(src, algorithm, control_period_ms=args.control_period_ms)

    record = RunRecord(
        captured_at=runs_now_utc(),
        label=args.label,
        algorithm=spec.label,
        samples=tuple(samples),
        curve_ref=curve_ref,
        aborted=aborted,
        notes=reason or "",
        # This script only ever runs against a real board (it needs
        # spidev), so the run it saves always drove real hardware.
        source="hardware",
        settings=settings,
        step_period_mean_ms=run_info.get("step_period_mean_ms"),
        step_period_max_ms=run_info.get("step_period_max_ms"),
        bad_frames=run_info.get("bad_frames"),
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
    if reason:
        print(f"Abort reason: {reason}")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
