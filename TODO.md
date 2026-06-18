# TODO — Simulation SDK

> Scope: simulation only. Hardware / firmware / HIL items live elsewhere and
> wait on the PCB.
>
> Done so far: panel models (`PvlibPanelModel`, `PvString`, `TabulatedPanel`),
> algorithms (P&O, InCond, Fuzzy, Scan&Track, PSO) with a uniform restart
> policy (`PowerChangeDetector` + periodic `rescan_period`), dynamic source,
> comparison harnesses (static / dynamic / animated / **cyclic ranking** /
> **sim-to-real test bank** with trace dumps / **noise sweep** / **rescan
> sweep** / **PSO seed stats**, plus a headless `snapshot.py` still of the
> live view), metrics incl. the energy-integrated
> `energy_efficiency(P, P_mpp_t)`, algorithm docs.
> Findings so far live in `docs/algorithms/` (PSO needs 8 particles under
> measurement lag and mis-converges from a cold start under shade; local
> trackers trap at 44–67 % of available power; the trigger policy moves the
> numbers more than the search itself).

---

## Next

- [x] `NoisySource` — a `SignalSource` wrapper injecting seeded Gaussian V/I
      noise (`mpp_sdk/io/noisy.py`), plus `harness/compare_noise.py` (η and
      trap count vs noise level on the cyclic schedule). It pulled the
      clean-sim numbers apart as hoped: at 0.5 % FS the fixed-step locals
      collapse (P&O 56 % η), at 1 % they random-walk (19 %) while the global
      trackers hold 60–64 %; Fuzzy is markedly more noise-robust than
      P&O/InCond up to 1 %. No false restarts observed (debounce holds).
      Strong motivation for adaptive-step P&O and the own algorithm.
- [x] **`rescan_period` sweep** (`harness/compare_rescan.py`) — η energy and
      trapped count vs `rescan_period` ∈ {250, 500, 1000, 2000, off} for the
      global trackers on the cyclic schedule, plus the expected-loss model
      L(P) = A/P + B·P (search tax A measured in a steady-sun calibration,
      trap exposure B from the backstop-off run, mean plateau length D). The
      derived optimum P* = sqrt(A/B) ≈ 1034 steps lands on the empirical best
      (Scan&Track η peaks at 95.0 % at period 1000); over-frequent re-scanning
      (250) actually traps *more* often. Derived-then-measured paper figure.
- [x] Seed statistics for stochastic algorithms (`harness/compare_seeds.py`) —
      PSO over 30 seeds reports mean ± std (η 93.9 % ± 0.7, trapped 7.9 ± 1.7)
      vs the deterministic Scan&Track (95.0 %, 5 traps), which beats PSO's mean
      and trap count with zero variance. Reinforces Scan&Track as the MCU
      candidate.

## Backlog (simulation)

- [ ] Adaptive-step P&O
- [ ] Own algorithm — model-informed candidate scan (peaks near k·V_mp) plus a
      cumulative-drift trigger, aimed at minimal MCU cost. Prototype *after*
      noise and the rescan sweep exist so its value is measurable: a 3-point
      search makes aggressive re-checking affordable where the 23-point scan
      cannot.
- [ ] Harness test cases: cold start, irradiance ramp, step, measurement noise
      *(isolated cold start, steps and the Voc-side trap now live in
      `harness/compare_bank.py`; noise sweeps in `harness/compare_noise.py`;
      quantized ramps are mixed into the cyclic schedule but missing as an
      isolated case)*
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
