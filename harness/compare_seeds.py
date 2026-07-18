"""PSO seed statistics - reporting a distribution, not a lucky trace.

PSO is stochastic: its particle updates draw on a random stream, so a single
``seed=0`` run is one sample, not the algorithm's typical behaviour. The PLAN
reproducibility rule asks for a distribution. This runs PSO over many seeds on
the cyclic schedule (the same seeded profile as ``compare_cyclic``) and reports
mean +/- std of the energy efficiency and the trap count, with the
deterministic Scan-and-Track as a fixed reference line.

Saves a PNG to ``harness/output/compare_seeds.png``.

Run with::

    uv run harness/compare_seeds.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness.compare_cyclic import (
    BAND,
    RESCAN_PERIOD,
    build_conditions,
    make_profile,
    plateau_spans,
    run,
    segment_stats,
)
from harness.panel_config import CONTROL_PERIOD_MS

N_SEEDS = 30  # PSO RNG seeds 0..N-1
N_PARTICLES = 8  # deployed swarm size (6 or fewer mis-locate under lag)


def pso_run(seed, schedule, conditions, spans, p_mpp_t):
    powers = run(
        lambda d: mpp_sdk.ParticleSwarm(
            initial_duty=d, n_particles=N_PARTICLES, rescan_period=RESCAN_PERIOD, seed=seed
        ),
        schedule,
        conditions,
    )
    eta = mpp_sdk.metrics.energy_efficiency(powers, p_mpp_t)
    _, finals = segment_stats(powers, spans, conditions)
    trapped = sum(f < 1.0 - BAND for f in finals)
    return eta * 100, trapped


def main() -> None:
    plateaus, schedule = make_profile()
    conditions = build_conditions(schedule)
    spans = plateau_spans(schedule)
    p_mpp_t = np.concatenate([np.full(n, conditions[irr][1]) for irr, n, _ in schedule])

    # Deterministic reference (no seed dependence).
    st_powers = run(
        lambda d: mpp_sdk.ScanAndTrack(initial_duty=d, rescan_period=RESCAN_PERIOD),
        schedule,
        conditions,
    )
    st_eta = mpp_sdk.metrics.energy_efficiency(st_powers, p_mpp_t) * 100
    _, st_finals = segment_stats(st_powers, spans, conditions)
    st_trapped = sum(f < 1.0 - BAND for f in st_finals)

    print(
        f"PSO seed statistics over {N_SEEDS} seeds "
        f"({N_PARTICLES} particles, rescan_period={RESCAN_PERIOD}, "
        f"cyclic schedule seed 1, {p_mpp_t.size * CONTROL_PERIOD_MS / 1e3:.1f} s).\n"
    )

    etas, traps = [], []
    for seed in range(N_SEEDS):
        eta, trapped = pso_run(seed, schedule, conditions, spans, p_mpp_t)
        etas.append(eta)
        traps.append(trapped)
    etas = np.asarray(etas)
    traps = np.asarray(traps)

    print(f"{'metric':<16}{'mean':<10}{'std':<10}{'min':<10}{'max':<10}")
    print("-" * 56)
    print(
        f"{'eta energy [%]':<16}{etas.mean():<10.2f}{etas.std():<10.2f}"
        f"{etas.min():<10.2f}{etas.max():<10.2f}"
    )
    print(
        f"{'trapped (/30)':<16}{traps.mean():<10.2f}{traps.std():<10.2f}"
        f"{traps.min():<10.0f}{traps.max():<10.0f}"
    )
    print(f"\nScan&Track reference (deterministic): eta {st_eta:.2f} %, trapped {st_trapped}/30")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(f"PSO seed spread over {N_SEEDS} seeds - cyclic schedule", fontweight="bold")

    ax1.hist(etas, bins=12, color="tab:orange", alpha=0.8, edgecolor="white")
    ax1.axvline(etas.mean(), color="k", lw=1.5, label=f"mean {etas.mean():.2f} %")
    ax1.axvspan(
        etas.mean() - etas.std(),
        etas.mean() + etas.std(),
        color="grey",
        alpha=0.2,
        label=f"+/- std ({etas.std():.2f})",
    )
    ax1.axvline(st_eta, color="tab:blue", ls="--", lw=1.5, label=f"Scan&Track {st_eta:.2f} %")
    ax1.set_xlabel("eta energy [%]")
    ax1.set_ylabel("seeds")
    ax1.set_title("Energy efficiency")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    bins = np.arange(traps.min(), traps.max() + 2) - 0.5
    ax2.hist(traps, bins=bins, color="tab:orange", alpha=0.8, edgecolor="white")
    ax2.axvline(traps.mean(), color="k", lw=1.5, label=f"mean {traps.mean():.2f}")
    ax2.axvline(st_trapped, color="tab:blue", ls="--", lw=1.5, label=f"Scan&Track {st_trapped}")
    ax2.set_xlabel("trapped plateaus (of 30)")
    ax2.set_ylabel("seeds")
    ax2.set_title("Trap count")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    out = Path(__file__).parent / "output" / "compare_seeds.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
