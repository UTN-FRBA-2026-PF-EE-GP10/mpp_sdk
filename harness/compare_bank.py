"""Fixed test-case bank - the sim-to-real comparison scenarios.

Unlike the pseudo-random cyclic harness (the sim-only *ranking* tool), this
bank holds the handful of scenarios simple enough to replicate in all three
environments: this simulator, PLECS, and the physical bench. The bench
mapping is one shade cloth of ~30 % transmission on one panel:

  cold start    power up at full sun, controller starts from scratch
  cover on      full sun, then the cloth goes onto panel B (step down
                into a bimodal curve; from duty 0.5 the new operating
                point lands in the global basin, so this grades
                re-acquisition speed, not trapping)
  cover off     cloth on panel B, then it comes off (step up, unimodal)
  steady shade  cloth already on, cold start from duty 0.5: lands in
                the global basin, every controller should find the peak
  shade trap    cloth already on, cold start from duty 0.15 (the high
                voltage / Voc side): the operating point equilibrates in
                the local basin, so local trackers stay trapped on the
                6.6 W peak while global trackers must find the 9.5 W
                one. The start duty is a controller config knob, so this
                is exactly replicable on the bench.

Each scenario grades its *last* segment against that segment's global MPP
with the standard metrics (final efficiency, settling / re-acquisition time,
energy efficiency, ripple). Per the sim-to-real protocol in TODO.md, every
run also dumps a (t, V, I, D) trace CSV so the same duty sequence can be
replayed open-loop into PLECS (plant vs plant) and the same (V, I) stream
can be replayed through another controller implementation (controller vs
controller). PSO is included for completeness but is stochastic: use the
deterministic algorithms for cross-environment replay.

Outputs: ``harness/output/compare_bank.png`` and
``harness/output/bank_traces/<scenario>_<algorithm>.csv``.

Run with::

    uv run harness/compare_bank.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

import mpp_sdk
from harness.panel_config import CONTROL_PERIOD_MS, STC_IRRADIANCE, shaded_string

CLOTH_TRANSMISSION = 0.3  # shade-cloth transmission used on the bench
FULL = (STC_IRRADIANCE, STC_IRRADIANCE)
SHADED = (STC_IRRADIANCE, STC_IRRADIANCE * CLOTH_TRANSMISSION)

# (name, start duty, [(irradiance pair, n_steps), ...]) - metrics grade the
# last segment. The start duty sets which basin the operating point
# equilibrates in (raising D lowers the panel voltage, see AGENTS.md).
SCENARIOS = [
    ("cold start", 0.5, [(FULL, 1500)]),
    ("cover on", 0.5, [(FULL, 1500), (SHADED, 2000)]),
    ("cover off", 0.5, [(SHADED, 1500), (FULL, 2000)]),
    ("steady shade", 0.5, [(SHADED, 2000)]),
    ("shade trap", 0.15, [(SHADED, 2000)]),
]

BAND = 0.05
LAST_N = 100

# Detector-only configuration: the periodic rescan backstop belongs to the
# cyclic *ranking* harness (long chaotic schedules). On the bank's short
# single-change scenarios it would fire mid-segment and pollute the settle
# and energy numbers of every environment being compared.
ALGORITHMS = [
    ("P&O", lambda d: mpp_sdk.PerturbAndObserve(initial_duty=d)),
    ("InCond", lambda d: mpp_sdk.IncrementalConductance(initial_duty=d)),
    ("Fuzzy", lambda d: mpp_sdk.FuzzyLogic(initial_duty=d)),
    ("Scan&Track", lambda d: mpp_sdk.ScanAndTrack(initial_duty=d)),
    (
        "PSO",  # stochastic - excluded from cross-environment replay
        lambda d: mpp_sdk.ParticleSwarm(initial_duty=d, n_particles=8),
    ),
]

METRICS_GUIDE = """\
======================== HOW TO READ THE METRICS ========================
Each scenario is graded on its LAST segment, against that segment's
global MPP (P_mpp):

  final eta    settled power / P_mpp over the last 100 ms. Below 95 %
               means the controller ended trapped on a local peak.
  settle       time from the start of the last segment until the power
               enters the 5 % band of P_mpp and stays there. For the
               'cover' scenarios this is the re-acquisition time after
               the step; 'never' means it stayed out (trapped).
  eta energy   captured / available energy over the last segment,
               transient included.
  ripple       peak-to-peak power oscillation once settled, in W.

