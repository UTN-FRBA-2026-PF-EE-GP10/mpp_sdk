# AGENTS.md

Guidelines for AI coding agents (and humans) contributing to **mpp-sdk**.
Read this before any structural change.

## What this project is

`mpp-sdk` is a Python SDK for designing, comparing, and (eventually) deploying
Maximum Power Point Tracking (MPPT) algorithms for photovoltaic systems. The
same controller code runs in simulation today and on a real **SEPIC** converter
tomorrow, driven by a **Raspberry Pi 5 + RP2040 (Pi Pico)** over SPI. The
RP2040 (firmware in **Rust**) drives the power stage and is the final deployment
target for the chosen algorithm — the thesis's headline deliverable.

For the why behind the design, see `docs/rationale.md`; for the system overview
and PV theory, `docs/general_information.md`; for the roadmap, `PLAN.md`.

## Architectural pillars

Four orthogonal concerns. Keep them decoupled.

```text
mpp_sdk/
├── models/         # Solar-panel I-V models   (PanelModel ABC)
├── converters/     # Power-stage models       (SEPICConverter)
├── algorithms/     # MPPT controllers         (MPPTAlgorithm ABC)
├── io/             # Hardware-abstraction     (SignalSource ABC)
├── metrics.py      # Comparison metrics
└── visualization.py
```

Hard rules:

- **Algorithms never import models or converters.** They consume `(V, I)` from a
  `SignalSource` and emit a duty cycle `D`. This seam is what lets the same
  algorithm run in simulation and on hardware.
- **Models never know about converters or algorithms.** A `PanelModel` answers
  one question: *given a terminal voltage (and my internal state), what current
  do I deliver?*
- **The source is the glue.** `SimulatedSource` / `DynamicSimulatedSource`
  compose panel + converter + load behind a `SignalSource` so algorithms run
  offline.

## Modelling conventions

- **Control variable** is the converter duty cycle `D ∈ (D_min, D_max)`.
  Algorithms return `D`, never `V_ref` or `I_ref`.
- **Measured quantities** are panel terminal voltage `V` and current `I` only.
  Algorithms must not read irradiance, temperature, or model parameters — those
  live on the *model* (e.g. mutable `model.irradiance`, `model.temperature`),
  updated by the simulation loop. The `current(V)` interface stays uniform.
- **SEPIC sign convention:** `V_out = V_in · D/(1−D)`; reflected resistance
  `R_in = R_load · ((1−D)/D)²`, decreasing in `D`. So **raising `D` lowers the
  panel voltage** (same sign as a boost). Porting an algorithm written in terms
  of `V_ref`? Flip the sign when mapping to `D`.
- **Vectorisation:** model `current()` accepts arrays *and* scalars
  (`numpy.asarray`).

## Models (`mpp_sdk/models/`)

In-tree, pedagogical (no optional deps):

- `IdealSingleDiode` — shipped. Explicit closed-form `I(V)`, no losses/temp.
- `SingleDiodeWithLosses` — *planned*. Adds `R_s`/`R_sh`; implicit `I(V)` solved
  with a hand-rolled Newton/bisection (the point is to *show* the solver).

Via the pvlib adapter (optional `mpp-sdk[pvlib]`):

- `PvlibPanelModel` — shipped. Wraps pvlib's De Soto single-diode behind
  `PanelModel`; temperature/irradiance aware. `from_datasheet(...)` fits
  parameters; `hissuma_psf10mono(...)` is the project's panel.

Composition and helpers:

- `PvString` — shipped. N panels in series with bypass diodes; per-panel
  irradiance gives a multi-modal P-V curve (the motivation for global MPPT).
- `TabulatedPanel` — shipped. Caches any model's I-V curve onto a grid for fast
  repeated lookups (makes the dynamic/animated harness tractable).

A new model ships with a smoke test pinning its MPP (and, for arrays, the count
/ location of local maxima) at known conditions.

## Algorithms (`mpp_sdk/algorithms/`)

