# TODO — Simulation SDK

> Scope: simulation only. Hardware / firmware / HIL items live elsewhere and
> wait on the PCB.
>
> Done so far: panel models (`PvlibPanelModel`, `PvString`, `TabulatedPanel`),
> algorithms (P&O, InCond, Fuzzy, Scan&Track, PSO), dynamic source, comparison
> harness (static / dynamic / animated), preliminary metrics, algorithm docs.

---

## Next

- [ ] **Cyclic irradiance profile harness** — the valid efficiency measurement.
      Run each algorithm over a dynamic profile (full → A shaded → full →
      B shaded → both shaded → full, repeat) and report tracking efficiency as
      captured energy / ideal energy integrated over the whole profile.
      This replaces the current fixed-start steady comparison (see the
      methodology warning in `mpp_sdk.metrics`).
- [ ] **Investigate the re-acquisition failures** — under arbitrary irradiance
      changes some algorithms don't re-find the MPP. Characterise which, and why.

## Backlog (simulation)

- [ ] Adaptive-step P&O
- [ ] Own algorithm — model-informed candidate scan (peaks near k·V_mp), aimed
      at minimal MCU cost
- [ ] Harness test cases: cold start, irradiance ramp, step, measurement noise
- [ ] Implementation-cost metrics (state size, per-step compute) for the MCU story
- [ ] Auto-generated paper figures from the harness
- [ ] `SingleDiodeWithLosses` — pedagogical in-tree model (low priority)

---

## Definition of done (per module)

1. Unit tests under `tests/` — public API in isolation.
2. Demo script under `examples/` (or a harness entry) producing one plot.
3. Integration in the comparison harness.
