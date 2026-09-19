"""Step the SEPIC duty cycle with a bench supply on the input and a load
resistor on the output, and record V in, I in and V out at each step.

This is the bench duty sweep: it checks the converter's transfer ratio
against `V_out = V_in * D / (1 - D)`, measures efficiency, and - with
`--meter` - compares the on-chip `ADC_VOUT` reading against a multimeter
at every step, while the converter is switching.

Needs `mpp-sdk[hardware]` (spidev) and the firmware in `MppTracker` mode.
**Stop the curve-tracer server first**: only one program can own the SPI
link.

**Always with a load on the output.** With no load the SEPIC output climbs
far past the input (tens of volts at 10 % duty), past the ADC range and
toward C15's 100 V rating.

Usage::

    uv run python scripts/duty_sweep.py --load-ohms 10 --meter
    uv run python scripts/duty_sweep.py --duties 0,0.05,0.1 --load-ohms 100
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Hard cap: at 12 V in and 10 Ohm, D = 0.50 already means about 1.2 A out,
# past the board's 1 A rating.
MAX_DUTY = 0.45

# Below the firmware's 100 ms frame timeout: the PIO SPI slave cannot
# recover from an idle timeout, so the link must never pause longer.
POLL_PERIOD_S = 0.05

# Consecutive bad frames before the link counts as down: about 1 s at the
# poll period above.
BAD_FRAMES_LINK_DOWN = 20


@dataclass(frozen=True)
class Limits:
    i_in_max: float  # A
    v_in_max: float  # V
    v_out_max: float  # V


@dataclass(frozen=True)
class StepResult:
    duty: float
    v_in: float
    i_in: float
    v_out_adc: float | None
    v_out_meter: float | None
    n_samples: int


class SweepAborted(RuntimeError):
    """A limit tripped or the link went down; duty has been set to 0."""


class Poller:
    """Owns the source for the whole sweep. Exchanges a frame every
    `POLL_PERIOD_S` at the current target duty, keeps recent samples, and
    enforces the limits - so the link never pauses (not even while the
    operator types a meter reading), and a limit trips even between steps.
    Duty returns to 0 on every exit."""

    def __init__(self, source, limits: Limits, clock=time.monotonic, sleep=time.sleep):
        self._source = source
        self._limits = limits
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._duty = 0.0
        self._samples: deque[tuple[float, float, float, float | None]] = deque(maxlen=400)
        self._stop = threading.Event()
        self._abort_reason: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Poller:
        self._source.write(0.0)  # SpiMcuSource.read() needs one write first
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        # A thread still alive is stuck inside an SPI transfer: writing from
        # here too would put two transfers on one link at once. Leave it;
        # the firmware zeroes duty by itself after ~500 ms of silence.
        if self._thread.is_alive():
            return
        # Zeroing duty must not mask the error that ended the sweep.
        with contextlib.suppress(Exception):
            self._source.write(0.0)

    def set_duty(self, duty: float) -> None:
        with self._lock:
            self._duty = duty

    def abort_reason(self) -> str | None:
        with self._lock:
            return self._abort_reason

    def samples_since(self, t0: float) -> list[tuple[float, float, float | None]]:
        with self._lock:
            return [(v, i, vo) for t, v, i, vo in self._samples if t >= t0]

    def now(self) -> float:
        return self._clock()

    def _trip(self, reason: str) -> None:
        with self._lock:
            self._abort_reason = reason
            self._duty = 0.0
        self._source.write(0.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                duty = self._duty
                tripped = self._abort_reason is not None
            try:
                self._source.write(0.0 if tripped else duty)
                v, i = self._source.read()
                vout = getattr(self._source, "vout", None)
            except Exception as exc:  # noqa: BLE001 - any failure ends the sweep safely
                self._trip(f"error: {exc}")
                return
            with self._lock:
                self._samples.append((self._clock(), v, i, vout))
            if not tripped:
                if i > self._limits.i_in_max:
                    self._trip(f"I in {i:.3f} A above {self._limits.i_in_max} A")
                elif v > self._limits.v_in_max:
                    self._trip(f"V in {v:.2f} V above {self._limits.v_in_max} V")
                elif vout is not None and vout > self._limits.v_out_max:
                    self._trip(f"V out {vout:.2f} V above {self._limits.v_out_max} V")
                elif getattr(self._source, "consecutive_bad_frames", 0) >= BAD_FRAMES_LINK_DOWN:
                    self._trip("link down: no valid frames from the board")
            self._sleep(POLL_PERIOD_S)


def run_step(
    poller: Poller,
    duty: float,
    *,
    hold_s: float,
    avg_s: float,
    meter: Callable[[float], float | None] | None = None,
    wait: Callable[[float], None] = time.sleep,
) -> StepResult:
    """Hold `duty` for `hold_s`, average the last `avg_s` of samples, then
    ask `meter` (if given) for the multimeter's V out."""
    if not 0.0 <= duty <= MAX_DUTY:
        raise ValueError(f"duty {duty} outside 0..{MAX_DUTY}")
    # A window longer than the hold reaches back into the previous step's
    # duty and reports a mix of two operating points as one.
    if avg_s > hold_s:
        raise ValueError(f"avg_s {avg_s} longer than hold_s {hold_s}")
    poller.set_duty(duty)
    wait(hold_s)
    if (reason := poller.abort_reason()) is not None:
        raise SweepAborted(reason)
    window = poller.samples_since(poller.now() - avg_s)
    if not window:
        raise SweepAborted("no samples in the averaging window")
    v_in = sum(s[0] for s in window) / len(window)
    i_in = sum(s[1] for s in window) / len(window)
    vouts = [s[2] for s in window if s[2] is not None]
    v_out_adc = sum(vouts) / len(vouts) if vouts else None
    v_out_meter = meter(duty) if meter is not None else None
    if (reason := poller.abort_reason()) is not None:
        raise SweepAborted(reason)
    return StepResult(duty, v_in, i_in, v_out_adc, v_out_meter, len(window))


