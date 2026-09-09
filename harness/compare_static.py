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
from harness import common
from harness.panel_config import series_string, shaded_string

N_STEPS = 2000
INITIAL_DUTY = 0.5

ALGORITHMS = [(s.label, s.make) for s in common.algorithm_specs()]

SCENARIOS = [
    ("Full sun (1000, 1000 W/m²)", series_string),
    ("Partial shade (1000, 400 W/m²)", shaded_string),
]


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Static MPPT comparison — final operating point", fontweight="bold")
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    mpp_sdk.metrics.print_methodology_warning()
    print(f"\n{'Scenario':<32}{'Algorithm':<10}{'V [V]':<9}{'P [W]':<9}{'η':<8}")
    print("-" * 68)

    for ax, (title, panel_fn) in zip(axes, SCENARIOS, strict=True):
        p_mpp, results = common.plot_pv_with_final_points(
            ax, panel_fn, ALGORITHMS, colors, n_steps=N_STEPS, initial_duty=INITIAL_DUTY
        )
        for label, v_f, p_f, eta in results:
            print(f"{title:<32}{label:<10}{v_f:<9.2f}{p_f:<9.2f}{eta * 100:5.1f} %")
        ax.set_title(title)

    out = Path(__file__).parent / "output" / "compare_static.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
