"""Re-scan period sweep - tuning the global trackers' periodic backstop.

The global trackers (Scan-and-Track, PSO) re-acquire the MPP two ways: a
change detector that fires on an abrupt power step, and a periodic backstop
that re-searches every ``rescan_period`` steps. The backstop exists for the
one change the detector cannot see - a slow ramp into a bimodal curve, where
the tracked power never steps - but it is not free: every periodic re-search
sweeps the duty range and spills energy. So there is an optimum period:

  too short  -> the search tax dominates (energy wasted re-scanning when
               nothing changed);
  too long   -> stealth traps persist longer before the backstop frees them.

This harness measures both sides on the cyclic schedule (the same seeded
profile as ``compare_cyclic``) and derives the optimum from first principles,
then checks the derivation against the measurement.

Derivation (loss as a fraction of the available energy, period P in steps):

    L(P) = A / P                +  B * P
           \\____search tax___/      \\__trap exposure__/

  - search tax: a periodic re-search costs a fixed energy ``e_s`` (measured
    in a steady-sun calibration, where re-scanning is the *only* loss). Over
    N schedule steps there are about N / P periodic re-searches, so the loss
    fraction is e_s * (N / P) / E = A / P with A = e_s * N / E.
  - trap exposure: with the backstop off, stealth traps cost a fraction
    ``L_off`` of the energy. A trap persists until the next periodic
    re-search, on average P / 2; for periods below the mean plateau length
    D the exposure scales with P, so the loss is about B * P with
    B = L_off / D.

  Minimising L(P): P* = sqrt(A / B). All of A, B come from measurements, so
  the predicted P* is then compared against the swept periods.

Saves a PNG to ``harness/output/compare_rescan.png``.

Run with::

    uv run harness/compare_rescan.py
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness.compare_cyclic import (
    BAND,
    build_conditions,
    make_profile,
    plateau_spans,
    run,
    segment_stats,
)
from harness.panel_config import CONTROL_PERIOD_MS, shaded_string

PERIODS = (250, 500, 1000, 2000, None)  # None = backstop off (detector only)
CAL_STEPS = 12000  # steady-sun calibration run length
CAL_PERIOD = 1000  # period used to price one periodic re-search

# Only the global trackers carry a periodic backstop; the locals have none.
GLOBALS = [
    ("Scan&Track", lambda d, p: mpp_sdk.ScanAndTrack(initial_duty=d, rescan_period=p)),
    ("PSO", lambda d, p: mpp_sdk.ParticleSwarm(initial_duty=d, n_particles=8, rescan_period=p)),
]

GUIDE = """\
==================== HOW TO READ THE RESCAN SWEEP ====================
Only the global trackers (Scan&Track, PSO) have a periodic re-search;
this sweeps how often it fires, over the cyclic schedule.

  rescan       period of the periodic backstop, in control steps (1 ms
               each). 'off' = no backstop, change detector only.
  eta energy   captured / available energy over the whole run.
  trapped      plateaus that ended more than 5 % below their MPP.

