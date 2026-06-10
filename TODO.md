# TODO — Simulation SDK

> Scope: simulation only. Hardware / firmware / HIL items live elsewhere and
> wait on the PCB.
>
> Done so far: panel models (`PvlibPanelModel`, `PvString`, `TabulatedPanel`),
> algorithms (P&O, InCond, Fuzzy, Scan&Track, PSO), dynamic source, comparison
> harness (static / dynamic / animated), preliminary metrics, algorithm docs.

---

## Next

- [x] **Cyclic irradiance profile harness** — `harness/compare_cyclic.py`.
      Runs each algorithm over full → A shaded → full → B shaded → both →
      full (×2 cycles) and reports energy-integrated efficiency against the
      time-varying global MPP, per-segment re-acquisition time, and
      global-MPP success rate.
- [x] **Investigate the re-acquisition failures** — characterised:
      - Local trackers (P&O, InCond, Fuzzy) re-acquire in ~10 ms but settle on
        the *local* peak in single-shaded segments (trap depth ≈ 0.90) —
        expected, they are local methods.
      - The global trackers had **no working restart**: `ParticleSwarm` had no
        mechanism at all; `ScanAndTrack.rescan_period` was disabled by default
        and unused by the harness. Fixed (next item).
      - PSO under measurement lag (capacitor slew, 1 kHz loop): 6 particles
        find the global basin for only ~60 % of seeds after a shading change;
        8 are reliable (see `docs/algorithms/particle_swarm.md`).
- [x] **Re-trigger policy for global algorithms** — change-detection restart
      (`PowerChangeDetector`, |ΔP|/P > 20 % for 3 consecutive steps, on by
      default) applied uniformly to `ScanAndTrack` and `ParticleSwarm`. The
      detector arms only after the post-search transient settles, and its
      in-band reference follows the power so the converter's own recovery
      can't cause a restart loop. Periodic `rescan_period` retained as the
      safety net for creeping changes the step detector cannot see.
- [x] **Profile-aware metrics** — `metrics.energy_efficiency(P, P_mpp_t)`
      accepts a time-varying reference; re-acquisition time and success rate
      are computed per segment in the cyclic harness from the existing
      primitives. (Worst-case trap depth across *many* patterns waits on the
      3/4-peak shading bank below.)

## Backlog (simulation)

- [ ] Adaptive-step P&O
- [ ] Own algorithm — model-informed candidate scan (peaks near k·V_mp), aimed
      at minimal MCU cost
- [ ] Harness test cases: cold start, irradiance ramp, step, measurement noise
      *(cold start, steps and quantized ramps are now mixed into the cyclic
      schedule; still missing as isolated cases, and noise entirely)*
- [ ] `NoisySource` — a `SignalSource` wrapper injecting V/I measurement noise
      (the architectural home for the noise test case; keeps it out of the
      harness and the algorithms)
- [ ] Seed statistics for stochastic algorithms — run PSO over N seeds and
      report mean ± std, not a single seed-0 trace (PLAN reproducibility rule)
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
