"""Capture SEPIC converter step response, settling time, and steady-state ripple.

Connects to the RP2040 Pico over SPI (HIL mode) or runs in simulation mode,
applies a sequence of duty cycle step transitions, and captures high-frequency
telemetry to calculate:
  - Steady-state output voltage mean (over the final 20% of the capture window)
  - Output voltage peak-to-peak ripple (mVpp)
  - Settling time (ts) within a configurable tolerance band (default ±2%)

Usage::

    # Real hardware on bench with 10 Ohm load:
    uv run python scripts/sepic_step_response.py --steps 0.1,0.3,0.2 --window-ms 500 --plot

    # Simulation mode (no hardware required):
    uv run python scripts/sepic_step_response.py --sim --steps 0.1,0.3,0.2 --window-ms 500 --plot
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import math
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Auto-detect default SPI bus: BeagleBone Black uses SPI1 (bus=1), RPi uses SPI0 (bus=0).
DEFAULT_BUS = 1 if not Path("/dev/spidev0.0").exists() and Path("/dev/spidev1.0").exists() else 0
DEFAULT_DEVICE = 0

# Maximum duty cycle cap allowed by the test script (allows up to 70% duty).
MAX_DUTY = 0.80

# Consecutive bad frames before the link counts as down:
# at a 3 ms poll period, 50 bad frames is ~150 ms of silence.
BAD_FRAMES_LINK_DOWN = 50


@dataclass(frozen=True)
class Limits:
    i_in_max: float = 10.0  # A
    v_in_max: float = 26.0  # V (Low divider range full scale is ~27.3 V)
    v_out_max: float = 26.0  # V (Low divider range full scale is ~27.3 V)


@dataclass(frozen=True)
class Sample:
    timestamp: float
    duty: float
    v_in: float
    i_in: float
    v_out: float


@dataclass(frozen=True)
class StepMetrics:
    step_idx: int
    duty_initial: float
    duty_target: float
    v_in_mean: float
    v_out_initial: float
    v_out_final: float
    ripple_pp_mv: float
    settling_time_ms: float | None
    tolerance_pct: float
    n_samples: int
    samples: list[Sample]


class StepAborted(RuntimeError):
    """A limit tripped or the link went down; duty has been zeroed."""


class Poller:
    """High-frequency background poller for SEPIC step response.

    Exchanges SPI frames at `poll_period_s` (e.g. 2 - 5 ms) while enforcing
    safety limits and recording telemetry samples. Duty returns to 0 on exit.
    """

    def __init__(
        self,
        source: Any,
        limits: Limits,
        poll_period_s: float = 0.003,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._source = source
        self._limits = limits
        self._poll_period_s = poll_period_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._duty = 0.0
        self._samples: list[Sample] = []
        self._stop = threading.Event()
        self._abort_reason: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Poller:
        self._source.write(0.0)  # Establish first frame
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            return
        with contextlib.suppress(Exception):
            self._source.write(0.0)

    def set_duty(self, duty: float) -> None:
        with self._lock:
            self._duty = duty

    def abort_reason(self) -> str | None:
        with self._lock:
            return self._abort_reason

    def now(self) -> float:
        return self._clock()

    def get_samples_between(self, t_start: float, t_end: float) -> list[Sample]:
        with self._lock:
            return [s for s in self._samples if t_start <= s.timestamp <= t_end]

    def all_samples(self) -> list[Sample]:
        with self._lock:
            return list(self._samples)

    def _trip(self, reason: str) -> None:
        with self._lock:
            self._abort_reason = reason
            self._duty = 0.0
        with contextlib.suppress(Exception):
            self._source.write(0.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                duty = self._duty
                tripped = self._abort_reason is not None

            try:
                self._source.write(0.0 if tripped else duty)
                v, i = self._source.read()
                vout = getattr(self._source, "vout", 0.0)
            except Exception as exc:  # noqa: BLE001
                self._trip(f"error: {exc}")
                return

            t_now = self._clock()
            with self._lock:
                self._samples.append(Sample(t_now, duty, v, i, vout))

            if not tripped:
                if i > self._limits.i_in_max:
                    self._trip(f"I in {i:.3f} A above {self._limits.i_in_max} A")
                elif v > self._limits.v_in_max:
                    self._trip(f"V in {v:.2f} V above {self._limits.v_in_max} V")
                elif vout > self._limits.v_out_max:
                    self._trip(f"V out {vout:.2f} V above {self._limits.v_out_max} V")
                elif getattr(self._source, "consecutive_bad_frames", 0) >= BAD_FRAMES_LINK_DOWN:
                    self._trip("link down: no valid frames from the board")

            self._sleep(self._poll_period_s)


class SimulatedSepicStepSource:
    """Software simulated SEPIC source with dynamic second-order response and ripple."""

    def __init__(
        self,
        v_in: float = 12.0,
        load_ohms: float = 10.0,
        efficiency: float = 0.90,
        f_n: float = 35.0,  # ~30 ms settling time
        zeta: float = 0.65,
        ripple_mv: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.v_in = v_in
        self.load_ohms = load_ohms
        self.efficiency = efficiency
        self.omega_n = 2.0 * math.pi * f_n
        self.zeta = zeta
        self.ripple_mv = ripple_mv
        self._clock = clock

        self.duty = 0.0
        self.vout = 0.0
        self._vout_state = 0.0
        self._vout_dot = 0.0
        self._last_t = clock()
        self.consecutive_bad_frames = 0

    def write(self, duty: float) -> None:
        self.duty = max(0.0, min(1.0, duty))
        self._update_dynamics()

    def read(self) -> tuple[float, float]:
        self._update_dynamics()
        p_out = (self.vout**2) / self.load_ohms
        p_in = p_out / self.efficiency if p_out > 0.001 else 0.0
        i_in = p_in / self.v_in if self.v_in > 0 else 0.0
        return self.v_in, i_in

    def _update_dynamics(self) -> None:
        now = self._clock()
        dt = max(1e-5, min(0.05, now - self._last_t))
        self._last_t = now

        # Ideal steady state target
        d = min(self.duty, 0.95)
        target_vout = self.v_in * d / (1.0 - d) if d < 1.0 else 0.0

        # Numerical integration of 2nd order ODE: y'' + 2*zeta*wn*y' + wn^2*y = wn^2*target
        # Using a sub-stepped Euler integration for stability
        sub_steps = 10
        sub_dt = dt / sub_steps
        for _ in range(sub_steps):
            accel = (self.omega_n**2) * (target_vout - self._vout_state) - (
                2.0 * self.zeta * self.omega_n * self._vout_dot
            )
            self._vout_dot += accel * sub_dt
            self._vout_state += self._vout_dot * sub_dt

        ripple = (self.ripple_mv / 2000.0) * math.sin(2.0 * math.pi * 1000.0 * now)
        self.vout = max(0.0, self._vout_state + ripple)


def calculate_step_metrics(
    samples: list[Sample],
    t_step: float,
    settle_s: float = 1.0,
    ripple_s: float = 1.0,
    duty_initial: float = 0.40,
    duty_target: float = 0.45,
    step_idx: int = 1,
    tolerance_pct: float = 2.0,
    v_out_initial: float | None = None,
    window_s: float | None = None,
) -> StepMetrics:
    """Compute steady-state mean, peak-to-peak ripple, and settling time.

    Separates the capture into:
      1. Settling phase (t_step -> t_step + settle_s): records step transient and ts.
      2. Ripple phase (t_step + settle_s -> t_step + settle_s + ripple_s): 1s steady-state ripple window.
    """
    if window_s is not None:
        settle_s = window_s * 0.8 if (settle_s == 1.0 and ripple_s == 1.0) else settle_s
        ripple_s = window_s - settle_s
    else:
        window_s = settle_s + ripple_s

    post_samples = [s for s in samples if s.timestamp >= t_step]
    if not post_samples:
        raise ValueError("No post-step samples available for metric calculation")

    # Initial Vout before step
    if v_out_initial is None:
        pre_samples = [s for s in samples if s.timestamp < t_step]
        v_out_initial = (
            sum(s.v_out for s in pre_samples) / len(pre_samples)
            if pre_samples
            else post_samples[0].v_out
        )

    # Dedicated ripple phase: samples from t_step + settle_s to t_step + settle_s + ripple_s
    t_ripple_start = t_step + settle_s
    ripple_samples = [s for s in post_samples if s.timestamp >= t_ripple_start]
    if not ripple_samples:
        # Fallback if window ended early
        ripple_samples = post_samples[-max(1, len(post_samples) // 5) :]

    v_out_final = sum(s.v_out for s in ripple_samples) / len(ripple_samples)
    v_in_mean = sum(s.v_in for s in ripple_samples) / len(ripple_samples)

    # Peak-to-peak ripple over the dedicated 1-second ripple window
    final_vouts = [s.v_out for s in ripple_samples]
    ripple_pp_mv = (max(final_vouts) - min(final_vouts)) * 1000.0

    # Settling time (ts):
    # Error band ±tolerance_pct around v_out_final (with floor 0.05 V for low voltages)
    tol_abs = max(abs(v_out_final) * (tolerance_pct / 100.0), 0.05)
    lower_bound = v_out_final - tol_abs
    upper_bound = v_out_final + tol_abs

    # Check samples within the settling window (up to end of settle_s)
    settle_samples = [s for s in post_samples if s.timestamp <= t_step + settle_s + 0.05]
    if not settle_samples:
        settle_samples = post_samples

    # Apply 5-point median filter to reject isolated single-sample ADC spikes
    raw_vouts = [s.v_out for s in settle_samples]
    k = min(5, len(raw_vouts))
    pad = k // 2
    filt_vouts: list[float] = []
    for i in range(len(raw_vouts)):
        window = raw_vouts[max(0, i - pad) : min(len(raw_vouts), i + pad + 1)]
        filt_vouts.append(sorted(window)[len(window) // 2])

    first_outside_idx: int | None = None
    for idx in range(len(filt_vouts) - 1, -1, -1):
        v = filt_vouts[idx]
        if v < lower_bound or v > upper_bound:
            first_outside_idx = idx
            break

    if first_outside_idx is None:
        # Never left the band
        settling_time_ms = 0.0
    elif first_outside_idx == len(settle_samples) - 1:
        # Last sample in settling window was still outside tolerance band
        settling_time_ms = None
    else:
        # Sample immediately following the last outside sample entered and stayed in band
        settled_sample = settle_samples[first_outside_idx + 1]
        settling_time_ms = max(0.0, (settled_sample.timestamp - t_step) * 1000.0)

    return StepMetrics(
        step_idx=step_idx,
        duty_initial=duty_initial,
        duty_target=duty_target,
        v_in_mean=v_in_mean,
        v_out_initial=v_out_initial,
        v_out_final=v_out_final,
        ripple_pp_mv=ripple_pp_mv,
        settling_time_ms=settling_time_ms,
        tolerance_pct=tolerance_pct,
        n_samples=len(post_samples),
        samples=samples,
    )


def run_step_response_test(
    poller: Poller,
    steps: list[float],
    *,
    hold_s: float = 1.0,
    settle_s: float = 1.0,
    ripple_s: float = 1.0,
    window_s: float | None = None,
    tolerance_pct: float = 2.0,
    wait: Callable[[float], None] = time.sleep,
) -> list[StepMetrics]:
    """Execute duty cycle step sequence, waiting settle_s (1s) for settling and ripple_s (1s) for ripple."""
    if len(steps) < 2:
        raise ValueError("At least 2 duty steps required to form a step transition")

    if window_s is not None:
        settle_s = window_s * 0.5
        ripple_s = window_s * 0.5

    results: list[StepMetrics] = []

    # 1. Pre-step steady state at the first duty
    poller.set_duty(steps[0])
    wait(hold_s)
    if (reason := poller.abort_reason()) is not None:
        raise StepAborted(reason)

    # 2. Iterate through transitions
    for idx in range(1, len(steps)):
        d_from = steps[idx - 1]
        d_to = steps[idx]

        # Read pre-step steady state voltage over the last 150 ms of hold
        t_now = poller.now()
        pre_samples = poller.get_samples_between(t_now - 0.15, t_now)
        v_out_init = (
            sum(s.v_out for s in pre_samples) / len(pre_samples)
            if pre_samples
            else (results[-1].v_out_final if results else 0.0)
        )

        # Apply the step
        t_step = poller.now()
        poller.set_duty(d_to)

        # Wait settle_s (e.g. 1 sec) to capture settling transient
        wait(settle_s)
        if (reason := poller.abort_reason()) is not None:
            raise StepAborted(reason)

        # Wait ripple_s (e.g. 1 more sec) to capture steady-state ripple
        wait(ripple_s)
        if (reason := poller.abort_reason()) is not None:
            raise StepAborted(reason)

        t_end = poller.now()
        # Include 100 ms pre-step for visualization
        step_samples = poller.get_samples_between(t_step - 0.1, t_end)

        metrics = calculate_step_metrics(
            step_samples,
            t_step=t_step,
            settle_s=settle_s,
            ripple_s=ripple_s,
            duty_initial=d_from,
            duty_target=d_to,
            step_idx=idx,
            tolerance_pct=tolerance_pct,
            v_out_initial=v_out_init,
        )
        results.append(metrics)

    # 3. Safe shutdown: return duty to 0
    poller.set_duty(0.0)
    wait(0.1)

    return results


def print_report(results: list[StepMetrics], tolerance_pct: float) -> None:
    """Print console summary table."""
    print()
    print("=" * 86)
    print(f"SEPIC Step Response & Stability Report (Tolerance: ±{tolerance_pct:g}%)")
    print("=" * 86)
    print(
        f"{'Step':>4}  {'Duty Transition':^15}  {'Vin Mean':>9}  "
        f"{'Vout: Pre -> Post':^19}  {'Ripple pk-pk':>14}  {'Settling Ts':>13}"
    )
    print("-" * 86)
    for r in results:
        ts_str = f"{r.settling_time_ms:6.1f} ms" if r.settling_time_ms is not None else "> window (unsettled)"
        vout_str = f"{r.v_out_initial:5.2f} V -> {r.v_out_final:5.2f} V"
        duty_str = f"{r.duty_initial:4.2f} -> {r.duty_target:4.2f}"
        print(
            f"{r.step_idx:4d}  {duty_str:^15}  {r.v_in_mean:7.2f} V  "
            f"{vout_str:^19}  {r.ripple_pp_mv:10.1f} mVpp  {ts_str:>13}"
        )
    print("=" * 86)
    print()
    for r in results:
        ts_str = f"{r.settling_time_ms:.1f} ms" if r.settling_time_ms is not None else "N/A"
        print(
            f"Step {r.duty_initial:.2f} -> {r.duty_target:.2f} | "
            f"Vout: {r.v_out_initial:.2f}V -> {r.v_out_final:.2f}V | "
            f"Ripple: {r.ripple_pp_mv:.0f} mVpp | Settling Time: {ts_str}"
        )
    print()


def export_csv(results: list[StepMetrics], out_path: Path, load_ohms: float | None = None) -> None:
    """Export raw time-series telemetry samples to CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "step_idx",
                "duty_from",
                "duty_to",
                "t_rel_ms",
                "timestamp",
                "duty",
                "v_in",
                "i_in",
                "v_out",
                "load_ohms",
            ]
        )
        for r in results:
            t0 = r.samples[0].timestamp if r.samples else 0.0
            for s in r.samples:
                t_rel_ms = (s.timestamp - t0) * 1000.0
                writer.writerow(
                    [
                        r.step_idx,
                        r.duty_initial,
                        r.duty_target,
                        f"{t_rel_ms:.2f}",
                        f"{s.timestamp:.6f}",
                        f"{s.duty:.4f}",
                        f"{s.v_in:.4f}",
                        f"{s.i_in:.4f}",
                        f"{s.v_out:.4f}",
                        load_ohms if load_ohms is not None else "",
                    ]
                )


