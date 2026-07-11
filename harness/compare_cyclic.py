"""Cyclic-shading comparison — the valid dynamic efficiency measurement.

Drives each algorithm through a long, seeded, pseudo-random irradiance
schedule against the capacitor-dynamics source. This is the measurement the
methodology warning in ``mpp_sdk.metrics`` calls for: instead of grading a
fixed start in steady conditions, every controller must repeatedly
*re-acquire* the MPP as the P-V curve changes shape under it.

The schedule is deliberately chaotic but **reproducible** (fixed RNG seed,
per the PLAN's reproducibility policy). It alternates *plateaus* — a
per-panel irradiance pair held for a random 0.4–1.5 s — with, on roughly
half of the transitions, a **ramp**: the irradiance slews linearly to the
next plateau over 0.2–0.8 s (quantized to 50 W/m², each sub-step moving
power by only a few percent). Plateau conditions mix:

- deep partial shading (bright panel at 800–1000, shaded at 200–400 W/m²) —
  these leave the local peak at well under half the global power, so a
  trapped tracker is punished hard;
- uniform steps across 200–1000 W/m² (unimodal — the local tracker must
  follow them) and recoveries to full sun.

Ramps matter for the *trigger policy*: a slow slide into a bimodal curve
never steps the tracked power, so the global trackers' change detector stays
silent and only the periodic re-search backstop can free them. The global
trackers therefore run as they would be deployed: change-detection restart
(library default) **plus** ``rescan_period=1000`` (a ≈2–4 % energy tax that
bounds how long a stealth change can trap them), and PSO with 8 particles
(6 or fewer mis-locate the global basin under measurement lag for a large
fraction of seeds).

Reported per algorithm (segment statistics are over plateaus only; ramp
periods count toward the energy efficiency, graded against the moving MPP):

- **η energy** — captured / ideally-available energy over the whole schedule
  (``metrics.energy_efficiency``). Energy-weighted, so deep-shade failures
  dent it less than they should intuitively — read it together with:
- **trapped** — the honest trap metric: how many plateaus ended more than
  5 % below the segment's global MPP, and the mean / worst settled fraction
  of available power *over those trapped segments* ("when it's trapped, it
  delivers X % of what the panel could give");
- **success** — plateaus that ended within 5 % of the global MPP;
- **re-acquisition** — per plateau, time until the power is back within 5 %
  of the new global MPP and stays there (mean / max over settled plateaus).

How each run works: a fresh controller and a fresh ``DynamicSimulatedSource``
per algorithm; the harness swaps the panel under the source (``set_panel``)
at every schedule step — instantly at plateau boundaries, in small quantized
moves along ramps — while the controller keeps its state. The controller
only ever sees ``(V, I)``.

Saves a PNG to ``harness/output/`` (does not block on a window).

Run with::

    uv run harness/compare_cyclic.py
"""

import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness import common
from harness.panel_config import CONTROL_PERIOD_MS

PROFILE_SEED = 1  # fixed for reproducibility — change to stress differently
N_SEGMENTS = 30
LEVELS = (200.0, 400.0, 600.0, 800.0, 1000.0)  # W/m² per panel
BRIGHT = (800.0, 1000.0)  # bright-panel levels in a shading segment
SHADE = (200.0, 400.0)  # shaded-panel levels — deep traps, local/global < 0.5
MIN_SEG_STEPS, MAX_SEG_STEPS = 400, 1500  # plateau hold, 0.4–1.5 s at 1 kHz
COLD_START_STEPS = 800
RAMP_PROB = 0.5  # fraction of transitions that slew instead of stepping
MIN_RAMP_STEPS, MAX_RAMP_STEPS = 200, 800  # ramp duration, 0.2–0.8 s
RAMP_QUANTUM = 50.0  # W/m² grid for ramp interpolation (cache-friendly)
INITIAL_DUTY = 0.5
BAND = 0.05  # "at the MPP" means within 5 % of the segment's global MPP
LAST_N = 100  # samples used to judge where a segment *ended*

RESCAN_PERIOD = 1000  # periodic re-search backstop for the global trackers

