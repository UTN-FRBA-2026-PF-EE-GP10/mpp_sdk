"""Dynamic comparison — transient response under full sun and partial shade.

Runs each algorithm against the capacitor-dynamics source so you can see how
it reaches the MPP over time (settling, overshoot, oscillation). Two scenarios
side by side: full sun (unimodal P-V) and partial shade (two-peak P-V, where
plain P&O can get trapped on the local maximum).

Saves a PNG to ``harness/output/`` (does not block on a window).

Run with::

    uv run harness/compare_dynamic.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness.panel_config import (
    CONTROL_PERIOD_MS,
    make_dynamic_source,
    series_string,
    shaded_string,
)

N_STEPS = 1500
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


def run(ctl_cls, panel):
    src = make_dynamic_source(panel=panel, initial_duty=INITIAL_DUTY)
    ctl = ctl_cls(initial_duty=INITIAL_DUTY)
    powers = np.empty(N_STEPS)
    for k in range(N_STEPS):
        v, i = src.read()
        src.write(ctl.step(v, i))
        powers[k] = v * i
    return powers


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Dynamic MPPT response — 2× Hissuma PSF10MONO series", fontweight="bold")
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    time_ms = np.arange(N_STEPS) * CONTROL_PERIOD_MS

    print(f"\n{'Scenario':<32}{'Algorithm':<10}{'η final (last 100)':<20}")
    print("-" * 62)

    for ax, (title, panel_fn) in zip(axes, SCENARIOS, strict=True):
        panel = panel_fn()
        p_mpp = panel.mpp()[2]
        ax.axhline(p_mpp, color="k", lw=1, ls="--", label=f"global MPP = {p_mpp:.2f} W")
        for (label, cls), color in zip(ALGORITHMS, colors, strict=False):
            powers = run(cls, panel_fn())
            ax.plot(time_ms, powers, label=label, color=color, lw=1.2)
            eta = powers[-100:].mean() / p_mpp
            print(f"{title:<32}{label:<10}{eta * 100:6.2f} %")
        ax.set_title(title)
        ax.set_xlabel("Time [ms]")
        ax.set_ylabel("Power [W]")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(bottom=0)

    out = Path(__file__).parent / "output" / "compare_dynamic.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
