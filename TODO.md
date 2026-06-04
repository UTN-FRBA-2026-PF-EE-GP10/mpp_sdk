# TODO — Block 2 (weeks 5–8)

> Goal: SDK ready to run multi-algorithm comparisons in simulation.
> PCB is in fab — no firmware work until it arrives (~week 7–8).

---

## This week

- [ ] **Send PCB to fab** — export Gerbers, place order, order INA226 + op-amps _(B, 30 min)_
- [ ] **Understand pvlib** — run `pvlib.pvsystem.calcparams_desoto` + `singlediode` in a notebook
      against the panel datasheet. Get `v_mp`, `i_mp`, `p_mp` at STC and one off-STC point.
- [ ] **`PvlibPanelModel(PanelModel)`** — adapter wrapping pvlib behind the SDK interface.
      Start with a skeleton that delegates `iv_curve(v)` to pvlib's `singlediode`.
      Add temperature + irradiance inputs. Validate: `I(0) ≈ Isc`, `I(Voc) ≈ 0`, MPP matches pvlib's own `bishop88_mpp`.

---

## Next week

- [ ] **`IncrementalConductance`** — fixed-step InCond. Validate against `SimulatedSource`:
      must converge within ε W of MPP in ≤ N steps.
- [ ] **Harness scaffold** — `run_comparison(algorithms, source, n_steps) → DataFrame`.
      Two metrics to start: tracking efficiency `η = ⟨P⟩ / P_mpp` and settling time.
      Run P&O vs InCond against `PvlibPanelModel` at STC — produce one table.
- [ ] **Decide Global MPPT algorithm** — PSO or scan-and-track.
      Pick based on embeddability: which one fits ≤ 4 KB RAM with N fixed at compile time?

---

## Backlog (Block 3–4, after PCB arrives)

- [ ] `SingleDiodeWithLosses` — pedagogical in-tree model (low priority, can skip for paper)
- [ ] Adaptive-step P&O
- [ ] Global MPPT (whichever is decided above)
- [ ] Harness test cases: cold start, irradiance step, ramp, noise injection
- [ ] Auto-generated figures for paper
- [ ] `SpiMcuSource` — complete Pi-side SPI wrapper with watchdog
- [ ] Firmware HIL mode — full ADC + PWM + SPI closed loop (needs PCB)
- [ ] ADC calibration with INA226 (needs PCB)
- [ ] HIL end-to-end validation (Hito 2, week 16)

---

## Definition of done (per module)

1. Unit tests under `tests/` — public API in isolation.
2. Demo script under `examples/` — runs standalone, produces one interpretable plot.
3. Integration test — full loop: panel + converter + algorithm + source.
