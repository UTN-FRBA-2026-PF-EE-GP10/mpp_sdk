"""Compare the SEPIC reflected resistance model with bench duty-sweep data.

Measured R_in = V_in / I_in at each duty point. Compared with the ideal
formula R_load * ((1 - D) / D)^2 and with ``SEPICConverter`` (which is
lossless, so it only differs from the formula by its duty clamp).

Usage::

    uv run python scripts/check_rin_model.py [csv ...] [--plot out.png]

With no CSV, the committed bench files under ``data/bench`` are used.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

from mpp_sdk.converters import SEPICConverter

BENCH = Path(__file__).resolve().parent.parent / "data" / "bench"
TOLERANCE = 0.10


def load_points(paths: list[Path]) -> list[dict]:
    """Return rows with duty > 0 and a usable input current, sorted by duty."""
    rows = []
    for path in paths:
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                d, v, i = float(r["duty"]), float(r["v_in"]), float(r["i_in"])
                if d <= 0.0 or i <= 0.0:
                    continue
                rows.append({"duty": d, "v_in": v, "i_in": i, "load": float(r["load_ohms"])})
    return sorted(rows, key=lambda r: r["duty"])


def evaluate(rows: list[dict]) -> list[dict]:
    sepic = SEPICConverter()
    out = []
    for r in rows:
        d, load = r["duty"], r["load"]
        measured = r["v_in"] / r["i_in"]
        ideal = load * ((1.0 - d) / d) ** 2
        model = sepic.reflected_resistance(d, load)
        err = (ideal - measured) / measured
        out.append({**r, "measured": measured, "ideal": ideal, "model": model, "err": err})
    return out


def summarize(res: list[dict]) -> str:
    errs = [abs(r["err"]) for r in res]
    ok = [r["duty"] for r in res if abs(r["err"]) <= TOLERANCE]
    span = f"D {min(ok):.2f} to {max(ok):.2f}" if ok else "no duty point"
    return (
        "relative error (ideal - measured) / measured: "
        f"median {statistics.median(errs) * 100:.1f} %, "
        f"max {max(errs) * 100:.1f} %; ideal formula within {TOLERANCE * 100:.0f} % at {span}"
    )


def format_table(res: list[dict]) -> str:
    lines = [f"{'duty':>6} {'measured':>10} {'ideal':>10} {'model':>10} {'rel err':>9}"]
    for r in res:
        lines.append(
            f"{r['duty']:6.3f} {r['measured']:10.2f} {r['ideal']:10.2f} "
            f"{r['model']:10.2f} {r['err'] * 100:8.1f}%"
        )
    return "\n".join(lines)


def make_plot(res: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    d = [r["duty"] for r in res]
    ax.semilogy(d, [r["measured"] for r in res], "o", label="measured")
    ax.semilogy(d, [r["ideal"] for r in res], "-", label="ideal formula")
    ax.set_xlabel("duty")
    ax.set_ylabel("R_in [Ohm]")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="*", type=Path)
    ap.add_argument("--plot", type=Path, default=None, help="write a PNG here (default: no plot)")
    args = ap.parse_args(argv)
    paths = args.csv or sorted(BENCH.glob("duty_*.csv"))
    res = evaluate(load_points(paths))
    if not res:
        raise SystemExit("no usable duty points")
    print(format_table(res))
    print(summarize(res))
    if args.plot:
        make_plot(res, args.plot)


if __name__ == "__main__":
    main()
