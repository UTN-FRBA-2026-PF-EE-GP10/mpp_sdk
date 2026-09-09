# AGENTS.md

Guidelines for AI coding agents (and humans) contributing to **mpp-sdk**.
Read this before any structural change.

## What this project is

`mpp-sdk` is a Python SDK for MPPT (Maximum Power Point Tracking) algorithms
for photovoltaic systems. The same controller code runs in simulation today.
It will run on a real **SEPIC** converter later, driven by a **Raspberry Pi
5 and an RP2040 (Pi Pico)** over SPI. The RP2040 (firmware in **Rust**)
drives the power stage. It is the final deployment target for the chosen
algorithm — the thesis's headline deliverable.

See `docs/rationale.md` for the design reasoning, `docs/general_information.md`
for the system overview and PV theory, and `PLAN.md` for the roadmap.

## Architectural pillars

Four separate concerns. Keep them decoupled.

```text
mpp_sdk/
├── models/         # Solar-panel I-V models   (PanelModel ABC)
├── converters/     # Power-stage models       (SEPICConverter)
├── algorithms/     # MPPT controllers         (MPPTAlgorithm ABC)
├── io/             # Hardware-abstraction     (SignalSource ABC)
├── curves/         # Captured I-V curve library (CurveRecord, feeds MeasuredPanel)
├── metrics.py      # Comparison metrics
└── visualization.py
```

Hard rules:

- **Algorithms never import models or converters.** They read `(V, I)` from a
  `SignalSource` and return a duty cycle `D`. This seam lets the same
  algorithm run in simulation and on hardware, unchanged.
- **Models never know about converters or algorithms.** A `PanelModel`
  answers one question: given a terminal voltage (and its own state), what
  current does it deliver?
- **The source is the glue.** `SimulatedSource` / `DynamicSimulatedSource`
  combine a panel, a converter, and a load behind a `SignalSource`. This lets
  algorithms run offline.

## Modelling conventions

- **Control variable**: the converter duty cycle `D ∈ (D_min, D_max)`.
  Algorithms return `D`, never `V_ref` or `I_ref`.
- **Measured quantities**: panel terminal voltage `V` and current `I` only.
  Algorithms must not read irradiance, temperature, or model parameters.
  Those live on the *model* (e.g. mutable `model.irradiance`,
  `model.temperature`), updated by the simulation loop. The `current(V)`
  interface stays the same either way.
- **SEPIC sign convention**: `V_out = V_in · D/(1−D)`; reflected resistance
  `R_in = R_load · ((1−D)/D)²`, which falls as `D` rises. So **raising `D`
  lowers the panel voltage** (same sign as a boost converter). Porting an
  algorithm written in terms of `V_ref`? Flip the sign when you map it to `D`.
- **Vectorisation**: model `current()` accepts arrays and scalars
  (`numpy.asarray`).

## Models (`mpp_sdk/models/`)

In-tree, no optional deps:

- `IdealSingleDiode` — shipped. Explicit closed-form `I(V)`, no losses or
  temperature effects.
- `SingleDiodeWithLosses` — *planned*. Adds `R_s`/`R_sh`; solves the implicit
  `I(V)` with a hand-rolled Newton/bisection method, to show the solver.

Via the pvlib adapter (optional `mpp-sdk[pvlib]`):

- `PvlibPanelModel` — shipped. Wraps pvlib's De Soto single-diode model
  behind `PanelModel`; aware of temperature and irradiance.
  `from_datasheet(...)` fits parameters; `hissuma_psf10mono(...)` is this
  project's panel.

Composition and helpers:

- `PvString` — shipped. N panels in series with bypass diodes. Per-panel
  irradiance gives a multi-modal P-V curve — the reason global MPPT exists.
- `TabulatedPanel` — shipped. Caches any model's I-V curve on a grid for fast
  repeated lookups. Makes the dynamic/animated harness fast enough to use.
- `MeasuredPanel` — shipped. Wraps a captured I-V sweep
  (`mpp_sdk.curves.CurveRecord`) as a `PanelModel`, so a real curve runs
  through the same comparison harness as any synthetic model.

A new model ships with a smoke test that pins its MPP (and, for arrays, the
count and location of local maxima) at known conditions.

## Algorithms (`mpp_sdk/algorithms/`)

All implement `MPPTAlgorithm.step(V, I) -> D` and own their state.

- `PerturbAndObserve`, `IncrementalConductance`, `FuzzyLogic` — local
  trackers.
