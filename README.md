# mpp-sdk

A Python SDK for designing, comparing, and deploying **Maximum Power Point
Tracking** (MPPT) algorithms for photovoltaic systems. Built around a clean
hardware-abstraction seam so the same controller code drives a simulation
today and a real boost converter on a Raspberry Pi 5 tomorrow.

See [`AGENTS.md`](./AGENTS.md) for architectural pillars and contribution
guidelines, [`PLAN.md`](./PLAN.md) for the full roadmap and viability
assessment, and [`CHANGELOG.md`](./CHANGELOG.md) for what has shipped.

## Why

The Python PV ecosystem has a strong **modelling** library
([`pvlib-python`](https://pvlib-python.readthedocs.io/)) but no shared
**control** library — pvlib gives you the panel physics, not the
closed-loop algorithms that decide where on the I-V curve to operate.
Most MPPT comparison work in the literature uses MATLAB / Simulink with
code that is rarely released and per-paper bespoke metrics, which makes
cross-paper comparisons and sim-to-real validation hard to reproduce
[Esram & Chapman 2007; Subudhi & Pradhan 2013].

`mpp-sdk` is built to close that gap with four concrete contributions:

1. **A uniform `MPPTAlgorithm.step(V, I) → D` interface** — adding a new
   controller is a one-file PR, and the comparison harness sees it like
   every other algorithm.
2. **A hardware-abstraction seam (`SignalSource`)** — the same algorithm
   code runs against a `SimulatedSource` *or* a real power-electronics
   board, with no branches in the algorithm.
3. **A microcontroller-as-deployment-target architecture.** The power
   stage is driven by a small MCU (Raspberry Pi Pico / RP2040 and ESP32
   are both under evaluation) connected to the Raspberry Pi 5 over SPI.
   This isolates the fast-switching / high-current side from the Pi
   *and* gives us the natural deployment target: once an algorithm has
   been validated against the framework, it is ported to the MCU and
   re-run end-to-end against the same physical rig.
4. **A reproducible comparison harness** — EN 50530 dynamic profiles,
   shared metrics (tracking efficiency, settling time, steady-state
   oscillation, step response), and paper figures regenerated from code.

> **The end deliverable of the thesis is an MCU-deployable algorithm
> that fits comfortably inside a Pico-class chip yet performs
> competitively with classical methods**, designed and validated
> end-to-end through the same codebase that compares it against the
> established literature. That MCU-deployment requirement is also a
> useful design constraint: it biases the work toward fixed-step,
> minimal-state methods that happen to be the easiest to analyse.

The full viability assessment, related-work survey, and risk mitigations
live in [`PLAN.md`](./PLAN.md).

## Installation

Once published to PyPI, install with `uv` (recommended) or `pip`:

```bash
# Core library — panel models, SEPIC converter, P&O, SimulatedSource
uv add mpp-sdk

# With high-fidelity pvlib panel models (PvlibPanelModel adapter)
uv add "mpp-sdk[pvlib]"

# With SPI hardware dependencies (Phase 5 — SpiMcuSource)
uv add "mpp-sdk[hardware]"

# Everything at once
uv add "mpp-sdk[all]"
```

Then import from your project:

```python
import mpp_sdk

panel = mpp_sdk.IdealSingleDiode()
conv  = mpp_sdk.SEPICConverter()
src   = mpp_sdk.SimulatedSource(panel, conv, load_resistance=10.0)
ctl   = mpp_sdk.PerturbAndObserve(initial_duty=src.duty)

for _ in range(500):
    v, i = src.read()
    src.write(ctl.step(v, i))
```

## Quickstart (development)

Clone the repo and run the live demo directly:

```bash
git clone https://github.com/<org>/mpp-sdk.git
cd mpp-sdk
uv sync
uv run main.py
```

This runs Perturb & Observe MPPT against the ideal single-diode panel model
and plots the I-V / P-V curves with the calculated MPP and the algorithm's
operating-point trajectory.

## Layout

```text
mpp_sdk/
├── models/         # Solar panel I-V models  (PanelModel ABC + IdealSingleDiode)
├── converters/     # Power-stage models      (BoostConverter)
├── algorithms/     # MPPT controllers        (MPPTAlgorithm ABC + PerturbAndObserve)
├── io/             # Hardware-abstraction    (SignalSource ABC + SimulatedSource)
└── visualization.py
```

The control variable is always the boost-converter **duty cycle**; the
measured quantities are always panel terminal **voltage** and **current**.
Richer panel models may depend on temperature, irradiance, or measured
curves, but those inputs live on the *model* — the controller never sees
them.

## Where mpp-sdk sits relative to pvlib

[`pvlib-python`](https://pvlib-python.readthedocs.io/) is the de-facto
open-source reference for photovoltaic system *performance modelling* in
Python — solar position, irradiance decomposition / transposition,
single- and two-diode I-V solvers, the `bishop88` reverse-bias method
that underpins partial-shading analysis, temperature models, and
inverter / energy-yield calculations [Anderson et al. 2023].

**pvlib does not provide closed-loop MPPT controllers, time-stepping
controller simulation, or hardware abstraction.** Its analytical
`bishop88_mpp` and single-diode MPP solvers return *the* maximum power
point given panel parameters; they do not implement Perturb & Observe,
Incremental Conductance, fuzzy logic, or any other tracking algorithm
that has to discover the MPP from a stream of (V, I) measurements.

`mpp-sdk` fills exactly that gap and is **complementary** to pvlib, not
a replacement:

| Concern                                  | pvlib            | mpp-sdk            |
| ---------------------------------------- | ---------------- | ------------------ |
| Solar resource & irradiance models       | yes              | out of scope       |
| Panel I-V physics (single / two-diode)   | yes (canonical)  | minimal in-tree    |
| Partial shading via `bishop88`           | yes              | wraps pvlib        |
| Closed-loop MPPT controllers (P&O, …)    | **no**           | **yes**            |
| Boost-converter / power-stage model      | no               | yes                |
| Hardware abstraction (`SignalSource`)    | no               | yes (RPi5 planned) |
| Algorithm benchmark / comparison harness | no               | yes (planned)      |

Concretely, the plan is to ship a `PvlibPanelModel(PanelModel)` adapter
in Phase 2 so that any pvlib-grade module can be dropped behind our
controller and converter pipeline without change. We do not intend to
re-implement panel physics that pvlib already provides under a more
authoritative implementation.

## Roadmap

Short list of what's next. The full plan — phases, milestones, verification
expectations, contributor liability, and LLM-usage policy — lives in
[`PLAN.md`](./PLAN.md).

### Models — single module (in-tree, pedagogical)

- [ ] `SingleDiodeWithLosses` — single-diode with `R_s` / `R_sh`
      (implicit I-V, hand-rolled Newton or bisection)

### Models — via `PvlibPanelModel` adapter (optional `mpp-sdk[pvlib]`)

- [ ] `PvlibPanelModel(PanelModel)` skeleton wrapping pvlib's
      `singlediode` and `bishop88` paths
- [ ] Temperature- and irradiance-aware single-diode via pvlib's
      `calcparams_cec` / `calcparams_desoto`
- [ ] Partial-shading / reverse-bias via pvlib's `bishop88` family
- [ ] CEC-module-database-backed lookups and / or user-supplied
      measured I-V tables under `data/`

### Models — arrays and shading

- [ ] Multi-panel `PanelArray(PanelModel)` composing modules in
      series / parallel topologies (S, P, SP, TCT, BL)
- [ ] Bypass diodes per panel or per substring
- [ ] Partial-shading scenarios — non-uniform per-panel irradiance
      yielding multi-modal P-V curves

### Algorithms

- [ ] Incremental Conductance (fixed and variable step)
- [ ] Adaptive-step P&O
- [ ] Fuzzy-logic and sliding-mode controllers
- [ ] Model-predictive controller
- [ ] Global MPPT for multi-modal P-V curves under partial shading
      (particle-swarm, periodic scan + local refinement, hybrid)
- [ ] Data-driven / RL baseline

### Comparison harness

- [ ] Standardized dynamic profiles (e.g. EN 50530)
- [ ] Tracking-efficiency, settling-time, steady-state-oscillation, and
      step-response metrics
- [ ] Auto-generated tables and plots consumed directly by the paper

### Hardware

The power-electronics board is driven by a small **microcontroller**
(candidates under evaluation: Raspberry Pi Pico / RP2040 and ESP32),
connected to the Raspberry Pi 5 over SPI. The MCU isolates the
fast-switching / high-current side from the Pi *and* doubles as the
deployment target for the final algorithm.

- [ ] `SpiMcuSource(SignalSource)` — Pi-side wrapper that sends a duty
      cycle and reads `(V, I)` from the MCU over SPI
- [ ] MCU firmware (HIL mode): ADC sense + hardware-PWM drive + SPI
      slave; in this mode the MCU is an I/O proxy and the algorithm
      still runs on the Pi in Python
- [ ] Calibration procedure (ADC scale / offset, sense-resistor value,
      PWM frequency, soft duty-cycle limits)
- [ ] Algorithm port from Python to the MCU (deployed mode): C with
      the Pico SDK or ESP-IDF, MicroPython / CircuitPython for early
      prototyping
- [ ] Cross-validation: deployed-MCU vs Pi-driven-Python on the same
      physical rig, same load profile, same recorded V/I/D traces
- [ ] Bench and outdoor validation against the simulator

### Infrastructure

- [ ] `tests/` with unit + integration tests for every pillar
- [ ] CI workflow (`uv sync`, `pytest`, demo smoke run)
- [ ] `data/` directory with provenanced benchmark profiles and panel curves

## Context

This SDK supports an **Electronics Engineering thesis** on MPPT algorithm
comparison. See [`PLAN.md`](./PLAN.md) for the full project plan, including
the contributor-liability statement, the policy on acknowledging LLM
usage, the viability / related-work analysis, and the requirement that
**each part of the SDK must work and be verified in isolation** before it
is integrated.

## References

The bibliography below is the working set the project cites; it will grow
as algorithms and models land.

### Reference Python framework

- **[Anderson et al. 2023]** Anderson, K. S., Hansen, C. W., Holmgren,
  W. F., Jensen, A. R., Mikofski, M. A., & Driesse, A. (2023). *pvlib
  python: 2023 project update.* Journal of Open Source Software,
  **8**(92), 5994. <https://doi.org/10.21105/joss.05994>
- **[Holmgren et al. 2018]** Holmgren, W. F., Hansen, C. W., & Mikofski,
  M. A. (2018). *pvlib python: a python package for modeling solar
  energy systems.* Journal of Open Source Software, **3**(29), 884.
  <https://doi.org/10.21105/joss.00884>

### Panel modelling

- **[Bishop 1988]** Bishop, J. W. (1988). *Computer simulation of the
  effects of electrical mismatches in photovoltaic cell interconnection
  circuits.* Solar Cells, **25**(1), 73–89. (Origin of the reverse-bias
  / breakdown model that pvlib's `bishop88` is named after.)
- **[De Soto et al. 2006]** De Soto, W., Klein, S. A., & Beckman, W. A.
  (2006). *Improvement and validation of a model for photovoltaic array
  performance.* Solar Energy, **80**(1), 78–88. (Single-diode model
  parameter extraction.)

### MPPT algorithm reviews and canonical methods

- **[Esram & Chapman 2007]** Esram, T., & Chapman, P. L. (2007).
  *Comparison of photovoltaic array maximum power point tracking
  techniques.* IEEE Transactions on Energy Conversion, **22**(2),
  439–449. (Canonical MPPT review.)
- **[Subudhi & Pradhan 2013]** Subudhi, B., & Pradhan, R. (2013). *A
  comparative study on maximum power point tracking techniques for
  photovoltaic power systems.* IEEE Transactions on Sustainable Energy,
  **4**(1), 89–98.
- **[Hussein et al. 1995]** Hussein, K. H., Muta, I., Hoshino, T., &
  Osakada, M. (1995). *Maximum photovoltaic power tracking: an
  algorithm for rapidly changing atmospheric conditions.* IEE
  Proceedings — Generation, Transmission and Distribution, **142**(1),
  59–64. (Incremental Conductance reference implementation.)
- **[Femia et al. 2005]** Femia, N., Petrone, G., Spagnuolo, G., &
  Vitelli, M. (2005). *Optimization of perturb and observe maximum
  power point tracking method.* IEEE Transactions on Power Electronics,
  **20**(4), 963–973. (P&O step-size design.)

### Partial shading and Global MPPT

- **[Patel & Agarwal 2008]** Patel, H., & Agarwal, V. (2008). *Maximum
  power point tracking scheme for PV systems operating under partially
  shaded conditions.* IEEE Transactions on Industrial Electronics,
  **55**(4), 1689–1698.
- **[Miyatake et al. 2011]** Miyatake, M., Veerachary, M., Toriumi, F.,
  Fujii, N., & Ko, H. (2011). *Maximum power point tracking of multiple
  photovoltaic arrays: a PSO approach.* IEEE Transactions on Aerospace
  and Electronic Systems, **47**(1), 367–380.
- **[Liu et al. 2012]** Liu, Y.-H., Huang, S.-C., Huang, J.-W., & Liang,
  W.-C. (2012). *A particle swarm optimization-based maximum power
  point tracking algorithm for PV systems operating under partially
  shaded conditions.* IEEE Transactions on Energy Conversion, **27**(4),
  1027–1035.

### Standards and benchmarking

- **[EN 50530]** CENELEC EN 50530:2010+A1:2013. *Overall efficiency of
  grid connected photovoltaic inverters.* (Defines the MPPT
  static- and dynamic-efficiency test profiles used as the comparison
  harness target.)