Short periods pay a search tax (re-scanning when nothing changed);
long periods let stealth traps (slow ramps into a bimodal curve)
persist. The model below predicts the period that balances the two.
=====================================================================
"""


def trapped_energy_deficit(powers, spans, conditions) -> float:
    """Energy lost on trapped plateaus, as a fraction of available energy.

    A plateau counts as trapped when it ends more than ``BAND`` below its
    MPP; its deficit is the integral of ``P_mpp - P`` over the plateau. This
    is the ``L_off`` the periodic backstop is there to cut down.
    """
    _, finals = segment_stats(powers, spans, conditions)
    deficit = 0.0
    available = 0.0
    for (start, n_steps, irr), final in zip(spans, finals, strict=True):
        p_mpp = conditions[irr][1]
        available += p_mpp * n_steps
        if final < 1.0 - BAND:
            chunk = powers[start : start + n_steps]
            deficit += float(np.sum(np.maximum(p_mpp - chunk, 0.0)))
    return deficit / available


def calibrate_search_tax(make_ctl) -> float:
    """Energy a single periodic re-search spills, in steady full sun [W*steps].

    Runs the tracker in unchanging full sun twice - backstop off, then every
    ``CAL_PERIOD`` steps. With no shading change the only difference is the
    periodic re-searches, so the extra energy lost divided by their count is
    the price of one re-search.
    """
    panel = mpp_sdk.TabulatedPanel(shaded_string((1000.0, 1000.0)))
    p_mpp = panel.mpp()[2]
    schedule = [((1000.0, 1000.0), CAL_STEPS, 0)]
    conditions = {(1000.0, 1000.0): (panel, p_mpp)}

    p_off = run(lambda d: make_ctl(d, None), schedule, conditions)
    p_on = run(lambda d: make_ctl(d, CAL_PERIOD), schedule, conditions)
    extra_loss = float(np.sum(p_off - p_on))  # W*steps lost to periodic scans
    n_rescans = CAL_STEPS // CAL_PERIOD
    return max(extra_loss, 0.0) / n_rescans


def main() -> None:
    plateaus, schedule = make_profile()
    conditions = build_conditions(schedule)
    spans = plateau_spans(schedule)
    p_mpp_t = np.concatenate([np.full(n, conditions[irr][1]) for irr, n, _ in schedule])
    n_total = p_mpp_t.size
    e_available = float(np.sum(p_mpp_t))
    mean_plateau = float(np.mean([n for _, n, _ in spans]))

    print(GUIDE)
    print(
        f"Re-scan sweep over the cyclic schedule (seed 1): {len(plateaus)} plateaus, "
        f"{n_total * CONTROL_PERIOD_MS / 1e3:.1f} s, mean plateau {mean_plateau:.0f} steps.\n"
    )
    header = f"{'rescan':<9}{'Algorithm':<12}{'eta energy':<12}{'trapped':<9}"
    print(header)
    print("-" * len(header))

    etas = {label: [] for label, _ in GLOBALS}
    traps = {label: [] for label, _ in GLOBALS}
    for period in PERIODS:
        for label, make_ctl in GLOBALS:
            powers = run(lambda d, mc=make_ctl, p=period: mc(d, p), schedule, conditions)
            eta = mpp_sdk.metrics.energy_efficiency(powers, p_mpp_t)
            _, finals = segment_stats(powers, spans, conditions)
            trapped = sum(f < 1.0 - BAND for f in finals)
            etas[label].append(eta)
            traps[label].append(trapped)
            tag = "off" if period is None else str(period)
            print(f"{tag:<9}{label:<12}{eta * 100:7.2f} %    {trapped:>3}/{len(finals)}")
        print()

    # ── Expected-loss model (derived from measurements) ──────────────────────
    # Use Scan&Track: the deterministic MCU candidate.
    s_make = GLOBALS[0][1]
    e_s = calibrate_search_tax(s_make)
    powers_off = run(lambda d: s_make(d, None), schedule, conditions)
    l_off = trapped_energy_deficit(powers_off, spans, conditions)
    a_coef = e_s * n_total / e_available
    b_coef = l_off / mean_plateau
    p_star = math.sqrt(a_coef / b_coef) if b_coef > 0 else float("inf")

    print("Expected-loss model (Scan&Track):")
    print(f"  search tax per re-search e_s = {e_s:.3g} W*steps")
    print(f"  trapped-energy fraction (backstop off) L_off = {l_off * 100:.2f} %")
    print(f"  A = {a_coef:.4g} (steps),  B = {b_coef:.3g} (1/steps)")
    print(f"  derived optimum  P* = sqrt(A/B) = {p_star:.0f} steps")
    finite = [p for p in PERIODS if p is not None]
    best = min(finite, key=lambda p: a_coef / p + b_coef * p)
    print(f"  nearest swept period minimising L(P): {best} steps\n")

    # ── Plots ────────────────────────────────────────────────────────────────
    x = list(range(len(PERIODS)))
    labels = ["off" if p is None else str(p) for p in PERIODS]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        "Re-scan period sweep - 2x Hissuma PSF10MONO series, cyclic schedule",
        fontweight="bold",
    )
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for (label, _), color in zip(GLOBALS, colors, strict=False):
        ax1.plot(x, [e * 100 for e in etas[label]], "o-", color=color, label=label)
        ax2.plot(x, traps[label], "o-", color=color, label=label)
    for ax in (ax1, ax2):
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_xlabel("rescan_period [steps]")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
    ax1.set_ylabel("eta energy [%]")
    ax1.set_title("Efficiency vs period")
    ax2.set_ylabel(f"trapped plateaus (of {len(spans)})")
    ax2.set_title("Traps vs period")

    pp = np.linspace(100, 3000, 400)
    ax3.plot(pp, a_coef / pp * 100, "--", color="tab:orange", label="search tax  A/P")
    ax3.plot(pp, b_coef * pp * 100, "--", color="tab:green", label="trap exposure  B*P")
    ax3.plot(pp, (a_coef / pp + b_coef * pp) * 100, "-", color="tab:blue", label="total L(P)")
    ax3.axvline(p_star, color="k", ls=":", lw=1, label=f"P* = {p_star:.0f}")
    ax3.set_xlabel("rescan_period [steps]")
    ax3.set_ylabel("expected energy loss [%]")
    ax3.set_title("Expected-loss model (Scan&Track)")
    ax3.set_ylim(bottom=0)
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=9)

    out = Path(__file__).parent / "output" / "compare_rescan.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
