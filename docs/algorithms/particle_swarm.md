---
title: "Particle Swarm Optimization (Global MPPT)"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

Particle Swarm Optimization is a population-based global search. A swarm of
candidate duty cycles ("particles") explores the operating range, each one
pulled toward its own best-seen point and the swarm's best-seen point. Because
the search is global, it finds the **global** MPP on a multi-modal (partially
shaded) P-V curve, where gradient methods get trapped.

## Particles

Particle $i$ has a position $x_i$ (a duty cycle), a velocity $v_i$, and a
personal-best position $p_i$ (the duty that gave it the most power so far). The
swarm shares the global-best position $g$ (best duty any particle has found).
The fitness of a position is the measured power $P = V\cdot I$ at that duty.

Particles are initialised **spread evenly** across $[D_\text{min}, D_\text{max}]$,
so the first pass doubles as a coarse scan that brackets the global peak's basin.

## Sequential evaluation

The rig can only test one duty at a time (one panel, one converter), so
particles are evaluated **one per control step**. A full PSO iteration therefore
takes $n_\text{particles}$ control steps: command each particle's duty, read its
power on the next step, update $p_i$ and $g$.

## Update rule

After every particle in an iteration has been evaluated, positions and
velocities are updated with the canonical PSO equations:

$$v_i \leftarrow w\,v_i + c_1 r_1\,(p_i - x_i) + c_2 r_2\,(g - x_i),$$
$$x_i \leftarrow \operatorname{clip}\big(x_i + v_i,\; D_\text{min},\, D_\text{max}\big),$$

where $r_1, r_2 \sim U(0,1)$ and:

- $w$ — **inertia**: how much previous velocity is retained (exploration).
- $c_1$ — **cognitive** weight: pull toward the particle's own best.
- $c_2$ — **social** weight: pull toward the swarm's global best.

Over successive iterations the particles contract around $g$, which converges to
the global MPP.

## Convergence and hand-off

After $M$ iterations (cost $\approx M\cdot n_\text{particles}$ steps) the swarm
has converged. Control is handed to a local `PerturbAndObserve` seeded at $g$,
which refines the operating point and keeps steady-state oscillation low — PSO
alone would keep jittering as particles never fully stop.

## Trade-offs

- **Swarm size / iterations:** larger ⇒ more reliable global capture but a
  longer, lossier search before lock-on.
- **vs. scan-and-track:** PSO can need fewer evaluations than a fine full scan
  on wide ranges, but it is stochastic (seed-dependent) and can still miss a
  very narrow peak with too few particles. Scan-and-track is deterministic.
- **MCU cost:** state is $\sim 4\,n_\text{particles}$ floats — small for modest
  swarms; the RNG and per-iteration update are cheap.

## Implementation

`mpp_sdk.ParticleSwarm(initial_duty, n_particles, inertia, cognitive, social,
max_iterations, track_step, seed, …)`. A fixed `seed` makes runs reproducible,
as required by the project's reproducibility policy.

## References

Kennedy & Eberhart (1995), *Particle swarm optimization*, ICNN. Miyatake et al.
(2011), *MPPT of multiple PV arrays: a PSO approach*, IEEE TAES. Liu et al.
(2012), *A PSO-based MPPT for PV under partial shading*, IEEE TEC.
