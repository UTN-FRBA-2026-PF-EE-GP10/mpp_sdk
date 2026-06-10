# TODO — Simulation SDK

> Scope: simulation only. Hardware / firmware / HIL items live elsewhere and
> wait on the PCB.
>
> Done so far: panel models (`PvlibPanelModel`, `PvString`, `TabulatedPanel`),
> algorithms (P&O, InCond, Fuzzy, Scan&Track, PSO) with a uniform restart
> policy (`PowerChangeDetector` + periodic `rescan_period`), dynamic source,
> comparison harnesses (static / dynamic / animated / **cyclic ranking** /
> **sim-to-real test bank** with trace dumps), metrics incl. the
> energy-integrated `energy_efficiency(P, P_mpp_t)`, algorithm docs.
> Findings so far live in `docs/algorithms/` (PSO needs 8 particles under
> measurement lag and mis-converges from a cold start under shade; local
> trackers trap at 44–67 % of available power; the trigger policy moves the
> numbers more than the search itself).

---

## Next

- [ ] `NoisySource` — a `SignalSource` wrapper injecting V/I measurement noise
      (the architectural home for the noise test case; keeps it out of the
      harness and the algorithms). Noise is the most likely thing to pull the
      clean-sim numbers apart and it stress-tests the restart detector's
      debounce for real.
- [ ] **`rescan_period` sweep** — η energy and trapped count vs
      `rescan_period` ∈ {250, 500, 1000, 2000, off} on the cyclic schedule,
      paired with the expected-loss derivation of the optimal period (search
      energy tax per period vs expected trapped time). Turns the trigger
      policy into a derived-then-measured paper figure.
- [ ] Seed statistics for stochastic algorithms — run PSO over N seeds and
      report mean ± std, not a single seed-0 trace (PLAN reproducibility rule)

## Backlog (simulation)

- [ ] Adaptive-step P&O
- [ ] Own algorithm — model-informed candidate scan (peaks near k·V_mp) plus a
      cumulative-drift trigger, aimed at minimal MCU cost. Prototype *after*
      noise and the rescan sweep exist so its value is measurable: a 3-point
      search makes aggressive re-checking affordable where the 23-point scan
      cannot.
- [ ] Harness test cases: cold start, irradiance ramp, step, measurement noise
      *(isolated cold start, steps and the Voc-side trap now live in
      `harness/compare_bank.py`; quantized ramps are mixed into the cyclic
      schedule but missing as an isolated case; noise missing entirely)*
- [ ] **Sim-to-real comparison protocol** - the cyclic harness is the sim-only
      ranking tool; replication on PLECS / the bench uses the fixed test-case
      bank (`harness/compare_bank.py`: cold start, cover-on step, cover-off
      step, steady shade, Voc-side shade trap; dumps (t, V, I, D) trace CSVs;
      `scripts/export_iv_plecs.py` (WIP) exports the panel curves for the
      PLECS lookup table) compared in three layers:
      1. plant vs plant: same recorded duty sequence open-loop into the
         Python source and the PLECS switched model, compare V(t)/I(t)
         (validates `DynamicSimulatedSource`; panel enters PLECS as a
         lookup-table current source exported from pvlib);
      2. controller vs controller: replay recorded (V, I) traces through the
         Python reference and the PLECS C-Script / MCU port, compare the
         emitted duty sequences point by point (deterministic algorithms
         only);
      3. closed loop: same bank in each environment, compare the metrics
         table within documented tolerances.
      Bench ground truth for P_mpp: a calibration duty sweep with the
      condition held, before each test case (the rig is its own instrument).
- [ ] Robustness vs **sample rate** (η at several control periods) — in PLAN
      Phase 4 alongside noise robustness
- [ ] 3- and 4-peak shading patterns — PLAN's test-case bank wants 2/3/4 local
      maxima; `harness/panel_config.py` only builds a 2-panel string (max 2
      peaks), so add a 3+ panel string config
- [ ] Implementation-cost metrics (state size, per-step compute) for the MCU story
- [ ] Auto-generated paper figures from the harness
- [ ] `SingleDiodeWithLosses` — pedagogical in-tree model (low priority)

---

## Definition of done (per module)

1. Unit tests under `tests/` — public API in isolation.
2. Demo script under `examples/` (or a harness entry) producing one plot.
3. Integration in the comparison harness.