def plot_step_responses(
    results: list[StepMetrics],
    out_path: Path | None = None,
    show: bool = True,
) -> None:
    """Generate matplotlib figures annotating settling time and ripple."""
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print("Note: matplotlib is not installed. Skipping plot generation.")
        return

    n_steps = len(results)
    fig, axes = plt.subplots(n_steps, 1, figsize=(10, 3.5 * n_steps), sharex=False, squeeze=False)

    for idx, r in enumerate(results):
        ax = axes[idx, 0]
        t_step = min((s.timestamp for s in r.samples if s.duty == r.duty_target), default=r.samples[0].timestamp)
        t_rel_ms = [(s.timestamp - t_step) * 1000.0 for s in r.samples]
        v_out_vals = [s.v_out for s in r.samples]

        # Vout curve
        ax.plot(t_rel_ms, v_out_vals, color="#1f77b4", linewidth=1.5, label="Vout (measured)")

        # Step line at t=0
        ax.axvline(0.0, color="#d62728", linestyle="--", alpha=0.8, label="Step Applied")

        # Target steady state & tolerance band
        tol_abs = max(abs(r.v_out_final) * (r.tolerance_pct / 100.0), 0.05)
        ax.axhline(r.v_out_final, color="#2ca02c", linestyle=":", label=f"Vss = {r.v_out_final:.2f} V")
        ax.axhspan(
            r.v_out_final - tol_abs,
            r.v_out_final + tol_abs,
            color="#2ca02c",
            alpha=0.15,
            label=f"±{r.tolerance_pct:g}% Band",
        )

        # Settling point annotation
        if r.settling_time_ms is not None:
            ax.axvline(r.settling_time_ms, color="#2ca02c", linestyle="--", alpha=0.9, label=f"ts = {r.settling_time_ms:.1f} ms")
            ax.plot([r.settling_time_ms], [r.v_out_final], marker="o", color="#2ca02c")
            ax.annotate(
                f"ts={r.settling_time_ms:.1f} ms\nRipple={r.ripple_pp_mv:.0f} mVpp",
                xy=(r.settling_time_ms, r.v_out_final),
                xytext=(r.settling_time_ms + 15, r.v_out_final + tol_abs * 1.5),
                arrowprops={"arrowstyle": "->", "color": "#2ca02c"},
                fontsize=9,
                bbox={"boxstyle": "round,pad=0.3", "fc": "yellow", "alpha": 0.3},
            )

        ax.set_title(
            f"Step {r.step_idx}: D = {r.duty_initial:.2f} -> {r.duty_target:.2f} (Vin ~ {r.v_in_mean:.1f} V)",
            fontsize=11,
            fontweight="bold",
        )
        ax.set_xlabel("Time from step (ms)")
        ax.set_ylabel("Output Voltage (V)")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, dpi=150)
        print(f"Saved plot to: {out_path}")

    if show and "pytest" not in sys.modules:
        with contextlib.suppress(Exception):
            plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SEPIC Step Response & Stability Verification",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--steps",
        default="0.40,0.45,0.50,0.55,0.60,0.65,0.70",
        help=f"comma-separated duty steps (0..{MAX_DUTY})",
    )
    parser.add_argument("--settle-s", type=float, default=1.0, help="duration to observe settling response (s)")
    parser.add_argument("--ripple-s", type=float, default=1.0, help="duration to observe steady-state ripple (s)")
    parser.add_argument("--hold-s", type=float, default=1.0, help="pre-step hold duration (s)")
    parser.add_argument("--window-ms", type=float, default=None, help="override total post-step capture window (ms)")
    parser.add_argument("--poll-period-ms", type=float, default=3.0, help="poller sampling interval (ms)")
    parser.add_argument("--tolerance-pct", type=float, default=2.0, help="settling time error band (%%)")
    parser.add_argument("--load-ohms", type=float, default=10.0, help="output load resistor (Ohms)")
    parser.add_argument("--i-in-max", type=float, default=10.0, help="safety current limit (A)")
    parser.add_argument("--v-in-max", type=float, default=26.0, help="safety input voltage limit (V)")
    parser.add_argument("--v-out-max", type=float, default=26.0, help="safety output voltage limit (V)")
    parser.add_argument("--out", type=Path, default=None, help="CSV output file path")
    parser.add_argument("--plot", action="store_true", help="render matplotlib plots")
    parser.add_argument("--plot-out", type=Path, default=None, help="save plot image to file")
    parser.add_argument("--sim", action="store_true", help="run against software simulated SEPIC model")
    parser.add_argument("--bus", type=int, default=DEFAULT_BUS, help="SPI bus index")
    parser.add_argument("--device", type=int, default=DEFAULT_DEVICE, help="SPI device index")
    parser.add_argument("--speed-hz", type=int, default=200_000, help="SPI clock frequency (Hz)")
    args = parser.parse_args()

    steps = [float(s.strip()) for s in args.steps.split(",")]
    for d in steps:
        if not 0.0 <= d <= MAX_DUTY:
            parser.error(f"duty {d} outside allowable range [0.0, {MAX_DUTY}]")
    if len(steps) < 2:
        parser.error("At least 2 duty steps required")

    if args.window_ms is not None:
        settle_s = (args.window_ms / 1000.0) * 0.5
        ripple_s = (args.window_ms / 1000.0) * 0.5
    else:
        settle_s = args.settle_s
        ripple_s = args.ripple_s

    poll_period_s = args.poll_period_ms / 1000.0
    limits = Limits(args.i_in_max, args.v_in_max, args.v_out_max)

    out_csv = args.out or Path(
        f"data/step_responses/sepic_step_response_{args.load_ohms:g}R_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"
    )

    if args.sim:
        src = SimulatedSepicStepSource(v_in=12.0, load_ohms=args.load_ohms)
        print("Using Simulated SEPIC Source (--sim)")
    else:
        # Check if background mpp-web service is active and competing for the SPI link
        if shutil.which("systemctl"):
            try:
                res = subprocess.run(
                    ["systemctl", "is-active", "mpp-web.service"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.stdout.strip() == "active":
                    print(
                        "\n" + "!" * 80 + "\n"
                        "[WARNING] 'mpp-web.service' is running in the background!\n"
                        "It accesses SPI every 50 ms and commands duty=0, which will corrupt\n"
                        "step response measurements. Stop it with:\n"
                        "    sudo systemctl stop mpp-web.service\n"
                        + "!" * 80 + "\n"
                    )
            except Exception:
                pass

        try:
            from mpp_sdk.io.spi_mcu import SpiMcuSource

            src = SpiMcuSource(
                bus=args.bus,
                device=args.device,
                speed_hz=args.speed_hz,
                settling_time_s=0.0,
                oversample_count=0,
            )
            print(f"Connected to hardware SpiMcuSource on /dev/spidev{args.bus}.{args.device}")
        except Exception as exc:
            print(f"Hardware initialization failed ({exc}). Falling back to --sim.")
            src = SimulatedSepicStepSource(v_in=12.0, load_ohms=args.load_ohms)

    with Poller(src, limits, poll_period_s=poll_period_s) as poller:
        try:
            results = run_step_response_test(
                poller,
                steps,
                hold_s=args.hold_s,
                settle_s=settle_s,
                ripple_s=ripple_s,
                tolerance_pct=args.tolerance_pct,
            )
        except StepAborted as exc:
            print(f"ABORTED: {exc} - duty cycle set to 0.0")
            sys.exit(1)
        except KeyboardInterrupt:
            print("Stopped by operator - duty cycle set to 0.0")
            sys.exit(1)

    print_report(results, tolerance_pct=args.tolerance_pct)
    export_csv(results, out_csv, load_ohms=args.load_ohms)
    print(f"Saved telemetry data: {out_csv}")

    if args.plot or args.plot_out:
        plot_step_responses(results, out_path=args.plot_out, show=args.plot)


if __name__ == "__main__":
    main()