All implement `MPPTAlgorithm.step(V, I) -> D` and own their state.

- `PerturbAndObserve`, `IncrementalConductance`, `FuzzyLogic` — local trackers.
- `ScanAndTrack`, `ParticleSwarm` — global MPPT (escape local maxima under
  partial shading).
- *Planned:* adaptive-step P&O; an own model-informed candidate scan; later, a
  data-driven baseline.

**Algorithms must stay portable to a Pico-class MCU.** Keep `step` dependency-free
(no numpy/scipy/pandas inside it), state small (a handful of scalars), and prefer
fixed-step / branch-light variants. Models, sources, harness, and visualisation
live on the Pi and are *not* bound by this — only the algorithm leaves.

## Coding conventions

- Python `>= 3.14`. Type hints on public APIs.
- Subpackages re-export their main classes; the top-level `__init__.py`
  re-exports the most-used symbols.
- `numpy` everywhere; `scipy` only when a hand-rolled solver is awkward.
- **Heavy / optional imports stay inside the function or module that needs them**
  (`matplotlib` in visualisation, `pvlib` in the adapter, `spidev` in
  `io/spi_mcu.py`), gated behind optional groups (`mpp-sdk[pvlib]`,
  `mpp-sdk[hardware]`). The base install must not pull any of them.
- Comments only when the *why* is non-obvious. Public classes get a docstring.
- Tests with `pytest` under `tests/` — one per module, exercising the public API
  in isolation; pvlib-dependent tests `importorskip` it.

## Hardware target (future)

**Raspberry Pi 5 + RP2040.** The Pi 5 hosts the SDK, harness, and (in HIL mode)
the algorithm; it is not responsible for hard-real-time signals. The RP2040
(firmware in **Rust**, `rp2040-hal`) drives the board: ADC sense for `(V, I)`,
hardware PWM for the SEPIC switch, SPI-slave to the Pi. It isolates the
fast-switching side *and* is the deployment target.

Two phases (see `PLAN.md` Phase 5):

1. **HIL bringup.** A Pi-side `SpiMcuSource(SignalSource)` (under `mpp_sdk/io/`,
   gated by `mpp-sdk[hardware]`) wraps the SPI protocol; the firmware is a dumb
   I/O proxy. The algorithm still lives on the Pi.
2. **Deployed mode.** The validated algorithm is ported to RP2040 firmware and
   cross-validated against the Python reference on recorded `(V, I, D)` traces.

MCU firmware lives in a sibling directory/repo, not under `mpp_sdk/`.
**Switching `SimulatedSource` → `SpiMcuSource`, or porting an algorithm to
firmware, must need no algorithm code changes.** If it does, fix the base class
first.

## What not to commit

This repo is public. Keep out of the tree, commit messages, and docs:

- **Credentials of any kind** (keys, tokens, passwords, Wi-Fi creds in firmware).
- **Personal / institutional metadata** (lab network paths, internal hostnames,
  GPS of test sites, serial numbers tied to a location). Use a no-reply commit
  email.
- **Embedded binary metadata** — strip EXIF/GPS from photos
  (`exiftool -all=`) and serials/IPs from scope captures.
- **Datasheets / third-party schematics / proprietary panel models** not
  licensed for redistribution — cite by reference.
- **Raw measurement files** with unscrubbed location/serial metadata. Measured
  data lives under `data/` with a `data/README.md` documenting the scrub.

`.gitignore` covers the obvious patterns; grep the staged diff for `API_KEY`,
`password`, `token`, `secret` before committing. If a secret lands in history,
rotate it, then rewrite history with `git filter-repo` and force-push.

## Process expectations

- **Read this file before structural changes.** If a change conflicts with a
  pillar above, surface it explicitly.
- **Prefer additive changes.** Ship a new model/algorithm alongside the old;
  deprecate before removing.
- **Demos and the harness are living documentation.** When you add an algorithm,
  add it to the comparison harness (`harness/`) and, where useful, a demo under
  `examples/`. The canonical quickstart is `main.py`.
