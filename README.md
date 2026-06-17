<div align="center">

# mpp-sdk

[![Hardware preview](https://img.shields.io/badge/hardware-open%20in%20KiCanvas-2b6cb0?logo=kicad&logoColor=white)](https://kicanvas.org/?github=https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/tree/main/hardware)

</div>

A Python SDK for designing, comparing, and deploying **Maximum Power Point
Tracking** (MPPT) algorithms for photovoltaic systems. Built around a clean
hardware-abstraction seam so the same controller code drives a simulation
today and a real SEPIC converter on a Raspberry Pi 5 tomorrow.

See [`AGENTS.md`](./AGENTS.md) for architectural pillars and contribution
guidelines, and [`PLAN.md`](./PLAN.md) for the full roadmap and viability
assessment.

## Why

The Python PV ecosystem has a strong **modelling** library
([`pvlib-python`](https://pvlib-python.readthedocs.io/)) but no shared
**control** library — pvlib gives you the panel physics, not the
closed-loop algorithms that decide where on the I-V curve to operate.
Most MPPT comparison work in the literature uses MATLAB / Simulink with
code that is rarely released and per-paper bespoke metrics, which makes
cross-paper comparisons and sim-to-real validation hard to reproduce
[Subudhi & Pradhan 2013].

`mpp-sdk` is built to close that gap with four concrete contributions:

1. **A uniform `MPPTAlgorithm.step(V, I) → D` interface** — adding a new
   controller is a one-file PR, and the comparison harness sees it like
   every other algorithm.
2. **A hardware-abstraction seam (`SignalSource`)** — the same algorithm
   code runs against a `SimulatedSource` *or* a real power-electronics
   board, with no branches in the algorithm.
3. **A microcontroller-as-deployment-target architecture.** The power
   stage is driven by a small MCU (Raspberry Pi Pico / RP2040) connected
   to the Raspberry Pi 5 over SPI.
   This isolates the fast-switching / high-current side from the Pi
   *and* gives us the natural deployment target: once an algorithm has
   been validated against the framework, it is ported to the MCU and
   re-run end-to-end against the same physical rig.
4. **A reproducible comparison harness** — dynamic irradiance profiles, shared
   metrics (tracking efficiency, settling time, steady-state oscillation, trap
   depth), and paper figures regenerated from code.

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
├── models/         # Solar panel I-V models  (PanelModel ABC; ideal, pvlib, string, tabulated)
├── converters/     # Power-stage models      (SEPICConverter)
├── algorithms/     # MPPT controllers        (MPPTAlgorithm ABC; P&O, InCond, fuzzy, scan, PSO)
├── io/             # Hardware-abstraction    (SignalSource ABC; simulated, dynamic)
├── metrics.py      # Comparison metrics
└── visualization.py

harness/            # Comparison scripts (static, dynamic, live, cyclic ranking, sim-to-real bank)
docs/               # Algorithm references, rationale, general information
```

The control variable is always the SEPIC **duty cycle**; the
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

What's shipped and what's next. The full plan — phases, milestones, verification
expectations, contributor liability, and LLM-usage policy — lives in
[`PLAN.md`](./PLAN.md).

### Models

- [x] `IdealSingleDiode` — explicit closed-form I(V) (in-tree, pedagogical)
- [x] `PvlibPanelModel` — pvlib De Soto adapter, temperature/irradiance aware
      (optional `mpp-sdk[pvlib]`); `from_datasheet` + `hissuma_psf10mono`
- [x] `PvString` — series panels with bypass diodes → multi-modal P-V curves
- [x] `TabulatedPanel` — cached I-V curve for fast repeated lookups
- [ ] `SingleDiodeWithLosses` — in-tree `R_s` / `R_sh` (implicit I-V)

### Algorithms

- [x] Perturb & Observe
- [x] Incremental Conductance
- [x] Fuzzy-logic (local tracker)
- [x] Scan-and-track (global MPPT)
- [x] Particle Swarm Optimization (global MPPT)
- [ ] Adaptive-step P&O; own model-informed candidate scan
- [ ] Data-driven / RL baseline

### Comparison harness

- [x] Static, dynamic, and live interactive (`harness/`)
- [x] Preliminary metrics — tracking efficiency, settling time, ripple, overshoot,
      trap depth (`mpp_sdk.metrics`)
- [x] Cyclic irradiance profile for a valid dynamic efficiency measurement
      (`harness/compare_cyclic.py`, `metrics.energy_efficiency`)
- [x] Fixed sim-to-real test-case bank (`harness/compare_bank.py`) with
      (t, V, I, D) trace dumps for PLECS / bench replay
- [ ] Auto-generated paper figures

### Hardware (future — see [`PLAN.md`](./PLAN.md))

The power stage is driven by an **RP2040 (Pi Pico, firmware in Rust)** connected
to the Raspberry Pi 5 over SPI. The MCU isolates the fast-switching side *and* is
the deployment target for the final algorithm.

- [x] SPI-slave firmware scaffold (PIO)
- [ ] `SpiMcuSource(SignalSource)` — Pi-side SPI wrapper (`mpp-sdk[hardware]`)
- [ ] MCU firmware (HIL mode): ADC + PWM + SPI-slave as an I/O proxy
- [ ] Calibration (ADC scale/offset, INA226 gain, PWM freq, duty limits)
- [ ] Algorithm port to RP2040 + cross-validation against the Python reference
- [ ] Bench and outdoor validation against the simulator

### Infrastructure

- [x] `tests/` — unit tests per pillar (`pytest`)
- [ ] CI workflow (`uv sync`, `pytest`, demo smoke run)
- [ ] `data/` — provenanced benchmark profiles and panel curves

## Context

This SDK supports an **Electronics Engineering thesis** on MPPT algorithm
comparison. See [`PLAN.md`](./PLAN.md) for the full project plan, including
the contributor-liability statement, the policy on acknowledging LLM
usage, the viability / related-work analysis, and the requirement that
**each part of the SDK must work and be verified in isolation** before it
is integrated.

## On the use of AI

This project uses large language models (Claude, ChatGPT, Copilot) as
part of its day-to-day toolchain — and treats that usage as a deliberate
methodological choice rather than something to apologise for.

The thesis is being developed **without external funding**, by a
three-person team with limited weekly hours, in a research landscape
where comparable groups routinely operate with either dedicated funding
or AI-assisted workflows (or both). Refusing to use AI would not buy us
purity; it would simply widen the resource gap between this work and
the well-resourced groups it has to be benchmarked against. We use AI
for the same reason we use `pvlib` instead of re-implementing
single-diode physics: because the leverage is real and the alternative
is to do less science.

That choice comes with explicit guardrails — disclosure, human
verification of every change, citation of the underlying references,
and human authorship of all numerical results, experimental claims, and
conclusions. The full policy lives in [`PLAN.md`](./PLAN.md#use-of-large-language-models),
together with a per-layer exposure table that makes it easy to audit
where AI helped and where it didn't.

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

- **[De Soto et al. 2006]** De Soto, W., Klein, S. A., & Beckman, W. A.
  (2006). *Improvement and validation of a model for photovoltaic array
  performance.* Solar Energy, **80**(1), 78–88. (Single-diode model
  parameter extraction.)

### MPPT algorithm reviews and canonical methods

- **[Andriniriniaimalaza et al. 2025]** Andriniriniaimalaza, F. P., Murad,
  N. M., Balan, G., Bilal, H., Randriatefison, N., Khoodaruth, A.,
  Andrianirina, C. B., & Ravelo, B. (2025). *Hybrid Fuzzy Logic and
  Shading-Aware Particle Swarm Optimization for Dynamic Photovoltaic
  Shading Faults Mitigation.* arXiv. <https://doi.org/10.48550/arXiv.2512.08419>
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
- **[Kobayashi et al. 2006]** Kobayashi, K., Takano, I., & Sawada, Y.
  (2006). *A study of a two stage maximum power point tracking control of
  a photovoltaic system under partially shaded insolation conditions.*
  Solar Energy Materials and Solar Cells, **90**(18), 2975–2988.

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
