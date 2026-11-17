"""Bench-like measurement - P&O, InCond and Fuzzy on a source that acts like the bench.

``BenchLikeSource`` adds sample-and-hold (2 ms), 1 mV / 1 mA quantisation and a
first-order settling lag to a clean simulated source. The same three local
trackers run on the plain source and on the bench-like source at a fast and a
slow decision rate, so the effect of "decisions faster than the converter
settles" can be seen. The table sweeps the exchange period.

Saves a PNG to ``harness/output/compare_bench_like.png``.

Run with::

    uv run harness/compare_bench_like.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness import common
from harness.panel_config import make_static_source

INITIAL_DUTY = 0.5
RUN_S = 10.0
SETTLE_TAU_S = 68e-3  # slowest settling seen on the bench
FAST_EXCHANGE_S = 1e-3
SLOW_EXCHANGE_S = 20e-3
SWEEP_EXCHANGE_S = (5e-4, 1e-3, 2e-3, 3e-3, 5e-3, 20e-3, 68e-3)


def _panel():
    return mpp_sdk.TabulatedPanel(mpp_sdk.PvlibPanelModel.hissuma_psf10mono())


def run(make_ctl, panel, exchange_s: float | None, tau_s: float = SETTLE_TAU_S):
    """Run one controller; ``exchange_s=None`` uses the plain source.

    Returns ``(time, duty)`` arrays, one point per decision.
    """
    inner = make_static_source(panel=panel, initial_duty=INITIAL_DUTY)
    if exchange_s is None:
        src, dt, n = inner, FAST_EXCHANGE_S, int(RUN_S / FAST_EXCHANGE_S)
    else:
        src = mpp_sdk.BenchLikeSource(inner, settle_tau_s=tau_s, exchange_period_s=exchange_s)
        dt, n = exchange_s, int(RUN_S / exchange_s)
    ctl = make_ctl(INITIAL_DUTY)
    duty = np.empty(n)
    for k in range(n):
        v, i = src.read()
        src.write(ctl.step(v, i))
        duty[k] = src.duty
    return np.arange(1, n + 1) * dt, duty


def main() -> None:
    panel = _panel()
    specs = common.algorithm_specs()[:3]
    cases = (
        ("plain simulated source", None),
        (f"bench-like, exchange {FAST_EXCHANGE_S * 1e3:g} ms", FAST_EXCHANGE_S),
        (f"bench-like, exchange {SLOW_EXCHANGE_S * 1e3:g} ms", SLOW_EXCHANGE_S),
    )
    fig, axes = plt.subplots(len(cases), 1, figsize=(9, 8), sharex=True, sharey=True)
    for ax, (title, ex) in zip(axes, cases, strict=True):
        for spec in specs:
            t, d = run(spec.make, panel, ex)
            ax.plot(t, d, color=spec.color, label=spec.label)
        ax.set_title(f"{title}, tau {SETTLE_TAU_S * 1e3:g} ms" if ex else title, fontsize=10)
        ax.set_ylabel("duty")
        ax.axhline(0.1, color="k", ls=":", lw=0.8)
        ax.grid(True, alpha=0.3)
    axes[0].legend(fontsize=8)
    axes[-1].set_xlabel("time [s]")
    fig.tight_layout()

    print(f"final duty after {RUN_S:g} s, tau {SETTLE_TAU_S * 1e3:g} ms, start {INITIAL_DUTY}")
    print("exchange [ms]  " + "  ".join(f"{s.label:>8}" for s in specs))
    for ex in SWEEP_EXCHANGE_S:
        finals = [run(s.make, panel, ex)[1][-1] for s in specs]
        print(f"{ex * 1e3:13g}  " + "  ".join(f"{d:8.3f}" for d in finals))

    out = Path(__file__).parent / "output" / "compare_bench_like.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
