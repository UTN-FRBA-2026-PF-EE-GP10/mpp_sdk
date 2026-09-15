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
board's documented 40V/1A limits), or the link looks down (a sustained
run of corrupt SPI frames - see `_BAD_FRAMES_LINK_DOWN` below), duty is
driven to zero and the run is marked aborted. `run_control_loop` is also
what `scripts/curve_tracer_server.py` calls to drive a run started from
the web UI - one control loop, one abort path, shared by both.

Usage::

    uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check
"""

from __future__ import annotations

import argparse
import contextlib
import time
from collections.abc import Callable

from harness.common import algorithm_specs
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves.library import save as curves_save
from mpp_sdk.curves.record import now_utc as curves_now_utc
from mpp_sdk.runs import RunRecord, RunSample
from mpp_sdk.runs import save as runs_save
from mpp_sdk.runs.record import now_utc as runs_now_utc

# Consecutive bad SPI frames before a run treats the link as down (see
# SpiMcuSource.consecutive_bad_frames). Conceptually the same idea as
# curve_tracer_server.py's own _BAD_FRAMES_LINK_DOWN (8, at that loop's
# ~50 ms poll period - about 400 ms to notice a pulled cable), but this
# loop has no sleep between exchanges by default (period_s=0) and each
# exchange is on the order of 1-2 ms, so the count is scaled up to reach
# a similar wall-clock detection time rather than tripping on one burst
# of ordinary line noise.
_BAD_FRAMES_LINK_DOWN = 300


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
    should_stop: Callable[[], bool] | None = None,
    max_consecutive_bad_frames: int = _BAD_FRAMES_LINK_DOWN,
    on_sample: Callable[[RunSample], None] | None = None,
) -> tuple[list[RunSample], bool, str | None]:
    """Run `algorithm` against `source` for `duration_s` seconds,
    recording one `RunSample` per control step. Returns
    `(samples, aborted, reason)`.

    `aborted` is True, and `reason` names why, if any of these fire
    (source is driven to 0 duty before returning either way):

    - `"overvoltage"` / `"overcurrent"`: a reading exceeded `v_max`/`i_max`.
    - `"link-down"`: `source.consecutive_bad_frames` (absent on a fake or
      simulated source, which reads as 0 and never trips this) reached
      `max_consecutive_bad_frames` - SPI has no presence detection, so a
      disconnected board otherwise looks like valid-but-stale telemetry.
    - `"stopped"`: `should_stop()` returned True - an explicit request to
      end the run early (e.g. a UI Stop button), checked once per step.

    `reason` is `None` on an ordinary `duration_s` timeout - that is not
    an abort.

    Every exit path - normal completion, an abort above, or an exception
    raised by `source`/`algorithm` - drives duty to zero before returning
    or propagating. This is the function's one safety-critical guarantee;
    do not reimplement this loop elsewhere; extend it here instead so the
    CLI and any other caller keep exactly one abort path.

    `period_s > 0` adds a `sleep()` pad between steps; 0 (default) runs as
    fast as `source.read()/write()` allow. `on_sample`, if given, is
    called with each `RunSample` as it's recorded - for a caller (e.g. a
    web server) that wants to observe the run live without waiting for it
    to finish.
    """
    source.write(initial_duty)  # seed - SpiMcuSource.read() raises before the first write()
    samples: list[RunSample] = []
    start = clock()
    aborted = False
    reason: str | None = None
    try:
        while clock() - start < duration_s:
            voltage, current = source.read()
            t = clock() - start
            if voltage > v_max or current > i_max:
                aborted = True
                reason = "overvoltage" if voltage > v_max else "overcurrent"
                break
            if getattr(source, "consecutive_bad_frames", 0) >= max_consecutive_bad_frames:
                aborted = True
                reason = "link-down"
                break
            if should_stop is not None and should_stop():
                aborted = True
                reason = "stopped"
                break
            duty = algorithm.step(voltage, current)
            source.write(duty)
            sample = RunSample(t=t, voltage=voltage, current=current, duty=duty)
            samples.append(sample)
            if on_sample is not None:
                on_sample(sample)
            if period_s > 0:
                sleep(period_s)
    finally:
        # Zeroing duty is the priority on the way out; a broken write here
        # must not mask whatever exception is already propagating (or
        # silently replace a clean return with a spurious one).
        with contextlib.suppress(Exception):
            source.write(0.0)
    return samples, aborted, reason


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
        samples, aborted, reason = run_control_loop(
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
        notes=reason or "",
        # This script only ever runs against a real board (it needs
        # spidev), so the run it saves always drove real hardware.
        source="hardware",
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