METRICS_GUIDE = """\
======================== HOW TO READ THE METRICS ========================
Everything compares captured power against P_mpp: the best possible
power for the current conditions (the global MPP).

Whole run:
  eta energy   captured energy / available energy over the whole run,
               ramps included. The bottom-line energy bill. It is
               weighted by available energy, so failures during deep
               shade (little energy on offer) dent it surprisingly
               little: always read it together with 'trapped'.

Per plateau (each held condition is graded on its own):
  success      plateaus whose last 100 ms sit within 5 % of P_mpp:
               the controller ended on the right peak.
  trapped      plateaus that ended below that band: stuck on a local
               peak. 'trap mean' and 'trap worst' are the settled power
               as a fraction of P_mpp in exactly those plateaus, i.e.
               "when trapped, it delivers X % of what the panel could
               give".
  reacq        time from the start of a plateau until the power enters
               the 5 % band and stays there: how fast the controller
               re-acquires the MPP after a change. Mean and max are
               taken over the plateaus that settled at all.

Rule of thumb: eta energy is the outcome, trapped is the why, reacq is
the recovery speed. Local trackers are fast but blind (small reacq,
many traps); global trackers are thorough but slow (few traps, large
reacq, paid for by their search transients).
=========================================================================
"""

ALGORITHMS = [
    (s.label, s.make) for s in common.algorithm_specs(rescan_period=RESCAN_PERIOD, pso_particles=8)
]


def _ramp_chunks(start, end, n_steps):
    """Quantized linear slew from irradiance pair ``start`` to ``end``.

    Returns ``[(irr, n_steps, None), …]`` runs on the ``RAMP_QUANTUM`` grid.
    Quantizing keeps the set of distinct panel models small enough to
    tabulate while each sub-step moves the power by only a few percent —
    smooth as far as the controllers can tell.
    """
    chunks = []
    last = None
    for k in range(n_steps):
        f = (k + 1) / n_steps
        pair = tuple(
            RAMP_QUANTUM * round((a + f * (b - a)) / RAMP_QUANTUM)
            for a, b in zip(start, end, strict=True)
        )
        if pair == last:
            chunks[-1][1] += 1
        else:
            chunks.append([pair, 1])
            last = pair
    return [(pair, n, None) for pair, n in chunks]


def make_profile(seed: int = PROFILE_SEED, n_segments: int = N_SEGMENTS):
    """Reproducible chaotic irradiance schedule.

    Returns ``(plateaus, schedule)``: ``plateaus`` is ``[(label, irr,
    n_steps), …]`` — the held conditions the segment statistics grade — and
    ``schedule`` is the full step sequence ``[(irr, n_steps, plateau_idx or
    None), …]`` including the quantized ramp runs between plateaus.

    Plateau moves are drawn from three kinds — deep partial shading (one
    panel bright, one heavily shaded: the bimodal trap case the global
    trackers exist for), a uniform step of both panels to a common level (a
    unimodal move the local tracker should follow), or a return to full sun
    — so traps of varying depth alternate with recoveries. About
    ``RAMP_PROB`` of the transitions slew smoothly instead of stepping.
    """
    rng = random.Random(seed)
    plateaus = [("1000/1000", (1000.0, 1000.0), COLD_START_STEPS)]
    irr = (1000.0, 1000.0)
    for _ in range(n_segments - 1):
        while True:
            kind = rng.random()
            if kind < 0.55:  # deep partial shading — bimodal curve
                pair = (rng.choice(BRIGHT), rng.choice(SHADE))
                candidate = pair if rng.random() < 0.5 else pair[::-1]
            elif kind < 0.8:  # uniform step, both panels together
                level = rng.choice(LEVELS)
                candidate = (level, level)
            else:  # back to full sun
                candidate = (1000.0, 1000.0)
            if candidate != irr:
                break
        irr = candidate
        n_steps = rng.randrange(MIN_SEG_STEPS, MAX_SEG_STEPS + 1)
        plateaus.append((f"{irr[0]:.0f}/{irr[1]:.0f}", irr, n_steps))

    schedule = []
    prev = None
    for idx, (_, irr, n_steps) in enumerate(plateaus):
        if prev is not None and rng.random() < RAMP_PROB:
            ramp_steps = rng.randrange(MIN_RAMP_STEPS, MAX_RAMP_STEPS + 1)
            schedule.extend(_ramp_chunks(prev, irr, ramp_steps))
        schedule.append((irr, n_steps, idx))
        prev = irr
    return plateaus, schedule


def build_conditions(schedule):
    """Tabulate each distinct irradiance pair once: ``{irr: (panel, p_mpp)}``.

    The tabulated panels are read-only and shared by every algorithm's source,
    and their own ``mpp()`` is the reference so the simulated world and the
    ideal-energy reference are the same curve.
    """
    return common.build_conditions(irr for irr, _, _ in schedule)


def run(make_ctl, schedule, conditions) -> np.ndarray:
    v, i, _d = common.run_schedule(make_ctl, schedule, conditions, initial_duty=INITIAL_DUTY)
    return v * i


