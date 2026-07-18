"""Noise robustness - eta vs measurement-noise level (PLAN Phase 4).

Reruns a shortened version of the cyclic-shading schedule with Gaussian
measurement noise injected on (V, I) through ``NoisySource``, at several
noise levels, and reports how each algorithm's energy efficiency and trap
count degrade. The noise level is specified as a fraction of the
hardware full scale (V_IN_MAX = 40 V, I_MAX = 1 A from
``harness/panel_config.py``), matching how an acquisition chain is
specified: 1 % FS means sigma = 0.4 V on voltage and 0.01 A on current.
For reference, a clean 12-bit ADC on the same ranges has an LSB around
0.025 % FS; 0.5-2 % FS represents a noisy, unfiltered sense path.

What to look for:

- local trackers dither: the (dP, dV) sign decision randomizes once the
  per-sample noise approaches the perturbation step's power change;
- global searches mis-rank peaks: scan and swarm fitness samples are
  single noisy reads;
- the restart detector's debounce: spurious restarts would show up as a
  falling eta with *rising* trap-free success - watch the global rows.

Algorithms run in the same deployed configuration as the cyclic harness
(restart detector + rescan_period=1000, PSO with 8 particles). The noise
seed is fixed per run (PLAN reproducibility).

Saves a PNG to ``harness/output/compare_noise.png``.

Run with::

    uv run harness/compare_noise.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness import common
from harness.compare_cyclic import (
    ALGORITHMS,
    BAND,
    INITIAL_DUTY,
    build_conditions,
    make_profile,
    plateau_spans,
    segment_stats,
)
from harness.panel_config import CONTROL_PERIOD_MS, I_MAX, V_IN_MAX

N_SEGMENTS = 12  # shortened cyclic schedule: enough traps, 6x faster
PROFILE_SEED = 1
NOISE_SEED = 0
# Noise sigma as a fraction of hardware full scale (V_IN_MAX, I_MAX).
NOISE_LEVELS = (0.0, 0.001, 0.0025, 0.005, 0.01, 0.02)

METRICS_GUIDE = """\
======================== HOW TO READ THE METRICS ========================
The experiment: the same shading schedule is replayed at increasing
measurement noise. The panel and converter stay perfectly clean; the
noise is added ONLY to the (V, I) samples the controller sees, like a
noisy ADC. Scoring always uses the true delivered power.

  sigma %FS    the noise level: the standard deviation of the Gaussian
               noise as a percent of full scale (40 V / 1 A). Example:
               0.50 means every voltage sample is off by about +/-0.2 V
               and every current sample by about +/-5 mA. For scale, a
               clean 12-bit ADC is ~0.025 %FS; 0.5-2 % is a noisy,
               unfiltered sense path.
  eta energy   captured energy / available energy over the whole run.
               1.00 would be a perfect tracker; the row at sigma 0 is
               the noise-free baseline from the cyclic harness.
  success      plateaus (held conditions) that ENDED within 5 % of that
               condition's global MPP, out of 12.
  trapped      the other plateaus: ended more than 5 % below.

What the curves mean:
  - P&O / InCond fall off a cliff between 0.25 and 0.5 %FS. They decide
    direction by comparing power before and after a tiny duty step;
    once the noise on one sample is bigger than that tiny power change,
    the decision is a coin flip and the tracker random-walks away.
  - The global trackers degrade but hold a floor (~60 %): every search
    sweeps the whole range and yanks the operating point back near the
    peak, even when the local tracking in between dithers.
  - Fuzzy resists longer than P&O/InCond because its step size shrinks
    near the peak, but it has no search to rescue it, so it eventually
    falls too.
=========================================================================
"""


def run(make_ctl, schedule, conditions, noise_fs: float) -> np.ndarray:
    # grade on the *true* delivered power; only the controller sees noise
    v, i, _d = common.run_schedule(
        make_ctl,
        schedule,
        conditions,
        initial_duty=INITIAL_DUTY,
        noise_v_std=noise_fs * V_IN_MAX,
        noise_i_std=noise_fs * I_MAX,
        noise_seed=NOISE_SEED,
    )
    return v * i


def main() -> None:
    plateaus, schedule = make_profile(seed=PROFILE_SEED, n_segments=N_SEGMENTS)
    conditions = build_conditions(schedule)
    spans = plateau_spans(schedule)
    p_mpp_t = np.concatenate([np.full(n, conditions[irr][1]) for irr, n, _ in schedule])

    print(METRICS_GUIDE)
    print(
        f"Noise robustness over a {N_SEGMENTS}-plateau cyclic schedule "
        f"(seed {PROFILE_SEED}, {p_mpp_t.size * CONTROL_PERIOD_MS / 1e3:.1f} s per run, "
        f"full scale {V_IN_MAX:.0f} V / {I_MAX:.0f} A).\n"
    )
    header = f"{'sigma %FS':<11}{'Algorithm':<12}{'eta energy':<12}{'success':<10}{'trapped':<8}"
    print(header)
    print("-" * len(header))

    etas = {label: [] for label, _ in ALGORITHMS}
    traps = {label: [] for label, _ in ALGORITHMS}
    for noise_fs in NOISE_LEVELS:
        for label, make_ctl in ALGORITHMS:
            powers = run(make_ctl, schedule, conditions, noise_fs)
            eta = mpp_sdk.metrics.energy_efficiency(powers, p_mpp_t)
            _, finals = segment_stats(powers, spans, conditions)
            trapped = sum(f < 1.0 - BAND for f in finals)
            etas[label].append(eta)
            traps[label].append(trapped)
            print(
                f"{noise_fs * 100:7.2f}    {label:<12}{eta * 100:7.2f} %   "
                f"{len(finals) - trapped}/{len(finals):<7}{trapped:>4}"
            )
        print()

    x = [lv * 100 for lv in NOISE_LEVELS]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    fig.suptitle(
        "Noise robustness - 2× Hissuma PSF10MONO series, cyclic schedule",
        fontweight="bold",
    )
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for (label, _), color in zip(ALGORITHMS, colors, strict=False):
        ax1.plot(x, [e * 100 for e in etas[label]], "o-", color=color, label=label)
        ax2.plot(x, traps[label], "o-", color=color, label=label)
    ax1.set_ylabel("eta energy [%]")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=8)
    ax2.set_ylabel(f"trapped plateaus (of {len(spans)})")
    ax2.set_xlabel("measurement noise sigma [% of full scale]")
    ax2.grid(True, alpha=0.3)

    out = Path(__file__).parent / "output" / "compare_noise.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
