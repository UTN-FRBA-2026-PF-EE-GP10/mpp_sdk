"""Compare MPPT algorithms against measured I-V curves — the payoff for
building the tracer: real panel data through the same algorithm bank as
every synthetic scenario, via `MeasuredPanel` and zero algorithm changes.

Loads every saved curve (`mpp_sdk.curves.library.load_all`), groups by
`measurement` kind, and for each kind saves one figure with one subplot per
record — final operating point of each algorithm marked on that record's
P-V curve, same layout as `compare_static.py`.

Saves PNGs to ``harness/output/`` (does not block on a window).

Run with::

    uv run mpp-sdk compare-measured
"""

import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import mpp_sdk
from harness import common
from mpp_sdk.curves import library
from mpp_sdk.models.measured import MeasuredPanel

N_STEPS = 2000
INITIAL_DUTY = 0.5

ALGORITHMS = [(s.label, s.make) for s in common.algorithm_specs()]


def _plot_record(ax, record, colors) -> None:
    panel = MeasuredPanel(record)
    p_mpp, results = common.plot_pv_with_final_points(
        ax,
        lambda: panel,
        ALGORITHMS,
        colors,
        n_steps=N_STEPS,
        initial_duty=INITIAL_DUTY,
        decimals=3,
        mpp_label="MPP",
        legend_fontsize=7,
    )
    for label, v_f, p_f, eta in results:
        print(f"{record.label:<32}{label:<10}{v_f:<9.2f}{p_f:<9.3f}{eta * 100:5.1f} %")

    ax.set_title(record.label, fontsize=10)


def main() -> None:
    records = library.load_all()
    if not records:
        print(f"No curves found under {library.default_dir()} - capture some first.")
        sys.exit(0)

    mpp_sdk.metrics.print_methodology_warning()
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for kind, kind_records in library.group_by_measurement(records).items():
        print(f"\n=== {kind} ({len(kind_records)} curve(s)) ===")
        print(f"{'Record':<32}{'Algorithm':<10}{'V [V]':<9}{'P [W]':<9}{'η':<8}")
        print("-" * 68)

        fig, axes = plt.subplots(
            1, len(kind_records), figsize=(6.5 * len(kind_records), 5), squeeze=False
        )
        fig.suptitle(f"Measured-curve MPPT comparison — {kind}", fontweight="bold")
        for ax, record in zip(axes[0], kind_records, strict=True):
            _plot_record(ax, record, colors)

        # `kind` is free text an operator can set to anything (see
        # mpp_sdk/curves/record.py's MEASUREMENT_KINDS docstring) - sanitize
        # before using it in a filename so e.g. a "/" can't be read as a
        # path separator into a directory that was never created.
        safe_kind = re.sub(r"[^A-Za-z0-9_.-]+", "-", kind).strip("-") or "curve"
        out = out_dir / f"compare_measured_{safe_kind}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=120)
        plt.close(fig)
        print(f"Saved: {out}")


if __name__ == "__main__":
    main()
