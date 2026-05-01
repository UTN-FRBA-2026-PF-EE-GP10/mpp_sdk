# AGENTS.md

Guidelines for AI coding agents (and humans) contributing to **mpp-sdk**.

## What this project is

`mpp-sdk` is a Python SDK for designing, comparing, and (eventually) deploying
Maximum Power Point Tracking (MPPT) algorithms for photovoltaic systems. The
roadmap is:

1. Build solar panel models of increasing fidelity — single-diode → losses →
   temperature/irradiance → measured curves.
2. Build a library of MPPT algorithms (P&O, InCond, fuzzy, ML, …) with a
   uniform interface.
3. Provide a hardware-abstraction seam so the same algorithm code can drive a
   simulation **or** a real boost converter on a Raspberry Pi 5 + a small
   intermediary microcontroller (Pi Pico / ESP32 under evaluation, talking
   SPI). The MCU drives the power stage and isolates it from the Pi; once an
   algorithm has been validated against the framework it is ported to the
   MCU itself, which is the project's headline deliverable.

## Architectural pillars

The codebase is organised around four orthogonal concerns. Keep them decoupled.

```
mpp_sdk/
├── models/         # Solar-panel I-V models           (PanelModel ABC)
├── converters/     # Power-stage models               (BoostConverter, …)
├── algorithms/     # MPPT controllers                 (MPPTAlgorithm ABC)
├── io/             # Hardware-abstraction layer       (SignalSource ABC)
└── visualization.py
```

Hard rules:

- **Algorithms never import models or converters.** They consume `(V, I)` from
  a `SignalSource` and emit a duty cycle. This is the seam that lets the same
  algorithm run in simulation and on a Raspberry Pi.
- **Models never know about converters or algorithms.** A `PanelModel` answers
  one question only: *given a terminal voltage (and my internal state), what
  current do I deliver?*
- **The simulator is the glue.** `SimulatedSource` composes a panel + converter
  + load behind a `SignalSource` so algorithms can be exercised offline.

## Modelling conventions

- **Control variable** is the boost-converter duty cycle, `D ∈ (D_min, D_max)`.
  MPPT algorithms in this SDK return `D`, never `V_ref` or `I_ref`.
- **Measured quantities** are panel terminal voltage `V` and panel output
  current `I` only. Algorithms must not consume irradiance, temperature, or
  model parameters directly — those exist in the *model*, not in the
  controller's state.
- **Richer models depend on more than (V, I).** A temperature-aware model has
  e.g. `model.temperature` and `model.irradiance` as mutable attributes; the
  simulation loop updates them over time. The `current(V)` interface stays
  uniform — environmental state lives on the model instance.
- **Boost-converter sign convention used in this repo:**
    - `V_out = V_in / (1 - D)`.
    - Increasing `D` ⇒ lower reflected resistance ⇒ **lower** panel terminal
      voltage.
    - When porting algorithms from papers that use `V_ref` as the control
      variable, **flip the sign** when translating to `D`.
- **Vectorisation:** model `current()` accepts arrays *and* scalars. Use
  `numpy.asarray` to broadcast.

## Roadmap of model fidelity

The model layer is split into two tracks: a small set of **in-tree,
pedagogical** models (the ideal single-diode and a single-diode with
losses), and a **pvlib-backed adapter** for everything beyond that.
The split is intentional: pvlib is the canonical Python implementation of
PV physics, well-validated and widely cited, and we should not reinvent it.

### In-tree (pedagogical, transparent)

These exist so a reader can step through the equations without leaving the
repo, and so the SDK installs and runs without optional dependencies.

1. **Ideal single-diode** — *shipped* in `models/ideal.py` as
   `IdealSingleDiode`. `I = I_ph − I_0·(exp(V / (n·V_t)) − 1)`. No losses,
   no temperature dependence; explicit closed-form `I(V)`.
