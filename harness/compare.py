"""Algorithm comparison — visual harness for the 2× Hissuma series string.

Runs each registered algorithm for N steps and produces:
  - Power-vs-step trace (convergence + steady-state oscillation)
  - P-V curve of the series panel with the algorithm trajectories overlaid

Run with::

    uv run harness/compare.py
"""

import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness.panel_config import CONTROL_PERIOD_MS, make_source, series_string

# ── Experiment parameters ─────────────────────────────────────────────────────
N_STEPS = 600
STEP_SIZE = 0.005
INITIAL_DUTY = 0.5

# Algorithms to compare: (label, class)
ALGORITHMS = [
    ("P&O", mpp_sdk.PerturbAndObserve),
    ("InCond", mpp_sdk.IncrementalConductance),
]


def run_algorithm(ctl_cls, n_steps: int) -> dict:
    """Run one algorithm and return its trace."""
    panel = series_string()
    src = make_source(panel=panel, initial_duty=INITIAL_DUTY)
    ctl = ctl_cls(initial_duty=INITIAL_DUTY, step_size=STEP_SIZE)

    voltages, currents, powers = [], [], []
    for _ in range(n_steps):
        v, i = src.read()
        src.write(ctl.step(v, i))
        voltages.append(v)
        currents.append(i)
        powers.append(v * i)

    return {"v": np.array(voltages), "i": np.array(currents), "p": np.array(powers)}


def pv_curve(panel, n: int = 300) -> tuple:
    v_arr, i_arr = panel.iv_curve(n=n)
    return v_arr, v_arr * i_arr


def main() -> None:
    panel_ref = series_string()
    v_mpp, i_mpp, p_mpp = panel_ref.mpp()

    results = {label: run_algorithm(cls, N_STEPS) for label, cls in ALGORITHMS}

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(
        f"2× Hissuma PSF10MONO in series — P_mpp = {p_mpp:.2f} W  "
        f"(V_mpp = {v_mpp:.1f} V, I_mpp = {i_mpp:.3f} A)",
        fontweight="bold",
    )

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    # ── Left: power trace ─────────────────────────────────────────────────────
    ax_p = axes[0]
    time_ms = np.arange(N_STEPS) * CONTROL_PERIOD_MS
    ax_p.axhline(p_mpp, color="k", lw=1, ls="--", label=f"MPP = {p_mpp:.2f} W")
    for (label, _), color in zip(ALGORITHMS, colors, strict=False):
        p = results[label]["p"]
        ax_p.plot(time_ms, p, label=label, color=color, lw=1.2)
    ax_p.set_xlabel("Time [ms]")
    ax_p.set_ylabel("Power [W]")
    ax_p.set_title("Convergence")
    ax_p.legend()
    ax_p.grid(True, alpha=0.3)
    ax_p.set_ylim(bottom=0)

    # ── Right: P-V curve with operating-point trajectories ───────────────────
    ax_pv = axes[1]
    v_curve, p_curve = pv_curve(panel_ref)
    ax_pv.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
    ax_pv.plot(v_mpp, p_mpp, "k*", ms=12, zorder=3, label=f"MPP ({v_mpp:.1f} V)")

    for (label, _), color in zip(ALGORITHMS, colors, strict=False):
        v = results[label]["v"]
        p = results[label]["p"]
        ax_pv.scatter(v, p, s=2, color=color, alpha=0.4, zorder=2)
        # mark final operating point
        ax_pv.plot(v[-1], p[-1], "o", color=color, ms=8, label=f"{label} (final)", zorder=4)

    ax_pv.set_xlabel("Voltage [V]")
    ax_pv.set_ylabel("Power [W]")
    ax_pv.set_title("Operating-point trajectories on P-V curve")
    ax_pv.legend(fontsize=8)
    ax_pv.grid(True, alpha=0.3)
    ax_pv.set_xlim(left=0)
    ax_pv.set_ylim(bottom=0)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'Algorithm':<12} {'η_avg (last 100)':<20} {'P_final [W]'}")
    print("-" * 45)
    for label, _ in ALGORITHMS:
        p = results[label]["p"]
        eta = np.mean(p[-100:]) / p_mpp
        print(f"{label:<12} {eta:.4f} ({eta * 100:.2f} %)        {p[-1]:.4f}")

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
