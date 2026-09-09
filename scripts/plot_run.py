"""Plot a saved closed-loop MPPT run: the real P-V curve (if a curve was
paired) with the run's trajectory overlaid, plus (V, I, P) time series.

No hardware - pure plotting from saved files.

Usage::

    uv run mpp-sdk plot-run [run_path]
    # defaults to the most recent file in mpp_sdk.runs.default_dir()
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mpp_sdk.curves import library as curve_library
from mpp_sdk.models.measured import MeasuredPanel
from mpp_sdk.runs import library as run_library


def _most_recent_run_path() -> Path:
    directory = run_library.default_dir()
    candidates = sorted(directory.glob("*.json")) if directory.exists() else []
    if not candidates:
        raise SystemExit(f"No runs found under {directory} - capture one first.")
    return candidates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_path", nargs="?", default=None)
    args = parser.parse_args()

    run_path = Path(args.run_path) if args.run_path else _most_recent_run_path()
    record = run_library.load(run_path)

    t = [s.t for s in record.samples]
    v = [s.voltage for s in record.samples]
    i = [s.current for s in record.samples]
    p = [s.voltage * s.current for s in record.samples]

    panel = None
    p_mpp = None
    if record.curve_ref is not None:
        curve_path = curve_library.default_dir() / record.curve_ref
        curve_record = curve_library.load(curve_path)
        panel = MeasuredPanel(curve_record)
        _, _, p_mpp = panel.mpp()
    else:
        print("No paired curve (curve_ref is None) - skipping the P-V subplot.")

    n_cols = 2 if panel is not None else 1
    fig, axes = plt.subplots(1, n_cols, figsize=(6.5 * n_cols, 5), squeeze=False)
    axes = axes[0]
    fig.suptitle(f"Closed-loop run - {record.label} ({record.algorithm})", fontweight="bold")

    col = 0
    if panel is not None:
        ax = axes[col]
        v_curve, i_curve = panel.iv_curve(n=400)
        p_curve = v_curve * i_curve
        v_mpp, _, _ = panel.mpp()
        ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
        ax.plot(v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"MPP ({p_mpp:.3f} W)")
        scatter = ax.scatter(v, p, c=t, cmap="viridis", zorder=2, label="run trajectory")
        fig.colorbar(scatter, ax=ax, label="time (s)")
        ax.set_xlabel("Voltage [V]")
        ax.set_ylabel("Power [W]")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        col += 1

    ax = axes[col]
    ax.plot(t, v, label="V [V]")
    ax.plot(t, i, label="I [A]")
    ax_p = ax.twinx()
    ax_p.plot(t, p, "g--", label="P [W]", alpha=0.7)
    if p_mpp is not None:
        ax_p.axhline(p_mpp, color="k", ls=":", lw=1, label=f"P_mpp ({p_mpp:.3f} W)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("V [V] / I [A]")
    ax_p.set_ylabel("P [W]")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax_p.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="best")
    ax.grid(True, alpha=0.3)
    if record.aborted:
        ax.set_title("aborted (safety cutoff)", color="red")

    out_dir = Path(__file__).parent.parent / "harness" / "output"
    out_dir.mkdir(exist_ok=True)
    slug = run_path.stem
    out = out_dir / f"plot_run_{slug}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