2. **Single-diode with losses** — *planned* as `models/lossy.py` /
   `SingleDiodeWithLosses`. Adds series resistance `R_s` and shunt
   resistance `R_sh`. `I(V)` becomes implicit; solve with hand-rolled
   Newton-Raphson or bisection (the point is to *show* the solver, not to
   beat pvlib's).

### Via pvlib adapter (`models/pvlib_adapter.py`, optional dep)

Anything that needs validated PV physics — temperature / irradiance
dependence, two-diode / `bishop88` reverse-bias for partial-shading
analysis, parameter extraction from datasheets, or the CEC module
database — is implemented by wrapping pvlib behind a `PvlibPanelModel`
that subclasses `PanelModel`. Because the adapter satisfies the
`PanelModel` interface, the rest of the SDK (`SimulatedSource`,
algorithms, visualisation, `PanelArray`) consumes it identically.

When adding a new in-tree model, also add a smoke test that pins its MPP
at standard test conditions to within tolerance — and, where relevant,
cross-check against the pvlib adapter at the same operating point as a
sanity check on both implementations.

### Composition: arrays, bypass diodes, shading

This axis is **orthogonal** to single-module fidelity. A `PanelArray` is
itself a `PanelModel` and composes other `PanelModel`s in series and/or
parallel topologies (S, P, SP, TCT, BL); per-panel (or per-substring)
bypass diodes clamp negative voltages when the string current exceeds a
panel's photocurrent. Partial shading is modelled by setting different
per-panel irradiance / photocurrent.

Because a `PanelArray` *is* a `PanelModel`, the rest of the SDK
(`SimulatedSource`, algorithms, visualization) consumes it identically —
`current(V)`, `iv_curve()`, `mpp()` all just work, and the resulting I-V
curve naturally becomes multi-modal under non-uniform shading. That
multi-modal P-V is the motivation for the Global-MPPT family of
algorithms (PSO, scanning, hybrid) in the algorithm roadmap. A new array
or shading model should add a smoke test that pins the count and
approximate locations of the local maxima for a canonical shading
pattern.

## Roadmap of algorithms

- **Perturb & Observe** — *shipped*. Fixed-step P&O, sign-corrected for
  boost-converter duty-cycle control.
- **Incremental Conductance** — first variant beyond P&O.
- **Adaptive-step P&O / variable-step InCond** — improve speed/accuracy
  tradeoff.
- **Fuzzy / sliding-mode / model-predictive** — research-grade controllers.
- **Global MPPT** — particle-swarm, periodic full-range scan with local
  refinement, two-stage scan-and-track. These exist to escape the local
  maxima introduced by bypass diodes under partial shading; they are the
  algorithmic counterpart to the array / shading models above.
- **Data-driven** — neural / RL once measured curves are available.

All algorithms implement `MPPTAlgorithm.step(V, I) -> D` and own their internal
state.

## Coding conventions

- Python `>= 3.14`. Type hints on all public APIs.
- Subpackages re-export their main classes via `__init__.py`. The top-level
  `mpp_sdk/__init__.py` re-exports the most-used symbols.
- `numpy` is fine everywhere. `scipy` only when a hand-rolled bisection or
  Newton step is awkward.
- **Heavy / optional imports stay inside the function (or module) that needs
  them.** `matplotlib` lives inside the visualization functions; `pvlib`
  (when the adapter lands) lives inside `mpp_sdk/models/pvlib_adapter.py`;
  any hardware-only libraries (`spidev`, etc.) live inside the eventual
  `mpp_sdk/io/spi_mcu.py`. All of these are gated behind optional
  dependency groups in `pyproject.toml` (`mpp-sdk[pvlib]`,
  `mpp-sdk[hardware]`). Importing the SDK with the base install must not
  pull any of them.
- Comments only when the *why* is non-obvious. Don't restate the code. Public
  classes get a short docstring.
- **Algorithms must stay portable to a Pico-class MCU.** The thesis ends with
  the chosen algorithm running on a small microcontroller (Pi Pico / ESP32).
  When implementing an `MPPTAlgorithm`, keep its `step` method
  dependency-free (no `numpy` / `scipy` / `pandas` *inside the step*), keep
  its state small (a handful of scalars), and prefer fixed-step / branch-light
  variants. A Python implementation that quietly relies on `numpy`
  vectorisation will be painful to port; surface the dependency early and
  refactor before merging. Models, simulators, and visualisations are *not*
  bound by this constraint — they live on the Pi, only the algorithm leaves.
- Tests with `pytest` under `tests/` (not yet — add the directory when the
  second model lands so the regression infrastructure has something to anchor
  on).

## Hardware target (future)

The eventual platform is a **Raspberry Pi 5 + intermediary microcontroller**
topology, not a bare Pi.

- The Pi 5 hosts the SDK, the comparison harness, and (in HIL mode) the
  algorithm itself. It is *not* responsible for hard-real-time signals.
- A small MCU (candidates under evaluation: **Raspberry Pi Pico / RP2040** and
  **ESP32**) drives the power-electronics board: ADC sense for `(V, I)`,
  hardware PWM for the boost-converter switch, and SPI-slave to the Pi. The
  MCU isolates the fast-switching / high-current side from the Pi *and*
  doubles as the deployment target for the algorithm itself once it has been
  validated.

The hardware shim lands in two phases (see `PLAN.md` Phase 5):

1. **HIL bringup.** A Pi-side `SpiMcuSource(SignalSource)` under `mpp_sdk/io/`
   wraps the SPI protocol; the MCU firmware is a dumb I/O proxy (set duty,
   read sample, watchdog). The algorithm still lives on the Pi.
2. **Deployed mode.** The validated algorithm is ported from Python to MCU
   firmware (C with the Pi Pico SDK or ESP-IDF; MicroPython / CircuitPython
   for prototyping). The Pi is reduced to monitoring and configuration. The
   ported firmware is cross-validated against the Python reference
   point-by-point on recorded `(V, I, D)` traces.

The Pi-side source will:

- Live under `mpp_sdk/io/` as `SpiMcuSource(SignalSource)`.
- Be guarded by an optional dependency group (`mpp-sdk[hardware]`) so the SDK
  still installs cleanly on a development laptop.
- Expose calibration parameters (ADC scale / offset, sense-resistor value,
  PWM frequency, soft duty-cycle limits, SPI clock, watchdog timeout).

The MCU firmware itself lives in a sibling directory or repository per chip,
not under `mpp_sdk/`.

**Algorithms must not need any code changes** when switching from
`SimulatedSource` to `SpiMcuSource`, or when their Python implementation is
ported to MCU firmware. If a change to the algorithm API is required to
support either, that change belongs in the base class first.

## Process expectations for agents

- **Update `CHANGELOG.md` for every user-visible change.** Use Keep-a-Changelog
  format under `[Unreleased]`. The maintainer rolls versions.
- **Keep CHANGELOG entries compact.** Each entry describes *the state of the
  repo at that version*, not a transcript of every doc edit, refactor, or
  intermediate revision. Aim for a handful of bullets per release; collapse
  related changes into a single line. Before a release is tagged, prune
  `[Unreleased]` so it reads like a snapshot, not a session log — until we
  push, the changelog is editable and should be edited rather than appended
  to. The git log is the place for per-commit detail; the CHANGELOG is the
  place for *what's new since the last version*.
- **Read this file before making structural changes.** If a change conflicts
  with a pillar above, surface that explicitly in the PR description.
- **Prefer additive PRs.** Ship a new model alongside the old; deprecate
  before removing.
- **Demos are living documentation.** When you add a feature, add or update a
  demo that exercises it end-to-end with a plot. The canonical quickstart is
  `main.py`; variants and comparisons go under `examples/`. If you change a
  default, run the demo and verify the plot still tells the right story.