def plateau_spans(schedule):
    """Start index and length of each plateau within the flat power trace."""
    spans = []
    k = 0
    for irr, n_steps, idx in schedule:
        if idx is not None:
            spans.append((k, n_steps, irr))
        k += n_steps
    return spans


def segment_stats(powers, spans, conditions):
    """Per-plateau re-acquisition times and end-of-segment efficiencies."""
    times: list[float | None] = []
    finals: list[float] = []
    for start, n_steps, irr in spans:
        p_mpp = conditions[irr][1]
        chunk = powers[start : start + n_steps]
        times.append(mpp_sdk.metrics.settling_time(chunk, p_mpp, dt=CONTROL_PERIOD_MS, band=BAND))
        finals.append(mpp_sdk.metrics.final_efficiency(chunk, p_mpp, last_n=LAST_N))
    return times, finals


def main() -> None:
    plateaus, schedule = make_profile()
    conditions = build_conditions(schedule)
    spans = plateau_spans(schedule)
    p_mpp_t = np.concatenate([np.full(n, conditions[irr][1]) for irr, n, _ in schedule])
    total_steps = p_mpp_t.size
    time_s = np.arange(total_steps) * CONTROL_PERIOD_MS * 1e-3

    n_ramps = sum(
        1
        for k in range(1, len(schedule))
        if schedule[k][2] is not None and schedule[k - 1][2] is None
    )
    print(METRICS_GUIDE)
    print(
        f"Pseudo-random shading schedule (seed {PROFILE_SEED}): "
        f"{len(plateaus)} plateaus, {n_ramps} ramped transitions, "
        f"{total_steps * CONTROL_PERIOD_MS / 1e3:.1f} s total, "
        f"per-panel irradiance in {{{', '.join(f'{lv:.0f}' for lv in LEVELS)}}} W/m².\n"
    )
    header = (
        f"{'Algorithm':<12}{'η energy':<11}{'success':<10}"
        f"{'trapped':<10}{'trap mean':<11}{'trap worst':<12}{'reacq mean':<12}{'reacq max':<10}"
    )
    print(header)
    print("-" * len(header))

    fig, axes = plt.subplots(
        len(ALGORITHMS), 1, figsize=(14, 2.2 * len(ALGORITHMS)), sharex=True, sharey=True
    )
    fig.suptitle(
        "Cyclic-shading MPPT response — 2× Hissuma PSF10MONO series "
        f"(pseudo-random schedule with ramps, seed {PROFILE_SEED})",
        fontweight="bold",
    )
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for ax, (label, make_ctl), color in zip(axes, ALGORITHMS, colors, strict=False):
        powers = run(make_ctl, schedule, conditions)
        eta = mpp_sdk.metrics.energy_efficiency(powers, p_mpp_t)
        times, finals = segment_stats(powers, spans, conditions)
        settled = [t for t in times if t is not None]
        successes = sum(f >= 1.0 - BAND for f in finals)
        trapped = [f for f in finals if f < 1.0 - BAND]
        trap_mean = f"{np.mean(trapped) * 100:5.1f} %" if trapped else "-"
        trap_worst = f"{min(trapped) * 100:5.1f} %" if trapped else "-"
        mean_t = f"{np.mean(settled):.0f} ms" if settled else "-"
        max_t = f"{max(settled):.0f} ms" if settled else "-"
        print(
            f"{label:<12}{eta * 100:6.2f} %   {successes}/{len(finals):<7}"
            f"{len(trapped):>4}    {trap_mean:>8}   {trap_worst:>8}    {mean_t:>8}  {max_t:>8}"
        )

        ax.plot(time_s, p_mpp_t, "k--", lw=1, label="global MPP")
        ax.plot(time_s, powers, color=color, lw=0.8, label=label)
        for start, _, _ in spans[1:]:
            ax.axvline(start * CONTROL_PERIOD_MS * 1e-3, color="grey", lw=0.4, alpha=0.35)
        ax.set_title(f"{label} — η_energy = {eta * 100:.1f} %", fontsize=10, loc="left")
        ax.set_ylabel("Power [W]")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.3)

    # Per-plateau irradiance labels along the top of the first subplot.
    top = axes[0]
    for (start, n_steps, _), (seg_label, _, _) in zip(spans, plateaus, strict=True):
        mid = (start + 0.5 * n_steps) * CONTROL_PERIOD_MS * 1e-3
        top.annotate(
            seg_label,
            (mid, 1.04),
            xycoords=("data", "axes fraction"),
            ha="center",
            fontsize=6,
            rotation=90,
            color="grey",
        )
    axes[-1].set_xlabel("Time [s]")

    out = Path(__file__).parent / "output" / "compare_cyclic.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
