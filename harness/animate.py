"""Live animated MPPT comparison with interactive shading controls.

The registered MPPT algorithms run side by side against the dynamic (capacitor) source.
Left panel: operating point climbing the P-V curve (with the I-V curve in grey).
Right panel: tracking efficiency vs time.

Interactive controls (bottom of the window):
  - **G1, G2 sliders** — per-panel irradiance [W/m²]. Lower one panel to shade
    it; the P-V curve grows a second peak and you watch each algorithm respond
    live. Equal values = full sun.
  - **Reset button** — restart all algorithms from the initial duty.

Run with::

    uv run harness/animate.py                      # full sun (G1=G2=1000)
    uv run harness/animate.py --shade              # start shaded (G2=400)
    uv run harness/animate.py --duty 0.1           # start from the Voc side
    uv run harness/animate.py --interval 60 --speed 1   # slow motion

Close the window to stop.
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button, Slider

from harness import common
from harness.panel_config import CONTROL_PERIOD_MS
from mpp_sdk import (
    DynamicSimulatedSource,
    PvlibPanelModel,
    PvString,
    SEPICConverter,
    TabulatedPanel,
)

TRAIL = 60  # operating-point trail length
SCAN_SAMPLES = 240  # per-panel I-V samples (lower = snappier sliders)
# pvlib's De Soto model divides by irradiance (R_sh ∝ 1/G), so G=0 is undefined.
# Map a slider value of 0 ("panel off") to a tiny irradiance: the panel produces
# ~no current and its bypass diode drops it out of the string — effectively off.
G_OFF_FLOOR = 1.0  # W/m²

ALGORITHMS = [(s.label, s.make, s.color) for s in common.algorithm_specs()]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shade", action="store_true", help="start shaded (G2=400 W/m²)")
    ap.add_argument("--duty", type=float, default=0.5, help="initial duty cycle")
    ap.add_argument("--speed", type=int, default=2, help="control steps advanced per frame")
    ap.add_argument("--interval", type=int, default=30, help="ms between frames (higher = slower)")
    return ap.parse_args()


def build_panel(g1: float, g2: float) -> TabulatedPanel:
    """Two Hissuma panels in series, tabulated for fast (interp-only) lookups.

    Returns a ``TabulatedPanel`` so all downstream use (display curve, MPP,
    dynamic source) is pure ``np.interp`` — no per-point pvlib/bisection in the
    interactive hot path.
    """
    string = PvString(
        [
            PvlibPanelModel.hissuma_psf10mono(irradiance=max(g1, G_OFF_FLOOR)),
            PvlibPanelModel.hissuma_psf10mono(irradiance=max(g2, G_OFF_FLOOR)),
        ],
        samples=SCAN_SAMPLES,
    )
    return TabulatedPanel(string, n=SCAN_SAMPLES)


class Runner:
    """One algorithm + dynamic source, advanced step by step."""

    def __init__(self, make_ctl, panel, initial_duty):
        self._make_ctl = make_ctl
        self._duty0 = initial_duty
        self.ctl = make_ctl(initial_duty)
        self.src = DynamicSimulatedSource(
            panel=panel,
            converter=SEPICConverter(),
            load_resistance=10.0,
            initial_duty=initial_duty,
            dt=CONTROL_PERIOD_MS * 1e-3,
        )
        self.trail: list[tuple[float, float]] = []

    def set_panel(self, panel):
        self.src.set_panel(panel)

    def reset(self, panel):
        self.ctl = self._make_ctl(self._duty0)
        self.src = DynamicSimulatedSource(
            panel=panel,
            converter=SEPICConverter(),
            load_resistance=10.0,
            initial_duty=self._duty0,
            dt=CONTROL_PERIOD_MS * 1e-3,
        )
        self.trail.clear()

    def advance(self, n: int):
        v = i = 0.0
        for _ in range(n):
            v, i = self.src.read()
            self.src.write(self.ctl.step(v, i))
        self.trail.append((v, v * i))
        if len(self.trail) > TRAIL:
            del self.trail[: len(self.trail) - TRAIL]
        return v, v * i


def main():
    args = parse_args()
    g1_0, g2_0 = 1000.0, (400.0 if args.shade else 1000.0)

    # Mutable environment state shared with the animation closure.
    # `dirty`/`reset` are deferred flags so slider drags collapse to one rebuild
    # per frame instead of one per event (the source of the lag).
    tab = build_panel(g1_0, g2_0)
    env = {"panel": tab, "g": (g1_0, g2_0), "dirty": False, "reset": False}

    fig, (ax, ax_t) = plt.subplots(1, 2, figsize=(15, 7))
    fig.subplots_adjust(left=0.07, right=0.93, top=0.9, bottom=0.28, wspace=0.32)
    fig.suptitle("Live MPPT — interactive shading", fontweight="bold")

    # ── Left panel: P-V curve + I-V backdrop ─────────────────────────────────
    ax_iv = ax.twinx()
    v_curve, i_curve = env["panel"].iv_curve(n=400)
    (iv_line,) = ax_iv.plot(v_curve, i_curve, color="grey", lw=1.2, ls="--", alpha=0.6, zorder=0)
    ax_iv.set_ylabel("Current [A]", color="grey")
    ax_iv.tick_params(axis="y", labelcolor="grey")

    (pv_line,) = ax.plot(v_curve, v_curve * i_curve, "k-", lw=1.5, zorder=1, label="P-V curve")
    (mpp_marker,) = ax.plot([], [], "k*", ms=16, zorder=2, label="global MPP")
    ax.plot([], [], color="grey", ls="--", alpha=0.6, label="I-V curve")
    ax.set_title("Operating point on P-V curve")
    ax.set_xlabel("Voltage [V]")
    ax.set_ylabel("Power [W]")
    ax.set_zorder(ax_iv.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.grid(True, alpha=0.3)

    # ── Right panel: tracking efficiency vs time ─────────────────────────────
    ax_t.axhline(100.0, color="k", lw=1, ls="--", label="global MPP (100 %)")
    ax_t.set_title("Tracking efficiency vs time")
    ax_t.set_xlabel("Time [ms]")
    ax_t.set_ylabel(r"$\eta = P / P_\mathrm{mpp}$  [%]")
    ax_t.set_ylim(80, 101)  # auto-rescaled each frame to fit the data
    ax_t.grid(True, alpha=0.3)

    runners, dots, trails, time_lines = [], [], [], []
    p_hist: list[list[float]] = []
    t_hist: list[float] = []
    frame_offset = {"n": 0}  # frame counter base, reset when env changes
    for _label, make_ctl, color in ALGORITHMS:
        runners.append(Runner(make_ctl, tab, args.duty))
        (trail_line,) = ax.plot([], [], "-", color=color, alpha=0.4, lw=1, zorder=3)
        (dot,) = ax.plot([], [], "o", color=color, ms=12, zorder=4, label=_label)
        (t_line,) = ax_t.plot([], [], "-", color=color, lw=1.4, label=_label)
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
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8, edgecolor="none"),
    )
    ax.legend(loc="lower right", fontsize=8)
    ax_t.legend(loc="lower right", fontsize=8)

    mpp = {"v": 0.0, "p": 1.0}

    def refresh_curve():
        """Recompute the reference P-V / I-V curves and the global MPP.

        Uses the tabulated panel, so every call is vectorized ``np.interp`` —
        cheap enough to run inline in the animation loop.
        """
        v, i = env["panel"].iv_curve(n=400)
        p = v * i
        pv_line.set_data(v, p)
        iv_line.set_data(v, i)
        k = int(np.argmax(p))
        mpp_marker.set_data([v[k]], [p[k]])
        mpp["v"], mpp["p"] = float(v[k]), float(p[k])
        ax.set_xlim(0, v[-1] * 1.05)
        ax.set_ylim(0, max(p.max() * 1.25, 1e-3))
        ax_iv.set_ylim(0, max(i.max() * 1.25, 1e-3))

    def clear_histories():
        t_hist.clear()
        for h in p_hist:
            h.clear()

    refresh_curve()

    # ── Interactive widgets ──────────────────────────────────────────────────
    ax_g1 = fig.add_axes([0.10, 0.13, 0.55, 0.03])
    ax_g2 = fig.add_axes([0.10, 0.08, 0.55, 0.03])
    ax_reset = fig.add_axes([0.78, 0.09, 0.1, 0.05])
    s_g1 = Slider(ax_g1, "G1 [W/m²]", 0, 1000, valinit=g1_0, valstep=50)
    s_g2 = Slider(ax_g2, "G2 [W/m²]", 0, 1000, valinit=g2_0, valstep=50)
    b_reset = Button(ax_reset, "Reset")

    # Defer the heavy rebuild: slider callbacks only flag intent, so a burst of
    # drag events collapses to a single rebuild on the next animation frame.
    def on_irradiance(_val):
        env["g"] = (s_g1.val, s_g2.val)
        env["dirty"] = True

    def on_reset(_event):
        env["reset"] = True

    s_g1.on_changed(on_irradiance)
    s_g2.on_changed(on_irradiance)
    b_reset.on_clicked(on_reset)

    def apply_pending():
        """Process deferred slider / reset requests, at most once per frame."""
        if env["dirty"]:
            env["panel"] = build_panel(*env["g"])
            for r in runners:
                r.set_panel(env["panel"])  # keep state → watch algorithms re-track
            refresh_curve()
            clear_histories()
            frame_offset["n"] = 0
            env["dirty"] = False
        if env["reset"]:
            for r in runners:
                r.reset(env["panel"])
            clear_histories()
            frame_offset["n"] = 0
            env["reset"] = False

    def update(frame):
        apply_pending()
        artists = []
        frame_offset["n"] += 1
        t_ms = frame_offset["n"] * args.speed * CONTROL_PERIOD_MS
        t_hist.append(t_ms)
        p_mpp = max(mpp["p"], 1e-9)  # guard: both panels off → MPP ≈ 0
        for k, (runner, dot, trail, t_line) in enumerate(
            zip(runners, dots, trails, time_lines, strict=True)
        ):
            v, p = runner.advance(args.speed)
            arr = np.asarray(runner.trail)
            trail.set_data(arr[:, 0], arr[:, 1])
            dot.set_data([v], [p])
            p_hist[k].append(p / p_mpp * 100.0)
            t_line.set_data(t_hist[-len(p_hist[k]) :], p_hist[k])
            artists += [trail, dot, t_line]
        ax_t.set_xlim(0, max(t_ms, 1))
        # auto-rescale the efficiency axis to fit the data (with headroom to 100 %)
        lo = min((min(h) for h in p_hist if h), default=80.0)
        ax_t.set_ylim(max(0.0, np.floor(lo / 5) * 5 - 2), 101)
        txt = [f"t = {t_ms:.0f} ms   MPP = {p_mpp:.2f} W @ {mpp['v']:.1f} V"]
        for (label, _, _), runner in zip(ALGORITHMS, runners, strict=True):
            _v, p = runner.trail[-1]
            txt.append(f"{label}: {p:5.2f} W  ({p / p_mpp * 100:5.1f}%)")
        readout.set_text("\n".join(txt))
        artists.append(readout)
        return artists

    _ani = FuncAnimation(fig, update, interval=args.interval, blit=False, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    main()
