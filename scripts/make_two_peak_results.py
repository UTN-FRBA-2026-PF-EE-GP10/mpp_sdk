"""Run every harness algorithm on committed measured I-V curves, offline.

Static simulation on measured curves (MeasuredPanel behind a SimulatedSource):
not a closed-loop bench run. Writes a markdown table and one PNG.

Usage::

    uv run python scripts/make_two_peak_results.py [--out-dir docs/results]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from harness import common
from mpp_sdk.curves import library
from mpp_sdk.models.measured import MeasuredPanel

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data" / "bench"
CURVES = [
    ("10 Ohm, B 60", BENCH / "two_panels_10R_20260926" / "curve_B60.json", 10.0),
    ("10 Ohm, B 30", BENCH / "two_panels_10R_20260926" / "curve_B30.json", 10.0),
    ("50 Ohm, B 45", BENCH / "two_panels_50R_20261017" / "curve_B45.json", 50.0),
]
START_DUTIES = (0.3, 0.5, 0.7)
N_STEPS = 2000
FOUND_RATIO = 0.98  # final power vs global MPP to count as "found"
SETTLE_BAND = 0.01  # power stays within 1 % of its final value


def interpolated_mpp(panel: MeasuredPanel, n: int = 800) -> float:
    """Global power peak of the interpolated curve, the target the algorithms see."""
    v = np.linspace(0.0, panel.open_circuit_voltage, n)
    return float(np.max(v * np.asarray(panel.current(v))))


def local_maxima(record, min_fraction: float = 0.05) -> list[tuple[float, float]]:
    """Return (V, P) of local maxima among the measured samples only.

    A hump that exists only between two far-apart samples comes from linear
    interpolation, so it is not counted.
    """
    by_v: dict[float, list[float]] = {}
    for v, i in record.points:
        by_v.setdefault(v, []).append(i)
    vs = sorted(by_v)
    ps = [v * float(np.mean(by_v[v])) for v in vs]
    floor = min_fraction * max(ps)
    return [
        (vs[k], ps[k])
        for k in range(1, len(vs) - 1)
        if ps[k] >= ps[k - 1] and ps[k] > ps[k + 1] and ps[k] > floor
    ]


def largest_gap(record) -> tuple[float, float]:
    """Return the widest voltage interval with no measured sample."""
    vs = sorted({v for v, _ in record.points})
    return max(zip(vs, vs[1:], strict=False), key=lambda ab: ab[1] - ab[0])


def run_one(make_ctl, panel, load: float, duty: float, n_steps: int) -> tuple[float, int]:
    """Return (final power, steps to settle). Settle = last step outside the band."""
    src = common.make_static_source(panel=panel, load_resistance=load, initial_duty=duty)
    ctl = make_ctl(duty)
    powers = []
    for _ in range(n_steps):
        v, i = src.read()
        powers.append(v * i)
        src.write(ctl.step(v, i))
    final = powers[-1]
    tol = SETTLE_BAND * max(final, 1e-9)
    outside = [k for k, p in enumerate(powers) if abs(p - final) > tol]
    return final, (outside[-1] + 1 if outside else 0)


# The committed results page documents these five. Keep the table fixed when
# the harness roster grows.
DOCUMENTED_LABELS = ("P&O", "InCond", "Fuzzy", "Scan&Track", "PSO")


def _documented_specs():
    by_label = {s.label: s for s in common.algorithm_specs()}
    return [by_label[label] for label in DOCUMENTED_LABELS]


def evaluate(curves, n_steps: int = N_STEPS, starts=START_DUTIES) -> list[dict]:
    rows = []
    specs = _documented_specs()
    for name, path, load in curves:
        record = library.load(Path(path))
        panel = MeasuredPanel(record)
        peaks = local_maxima(record)
        p_mpp = interpolated_mpp(panel)
        gap = largest_gap(record)
        peak_text = "; ".join(f"{v:.1f} V, {p:.2f} W" for v, p in peaks)
        for spec in specs:
            for d0 in starts:
                p_f, steps = run_one(spec.make, panel, load, d0, n_steps)
                rows.append(
                    {
                        "curve": name,
                        "peaks": peak_text,
                        "gap": f"{gap[0]:.1f} to {gap[1]:.1f} V",
                        "algorithm": spec.label,
                        "start": d0,
                        "p_final": p_f,
                        "p_mpp": p_mpp,
                        "eta": p_f / p_mpp if p_mpp else 0.0,
                        "found": p_mpp > 0 and p_f >= FOUND_RATIO * p_mpp,
                        "steps": steps,
                        "n_peaks": len(peaks),
                    }
                )
    return rows


def to_markdown(rows: list[dict]) -> str:
    out = [
        "| Curve | Peaks | Algorithm | Start D | Final P [W] | Efficiency | Global peak | Steps |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['curve']} | {r['peaks']} | {r['algorithm']} | {r['start']:.1f} "
            f"| {r['p_final']:.3f} | {r['eta'] * 100:.1f} % | {'yes' if r['found'] else 'no'} "
            f"| {r['steps']} |"
        )
    return "\n".join(out) + "\n"


def make_plot(rows: list[dict], curves, path: Path, start: float = 0.5) -> None:
    fig, axes = plt.subplots(1, len(curves), figsize=(5.5 * len(curves), 4.5), squeeze=False)
    colors = {s.label: s.color for s in _documented_specs()}
    for ax, (name, cpath, _) in zip(axes[0], curves, strict=True):
        panel = MeasuredPanel(library.load(Path(cpath)))
        v = np.linspace(0.0, panel.open_circuit_voltage, 400)
        ax.plot(v, v * np.asarray(panel.current(v)), "k-", lw=1)
        ax.set_title(f"{name} (start D {start})", fontsize=10)
        ax.set_xlabel("V [V]")
        ax.set_ylabel("P [W]")
        for r in rows:
            if r["curve"] == name and r["start"] == start:
                ax.axhline(
                    r["p_final"], color=colors[r["algorithm"]], ls=":", lw=1.2, label=r["algorithm"]
                )
        ax.legend(fontsize=7, title="final power")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "results")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = evaluate(CURVES, N_STEPS, START_DUTIES)
    table = to_markdown(rows)
    (args.out_dir / "two_peak_table.md").write_text(table)
    make_plot(
        rows,
        CURVES,
        args.out_dir / "two_peak_compare.png",
        START_DUTIES[0] if 0.5 not in START_DUTIES else 0.5,
    )
    print(table)


if __name__ == "__main__":
    main()