Each run also writes harness/output/bank_traces/<scenario>_<algo>.csv
with columns t_ms, v, i, duty for PLECS / bench replay (see TODO.md,
sim-to-real comparison protocol).
=========================================================================
"""


def build_conditions():
    """Tabulate each distinct irradiance pair once: ``{irr: (panel, p_mpp)}``."""
    conditions = {}
    for _, _, segments in SCENARIOS:
        for irr, _ in segments:
            if irr not in conditions:
                panel = mpp_sdk.TabulatedPanel(shaded_string(irr))
                conditions[irr] = (panel, panel.mpp()[2])
    return conditions


def run(make_ctl, initial_duty, segments, conditions):
    """Run one scenario; returns (v, i, duty) arrays over all segments."""
    src = mpp_sdk.DynamicSimulatedSource(
        panel=conditions[segments[0][0]][0],
        converter=mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=initial_duty,
        dt=CONTROL_PERIOD_MS * 1e-3,
    )
    ctl = make_ctl(initial_duty)
    n_total = sum(n for _, n in segments)
    vs, is_, ds = np.empty(n_total), np.empty(n_total), np.empty(n_total)
    k = 0
    for irr, n_steps in segments:
        src.set_panel(conditions[irr][0])
        for _ in range(n_steps):
            v, i = src.read()
            d = ctl.step(v, i)
            src.write(d)
            vs[k], is_[k], ds[k] = v, i, d
            k += 1
    return vs, is_, ds


def dump_trace(path, vs, is_, ds):
    t_ms = np.arange(vs.size) * CONTROL_PERIOD_MS
    np.savetxt(
        path,
        np.column_stack([t_ms, vs, is_, ds]),
        delimiter=",",
        header="t_ms,v,i,duty",
        comments="",
        fmt="%.6f",
    )


def main() -> None:
    conditions = build_conditions()
    trace_dir = Path(__file__).parent / "output" / "bank_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)

    print(METRICS_GUIDE)
    print(
        f"Bench mapping: shade cloth of {CLOTH_TRANSMISSION:.0%} transmission on panel B "
        f"({SHADED[1]:.0f} W/m² under {STC_IRRADIANCE:.0f} W/m² sun).\n"
    )
    header = (
        f"{'Scenario':<14}{'Algorithm':<12}{'final eta':<12}"
        f"{'settle [ms]':<13}{'eta energy':<12}{'ripple [W]':<10}"
    )
    print(header)
    print("-" * len(header))

    fig, axes = plt.subplots(len(SCENARIOS), 1, figsize=(12, 2.4 * len(SCENARIOS)), sharex=False)
    fig.suptitle(
        "Fixed test-case bank - 2× Hissuma PSF10MONO series (sim-to-real scenarios)",
        fontweight="bold",
    )
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for ax, (name, d0, segments) in zip(axes, SCENARIOS, strict=True):
        last_start = sum(n for _, n in segments[:-1])
        last_irr, last_n_steps = segments[-1]
        p_mpp = conditions[last_irr][1]
        p_mpp_t = np.concatenate([np.full(n, conditions[irr][1]) for irr, n in segments])
        time_ms = np.arange(p_mpp_t.size) * CONTROL_PERIOD_MS

        ax.plot(time_ms, p_mpp_t, "k--", lw=1, label="global MPP")
        for (label, make_ctl), color in zip(ALGORITHMS, colors, strict=False):
            vs, is_, ds = run(make_ctl, d0, segments, conditions)
            powers = vs * is_
            chunk = powers[last_start:]
            final = mpp_sdk.metrics.final_efficiency(chunk, p_mpp, last_n=LAST_N)
            settle = mpp_sdk.metrics.settling_time(chunk, p_mpp, dt=CONTROL_PERIOD_MS, band=BAND)
            eta = mpp_sdk.metrics.energy_efficiency(chunk, p_mpp)
            ripple = mpp_sdk.metrics.steady_state_ripple(chunk, last_n=LAST_N)
            settle_s = "never" if settle is None else f"{settle:.0f}"
            print(
                f"{name:<14}{label:<12}{final * 100:7.2f} %   {settle_s:>9}    "
                f"{eta * 100:7.2f} %   {ripple:7.3f}"
            )
            dump_trace(
                trace_dir / f"{name.replace(' ', '_')}_{label.replace('&', '')}.csv", vs, is_, ds
            )
            ax.plot(time_ms, powers, color=color, lw=0.9, label=label)

        if last_start:
            ax.axvline(last_start * CONTROL_PERIOD_MS, color="grey", lw=0.6, alpha=0.6)
        ax.set_title(name, fontsize=10, loc="left")
        ax.set_ylabel("Power [W]")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, ncols=3)
    axes[-1].set_xlabel("Time [ms]")

    out = Path(__file__).parent / "output" / "compare_bank.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out}")
    print(f"Traces: {trace_dir}/")


if __name__ == "__main__":
    main()