- `ScanAndTrack`, `ParticleSwarm` — global MPPT. They escape local maxima
  under partial shading.
- *Planned*: adaptive-step P&O; a model-informed candidate scan; later, a
  data-driven baseline.

**Algorithms must stay portable to a Pico-class MCU.** Keep `step`
dependency-free (no numpy/scipy/pandas inside it). Keep state small — a
handful of scalars. Prefer fixed-step, branch-light variants. Models,
sources, the harness, and visualisation live on the Pi and are not bound by
this rule — only the algorithm leaves the Pi.

## Coding conventions

- Python `>= 3.14`. Type hints on public APIs.
- Subpackages re-export their main classes. The top-level `__init__.py`
  re-exports the most-used symbols.
- `numpy` everywhere. Use `scipy` only when a hand-rolled solver would be
  awkward.
- **Heavy or optional imports stay inside the function or module that needs
  them** (`matplotlib` in visualisation, `pvlib` in the adapter, `spidev` in
  `io/spi_mcu.py`, `fastapi`/`uvicorn` in the curve-tracer server). Gate them
  behind optional groups (`mpp-sdk[pvlib]`, `mpp-sdk[hardware]`,
  `mpp-sdk[web]`). The base install must not need any of them.
- Comments explain *why*, only when the why is not obvious. Public classes
  get a docstring.
- Tests use `pytest`, under `tests/` — one file per module, exercising the
  public API in isolation. pvlib-dependent tests call `importorskip` first.

## Hardware target (future)

**Raspberry Pi 5 and RP2040.** The Pi 5 hosts the SDK, the harness, and (in
HIL mode) the algorithm. It is not responsible for hard-real-time signals.
The RP2040 (firmware in **Rust**, `rp2040-hal`) drives the board: ADC sense
for `(V, I)`, hardware PWM for the SEPIC switch, SPI-slave to the Pi. It
isolates the fast-switching side and is also the deployment target. See
`firmware/pipico_board/README.md` for build, flash, and calibration steps.

Two phases (see `PLAN.md`, Phase 5):

1. **HIL bringup.** A Pi-side `SpiMcuSource(SignalSource)` (under
   `mpp_sdk/io/`, gated by `mpp-sdk[hardware]`) wraps the SPI protocol. The
   firmware is a dumb I/O proxy. The algorithm still runs on the Pi.
2. **Deployed mode.** The validated algorithm is ported to RP2040 firmware
   and cross-checked against the Python reference, on recorded `(V, I, D)`
   traces.

MCU firmware lives in a sibling directory, not under `mpp_sdk/`.
**Switching `SimulatedSource` to `SpiMcuSource`, or porting an algorithm to
firmware, must need no algorithm code changes.** If it does, fix the base
class first.

## What not to commit

This repo is public. Keep these out of the tree, commit messages, and docs:

- **Credentials of any kind** — keys, tokens, passwords, Wi-Fi credentials in
  firmware.
- **Personal or institutional metadata** — lab network paths, internal
  hostnames, GPS of test sites, serial numbers tied to a location. Use a
  no-reply commit email.
- **Embedded binary metadata** — strip EXIF/GPS from photos
  (`exiftool -all=`) and serials/IPs from scope captures.
- **Datasheets, third-party schematics, or proprietary panel models** not
  licensed for redistribution. Cite them by reference instead.
- **Raw measurement files** with unscrubbed location or serial metadata.
  Measured data lives under `data/`, with a `data/README.md` that documents
  the scrub.
- **Internal session identifiers** — e.g. an AI-tool session URL. It has no
  reason to be public and reveals nothing useful to a reader.

`.gitignore` covers the obvious patterns. Before committing, grep the staged
diff for `API_KEY`, `password`, `token`, `secret`. If a secret lands in
history, rotate it, then rewrite history with `git filter-repo` and
force-push.

## Process expectations

- **Read this file before structural changes.** If a change conflicts with a
  pillar above, say so explicitly.
- **Prefer additive changes.** Ship a new model or algorithm alongside the
  old one. Deprecate before removing.
- **Demos and the harness are living documentation.** When you add an
  algorithm, add it to the comparison harness (`harness/`) and, where
  useful, a demo under `examples/`. The canonical quickstart is `main.py`.

### Definition of done for a new module

1. Unit tests under `tests/` — public API in isolation.
2. Demo script under `examples/` (or a harness entry) that produces one plot.
3. Integration in the comparison harness.