def _theory_v_out(v_in: float, duty: float) -> float:
    return v_in * duty / (1.0 - duty) if duty < 1.0 else float("inf")


def _prompt_meter(duty: float) -> float | None:
    raw = input(f"  D={duty:.2f}: meter V out in volts (Enter to skip): ").strip()
    return float(raw) if raw else None


def _format_row(r: StepResult, load_ohms: float | None) -> str:
    theory = _theory_v_out(r.v_in, r.duty)
    adc = f"{r.v_out_adc:8.3f}" if r.v_out_adc is not None else "       -"
    meter = f"{r.v_out_meter:8.3f}" if r.v_out_meter is not None else "       -"
    err = (
        f"{(r.v_out_adc - r.v_out_meter) * 1000:+7.0f}"
        if r.v_out_adc is not None and r.v_out_meter is not None
        else "      -"
    )
    v_out = r.v_out_meter if r.v_out_meter is not None else r.v_out_adc
    p_in = r.v_in * r.i_in
    eta = (
        f"{(v_out**2 / load_ohms) / p_in * 100:5.1f}"
        if load_ohms and v_out is not None and p_in > 0.05
        else "    -"
    )
    return (
        f"{r.duty:5.2f} {r.v_in:7.3f} {r.i_in:7.3f} {p_in:7.3f} "
        f"{theory:8.3f} {adc} {meter} {err} {eta}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--duties",
        default="0,0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.45",
        help=f"comma-separated duty steps, each 0..{MAX_DUTY}",
    )
    parser.add_argument("--load-ohms", type=float, required=True, help="output load resistor")
    parser.add_argument("--hold-s", type=float, default=4.0)
    parser.add_argument("--avg-s", type=float, default=2.0)
    parser.add_argument("--meter", action="store_true", help="prompt for the meter's V out")
    parser.add_argument("--i-in-max", type=float, default=1.0)
    parser.add_argument("--v-in-max", type=float, default=30.0)
    parser.add_argument(
        "--v-out-max", type=float, default=25.0, help="below the ADC Low range (~27 V)"
    )
    parser.add_argument("--out", type=Path, default=None, help="CSV path")
    parser.add_argument("--bus", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--speed-hz", type=int, default=200_000)
    args = parser.parse_args()

    if args.avg_s > args.hold_s:
        parser.error("--avg-s must not be longer than --hold-s")
    duties = [float(d) for d in args.duties.split(",")]
    for d in duties:
        if not 0.0 <= d <= MAX_DUTY:
            parser.error(f"duty {d} outside 0..{MAX_DUTY}")
    out = args.out or Path(
        f"data/bench/duty_sweep_{args.load_ohms:g}R_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"
    )
    limits = Limits(args.i_in_max, args.v_in_max, args.v_out_max)

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    header = (
        f"{'D':>5} {'Vin':>7} {'Iin':>7} {'Pin':>7} {'Vth':>8} {'Vo ADC':>8} "
        f"{'Vo mtr':>8} {'ADC-mtr mV':>7} {'eta%':>5}"
    )
    results: list[StepResult] = []
    with (
        SpiMcuSource(bus=args.bus, device=args.device, speed_hz=args.speed_hz) as src,
        Poller(src, limits) as poller,
    ):
        print(header)
        try:
            for d in duties:
                r = run_step(
                    poller,
                    d,
                    hold_s=args.hold_s,
                    avg_s=args.avg_s,
                    meter=_prompt_meter if args.meter else None,
                )
                results.append(r)
                print(_format_row(r, args.load_ohms))
        except SweepAborted as exc:
            print(f"ABORTED: {exc} - duty set to 0")
        except KeyboardInterrupt:
            print("Stopped by operator - duty set to 0")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["duty", "v_in", "i_in", "v_out_adc", "v_out_meter", "n", "load_ohms"])
        for r in results:
            w.writerow(
                [r.duty, r.v_in, r.i_in, r.v_out_adc, r.v_out_meter, r.n_samples, args.load_ohms]
            )
    print(f"Saved {len(results)} steps: {out}")


if __name__ == "__main__":
    main()
