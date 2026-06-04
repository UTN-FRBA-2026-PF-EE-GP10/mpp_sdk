"""Live animated MPPT comparison — watch algorithms climb the P-V curve.

Two algorithms run side by side against the dynamic (capacitor) source. Each
frame advances a few control steps, so you watch the operating point slew and
the MPPT converge in slow motion. Pick the scenario (full sun or partial
shade) on the command line.

Run with::

    uv run harness/animate.py                 # full sun
    uv run harness/animate.py --shade          # partial shade (two-peak P-V)
    uv run harness/animate.py --shade --speed 1   # one control step per frame
    uv run harness/animate.py --shade --duty 0.1  # start from the Voc side
                                                  # (watch P&O get trapped on the
                                                  #  local peak under shade)

Close the window to stop.
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

import mpp_sdk
from harness.panel_config import (
    CONTROL_PERIOD_MS,
    make_dynamic_source,
    series_string,
    shaded_string,
)

TRAIL = 60  # operating-point trail length

ALGORITHMS = [
    ("P&O", mpp_sdk.PerturbAndObserve, "tab:blue"),
    ("InCond", mpp_sdk.IncrementalConductance, "tab:red"),
    ("Fuzzy", mpp_sdk.FuzzyLogic, "tab:green"),
]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shade", action="store_true", help="partial-shade scenario")
    ap.add_argument(
        "--duty",
        type=float,
        default=0.5,
        help="initial duty cycle (low → start near Voc, high → start near Vsc)",
    )
    ap.add_argument("--speed", type=int, default=2, help="control steps advanced per frame")
    ap.add_argument("--interval", type=int, default=30, help="ms between frames (higher = slower)")
    return ap.parse_args()


class Runner:
    """One algorithm + dynamic source, advanced step by step."""

    def __init__(self, ctl_cls, panel_fn, initial_duty):
        self.src = make_dynamic_source(panel=panel_fn(), initial_duty=initial_duty)
        self.ctl = ctl_cls(initial_duty=initial_duty)
        self.trail: list[tuple[float, float]] = []

    def advance(self, n: int):
        for _ in range(n):
            v, i = self.src.read()
            self.src.write(self.ctl.step(v, i))
        self.trail.append((v, v * i))
        if len(self.trail) > TRAIL:
            del self.trail[: len(self.trail) - TRAIL]
        return v, v * i


def main():
    args = parse_args()
    panel_fn = shaded_string if args.shade else series_string
    title = "Partial shade (1000, 400 W/m²)" if args.shade else "Full sun (1000, 1000 W/m²)"

    # Reference P-V curve and global MPP (accurate model, sampled once).
    ref = panel_fn()
    v_curve, i_curve = ref.iv_curve(n=400)
    p_curve = v_curve * i_curve
    v_mpp, _, p_mpp = ref.mpp()

    fig, (ax, ax_t) = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)
    fig.suptitle(f"Live MPPT — {title}", fontweight="bold")

    # ── Left panel: P-V curve with moving operating points ───────────────────
    ax_iv = ax.twinx()
    ax_iv.plot(v_curve, i_curve, color="grey", lw=1.2, ls="--", alpha=0.6, zorder=0)
    ax_iv.set_ylabel("Current [A]", color="grey")
    ax_iv.tick_params(axis="y", labelcolor="grey")
    ax_iv.set_ylim(0, i_curve.max() * 1.25)

    ax.plot(v_curve, p_curve, "k-", lw=1.5, zorder=1, label="P-V curve")
    ax.plot(v_mpp, p_mpp, "k*", ms=16, zorder=2, label=f"global MPP ({p_mpp:.2f} W)")
    ax.plot([], [], color="grey", ls="--", alpha=0.6, label="I-V curve")
    ax.set_title("Operating point on P-V curve")
    ax.set_xlabel("Voltage [V]")
    ax.set_ylabel("Power [W]")
    ax.set_xlim(0, v_curve[-1] * 1.05)
    ax.set_ylim(0, p_curve.max() * 1.25)
    ax.set_zorder(ax_iv.get_zorder() + 1)  # keep P-V markers above the I-V backdrop
    ax.patch.set_visible(False)
    ax.grid(True, alpha=0.3)

    # ── Right panel: tracking efficiency vs time ─────────────────────────────
    # η = P / P_mpp in %. The y-axis is zoomed near 100 % so the steady-state
    # ripple is visible (a full 0–Pmpp power axis would hide it), while trapped
    # algorithms sit clearly lower (e.g. ~89 % on the local maximum).
    ax_t.axhline(100.0, color="k", lw=1, ls="--", label="global MPP (100 %)")
    ax_t.set_title("Tracking efficiency vs time")
    ax_t.set_xlabel("Time [ms]")
    ax_t.set_ylabel(r"$\eta = P / P_\mathrm{mpp}$  [%]")
    ax_t.set_ylim(80, 101)
    ax_t.grid(True, alpha=0.3)

    runners, dots, trails, time_lines = [], [], [], []
    p_hist: list[list[float]] = []
    t_hist: list[float] = []
    for label, cls, color in ALGORITHMS:
        runners.append(Runner(cls, panel_fn, args.duty))
        (trail_line,) = ax.plot([], [], "-", color=color, alpha=0.4, lw=1, zorder=3)
        (dot,) = ax.plot([], [], "o", color=color, ms=12, zorder=4, label=label)
        (t_line,) = ax_t.plot([], [], "-", color=color, lw=1.4, label=label)
        trails.append(trail_line)
        dots.append(dot)
        time_lines.append(t_line)
        p_hist.append([])

    readout = ax.text(
        0.02,
        0.97,
        "",
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8, edgecolor="none"),
    )
    ax.legend(loc="lower right")
    ax_t.legend(loc="lower right", fontsize=9)

    def update(frame):
        artists = []
        t_ms = frame * args.speed * CONTROL_PERIOD_MS
        t_hist.append(t_ms)
        for k, (runner, dot, trail, t_line) in enumerate(
            zip(runners, dots, trails, time_lines, strict=True)
        ):
            v, p = runner.advance(args.speed)
            arr = np.asarray(runner.trail)
            trail.set_data(arr[:, 0], arr[:, 1])
            dot.set_data([v], [p])
            p_hist[k].append(p / p_mpp * 100.0)  # tracking efficiency [%]
            t_line.set_data(t_hist, p_hist[k])
            artists += [trail, dot, t_line]
        # grow the time axis as the run advances
        ax_t.set_xlim(0, max(t_ms, 1))
        txt = [f"t = {t_ms:.0f} ms"]
        for (label, _, _), runner in zip(ALGORITHMS, runners, strict=True):
            v, p = runner.trail[-1]
            txt.append(f"{label}: {p:5.2f} W  ({p / p_mpp * 100:5.1f}%)")
        readout.set_text("\n".join(txt))
        artists.append(readout)
        return artists

    _ani = FuncAnimation(fig, update, interval=args.interval, blit=False, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    main()
