# mpp-sdk documentation

A Python SDK for designing, comparing, and deploying **Maximum Power Point
Tracking** (MPPT) algorithms for photovoltaic systems.

## Start here

- **[General Information](general_information.md)** — what the system is, the
  four SDK pillars, minimum PV theory, what pvlib contributes, and why the
  panels are wired in series.
- **[Rationale](rationale.md)** — the design decisions behind the project.
- **[Methodology](methodology.md)** — how the harnesses measure MPPT
  performance, what each metric means, the restart trigger policy, noise
  robustness, and the sim-to-real (PLECS / bench) comparison protocol.

## Algorithm references

One page each, with the equations and references:

- [Perturb & Observe](algorithms/perturb_observe.md) — classical hill-climbing baseline
- [Incremental Conductance](algorithms/incremental_conductance.md) — explicit at-the-MPP test
- [Fuzzy Logic](algorithms/fuzzy_logic.md) — graduated-step local tracker
- [Scan-and-Track](algorithms/scan_and_track.md) — global MPPT (scan + local refine)
- [Particle Swarm](algorithms/particle_swarm.md) — global MPPT (population search)

The first three are **local** trackers (they get trapped on local maxima under
partial shading); the last two are **global** methods that escape the trap.

---

Source and full roadmap: [github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk).
