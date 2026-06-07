"""Static comparison — final operating point only, no transient.

Runs each algorithm against the instantaneous source (no capacitor dynamics)
and reports where it settles. Two scenarios: full sun and partial shade. The
P-V curve is drawn with each algorithm's final operating point marked, which
makes it obvious when plain P&O is trapped on a local maximum under shade.

Saves a PNG to ``harness/output/`` (does not block on a window).

Run with::

    uv run harness/compare_static.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import mpp_sdk
from harness.panel_config import make_static_source, series_string, shaded_string

N_STEPS = 2000
INITIAL_DUTY = 0.5

ALGORITHMS = [
    ("P&O", mpp_sdk.PerturbAndObserve),
    ("InCond", mpp_sdk.IncrementalConductance),
    ("Fuzzy", mpp_sdk.FuzzyLogic),
    ("Scan&Track", mpp_sdk.ScanAndTrack),
]

SCENARIOS = [
    ("Full sun (1000, 1000 W/m²)", series_string),
    ("Partial shade (1000, 400 W/m²)", shaded_string),
]


def final_point(ctl_cls, panel):
    src = make_static_source(panel=panel, initial_duty=INITIAL_DUTY)
    ctl = ctl_cls(initial_duty=INITIAL_DUTY)
    v = i = 0.0
    for _ in range(N_STEPS):
        v, i = src.read()
        src.write(ctl.step(v, i))
    return v, v * i


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Static MPPT comparison — final operating point", fontweight="bold")
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    print(f"\n{'Scenario':<32}{'Algorithm':<10}{'V [V]':<9}{'P [W]':<9}{'η':<8}")
    print("-" * 68)

    for ax, (title, panel_fn) in zip(axes, SCENARIOS, strict=True):
        panel = panel_fn()
        v_curve, i_curve = panel.iv_curve(n=400)
        p_curve = v_curve * i_curve
        v_mpp, _, p_mpp = panel.mpp()

        ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
        ax.plot(v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"global MPP ({p_mpp:.2f} W)")

        for (label, cls), color in zip(ALGORITHMS, colors, strict=False):
            v_f, p_f = final_point(cls, panel_fn())
            eta = p_f / p_mpp
            ax.plot(v_f, p_f, "o", color=color, ms=10, zorder=4, label=f"{label}: {p_f:.2f} W")
            print(f"{title:<32}{label:<10}{v_f:<9.2f}{p_f:<9.2f}{eta * 100:5.1f} %")

        ax.set_title(title)
        ax.set_xlabel("Voltage [V]")
        ax.set_ylabel("Power [W]")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)

    out = Path(__file__).parent / "output" / "compare_static.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
