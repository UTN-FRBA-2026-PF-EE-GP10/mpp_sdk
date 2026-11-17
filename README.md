<div align="center">

# mpp-sdk

[![Hardware preview](https://img.shields.io/badge/hardware-open%20in%20KiCanvas-2b6cb0?logo=kicad&logoColor=white)](https://kicanvas.org/?github=https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/tree/main/hardware)

</div>

A Python SDK for designing, comparing, and deploying **Maximum Power Point
Tracking** (MPPT) algorithms for photovoltaic systems. Built around a clean
hardware-abstraction seam so the same controller code drives a simulation
today and a real SEPIC converter on a Host/sbc tomorrow.

See [`AGENTS.md`](./AGENTS.md) for architectural pillars and contribution
guidelines. Open work is tracked in the
[project tracker issue](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/issues/128).

## Why

pvlib gives panel physics but no shared **control** library. Most MPPT
comparison work uses MATLAB or Simulink code that is rarely released.
`mpp-sdk` adds:

1. **One interface.** `MPPTAlgorithm.step(V, I) -> D`. A new controller is
   a one-file PR.
2. **A hardware seam.** `SignalSource` lets the same algorithm run on a
   `SimulatedSource` or on a real board, with no branches.
3. **An MCU deployment target.** A Raspberry Pi Pico (RP2040) drives the
   power stage and talks to the Host/sbc over SPI. A validated algorithm is
   ported to the Pico and re-run on the same rig.
4. **A reproducible harness.** Dynamic irradiance profiles, shared metrics
   and figures regenerated from code.

The thesis deliverable is an MCU-deployable algorithm that fits a Pico-class
chip and competes with classical methods. That limit favors fixed-step,
minimal-state methods. See [`docs/rationale.md`](docs/rationale.md) and
[`docs/general_information.md`](docs/general_information.md).

## Installation

Once published to PyPI, install with `uv` (recommended) or `pip`:

```bash
# Core library - panel models, SEPIC converter, P&O, SimulatedSource
uv add mpp-sdk

# With high-fidelity pvlib panel models (PvlibPanelModel adapter)
uv add "mpp-sdk[pvlib]"

# With SPI hardware dependencies (SpiMcuSource)
uv add "mpp-sdk[hardware]"

# With the curve-tracer FastAPI web backend (mpp-sdk curve-tracer-web)
uv add "mpp-sdk[web]"

# Everything at once
uv add "mpp-sdk[all]"
```

Then import from your project:

```python
import mpp_sdk

panel = mpp_sdk.IdealSingleDiode()
conv  = mpp_sdk.SEPICConverter()
src   = mpp_sdk.SimulatedSource(panel, conv, load_resistance=10.0)
ctl   = mpp_sdk.PerturbAndObserve(initial_duty=src.duty, min_duty=0.1, max_duty=0.9)

for _ in range(500):
    v, i = src.read()
    src.write(ctl.step(v, i))
```

## Quickstart (development)

Clone the repo and run the live demo directly:

```bash
git clone https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk.git
cd mpp_sdk
uv sync
uv run main.py
```

This runs Perturb & Observe MPPT against the ideal single-diode panel model
and plots the I-V / P-V curves with the calculated MPP and the algorithm's
operating-point trajectory.

Every other runnable script under `harness/`, `examples/`, and `scripts/`
is also reachable through one dispatcher, `mpp-sdk`
(`examples/pno_demo.py` is a thin shim to this same `main.py` quickstart,
so it is not a separate entry):

```bash
uv run mpp-sdk --help              # list every runnable script
uv run mpp-sdk compare-dynamic     # run harness/compare_dynamic.py
uv run mpp-sdk animate --shade     # forwards extra flags to the target script
```

Each script also stays directly runnable on its own (e.g.
`uv run harness/compare_dynamic.py`) - `mpp-sdk` is just a single place to
discover them all.

### Curve-tracer web workbench

A React frontend + FastAPI backend for capturing, browsing, and replaying
real panel I-V curves - see [`frontend/README.md`](frontend/README.md) for
the full picture. Try it with no hardware at all:

```bash
uv sync --extra web
uv run mpp-sdk curve-tracer-web --demo
# open http://localhost:8000/
```

Drop `--demo` (and add `--extra hardware`) once a Raspberry Pi + RP2040
board is wired up per
[`firmware/pipico_board/README.md`](firmware/pipico_board/README.md).

### Closed-loop runs

`mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check`
sweeps a ground-truth I-V curve, then runs a registered algorithm against
the live board for a while, recording `(t, V, I, D)`. Plot it with
`mpp-sdk plot-run`. Needs real hardware (`--extra hardware`).

## Layout

```text
mpp_sdk/
├── models/         # Solar panel I-V models  (PanelModel ABC; ideal, pvlib, string, tabulated, measured)
├── converters/     # Power-stage models      (SEPICConverter)
├── algorithms/     # MPPT controllers        (MPPTAlgorithm ABC; P&O, InCond, fuzzy, scan, PSO)
├── io/             # Hardware-abstraction    (SignalSource ABC; simulated, dynamic, noisy, SPI to the Pico)
├── curves/         # Captured I-V curve library (CurveRecord, feeds MeasuredPanel)
├── runs/           # Captured closed-loop runs (RunRecord)
├── sessions/       # Bench session checklists and their templates
├── panels/         # Panel model library (label values)
├── metrics.py      # Comparison metrics
└── visualization.py

harness/            # Comparison scripts (static, dynamic, live, cyclic ranking, sim-to-real bank)
scripts/            # Bench tools and the workbench server (FastAPI)
frontend/           # Workbench UI (React); its build is committed to scripts/curve_tracer_web/
firmware/           # RP2040 firmware (Rust) and its host-tested safety-checks crate
hardware/           # KiCad board
  dimmer/           # Lamp dimmer board (see hardware/dimmer/README.md)
data/               # Bench data (see data/README.md)
docs/               # Algorithm references, rationale, procedures
```

The control variable is always the SEPIC **duty cycle**. The measured
quantities are always panel terminal **voltage** and **current**. Richer
panel models may depend on temperature, irradiance, or a measured curve,
but those inputs live on the *model* - the controller never sees them.

## Where mpp-sdk sits relative to pvlib

`mpp-sdk` is complementary to [`pvlib-python`](https://pvlib-python.readthedocs.io/),
not a replacement:

- pvlib owns solar resource, irradiance and panel I-V physics. It returns
  the MPP. It has no closed-loop controllers.
- `mpp-sdk` owns the MPPT controllers, the SEPIC model, the `SignalSource`
  seam and the comparison harness.
- `PvlibPanelModel` puts any pvlib model behind the same pipeline.

## Status

- **Shipped:** panel models (ideal, pvlib, string, measured), five
  algorithms, the comparison harness, the curve tracer, the web
  workbench, and the Pi + Pico firmware.
- **On hardware:** curves are good. Closed-loop runs work for P&O. The
  other algorithms need a slower, settled control loop first.
- **Open:** a valid hardware comparison, the algorithm port to the Pico,
  and the thesis figures.

Open work is tracked in the [project tracker issue](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/issues/128).

## Context

This SDK supports an **Electronics Engineering thesis** on MPPT algorithm
comparison. One hard rule applies: **each part of the SDK must work and be
verified in isolation** before it is integrated (see
[`AGENTS.md`](./AGENTS.md), "Definition of done").

The MIT license (see [`LICENSE`](./LICENSE)) covers redistribution. It is
not a warranty: whoever wires this code to real hardware is responsible
for electrical safety and for checking the code against their own
measurements.

## On the use of AI

The project uses LLMs (Claude, ChatGPT, Copilot) as a deliberate choice.
The thesis has no external funding and the team has limited hours. Rules:

- **Disclose.** The thesis names the LLMs and the tasks.
- **Verify.** A person reads and tests every LLM-assisted change.
- **Cite.** A reproduced algorithm or formula cites its primary source.
- **Author.** A person authors and owns every commit.
- **Off-limits.** Numerical results, measured data, claims and conclusions
  are written and checked by the authors.

## References

Working set of cited sources.

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
  performance.* Solar Energy, **80**(1), 78-88. (Single-diode model
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
  **4**(1), 89-98.
- **[Hussein et al. 1995]** Hussein, K. H., Muta, I., Hoshino, T., &
  Osakada, M. (1995). *Maximum photovoltaic power tracking: an
  algorithm for rapidly changing atmospheric conditions.* IEE
  Proceedings - Generation, Transmission and Distribution, **142**(1),
  59-64. (Incremental Conductance reference implementation.)
- **[Femia et al. 2005]** Femia, N., Petrone, G., Spagnuolo, G., &
  Vitelli, M. (2005). *Optimization of perturb and observe maximum
  power point tracking method.* IEEE Transactions on Power Electronics,
  **20**(4), 963-973. (P&O step-size design.)
- **[Kobayashi et al. 2006]** Kobayashi, K., Takano, I., & Sawada, Y.
  (2006). *A study of a two stage maximum power point tracking control of
  a photovoltaic system under partially shaded insolation conditions.*
  Solar Energy Materials and Solar Cells, **90**(18), 2975-2988.

### Partial shading and Global MPPT

- **[Patel & Agarwal 2008]** Patel, H., & Agarwal, V. (2008). *Maximum
  power point tracking scheme for PV systems operating under partially
  shaded conditions.* IEEE Transactions on Industrial Electronics,
  **55**(4), 1689-1698.
- **[Miyatake et al. 2011]** Miyatake, M., Veerachary, M., Toriumi, F.,
  Fujii, N., & Ko, H. (2011). *Maximum power point tracking of multiple
  photovoltaic arrays: a PSO approach.* IEEE Transactions on Aerospace
  and Electronic Systems, **47**(1), 367-380.
- **[Liu et al. 2012]** Liu, Y.-H., Huang, S.-C., Huang, J.-W., & Liang,
  W.-C. (2012). *A particle swarm optimization-based maximum power
  point tracking algorithm for PV systems operating under partially
  shaded conditions.* IEEE Transactions on Energy Conversion, **27**(4),
  1027-1035.

### Standards and benchmarking

- **[EN 50530]** CENELEC EN 50530:2010+A1:2013. *Overall efficiency of
  grid connected photovoltaic inverters.* (Defines the MPPT
  static- and dynamic-efficiency test profiles used as the comparison
  harness target.)
