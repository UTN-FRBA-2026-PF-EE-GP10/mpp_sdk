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

## Restart on shading change

Once handed off, the controller is a plain P&O and cannot escape a local
maximum when the shading pattern changes. A `PowerChangeDetector` (on by
default) watches $P = V\,I$ during tracking: a sustained relative change
beyond `restart_threshold` re-seeds the particles evenly across the duty
range — stale personal/global bests are forgotten, not reused — and re-runs
the whole search. This is the $|\Delta P|/P$ restart condition from the
PSO-MPPT literature [Liu et al. 2012]. The detector arms only once the power
is stable after hand-off, so the converter's own settling transient cannot
trigger a restart loop.

The detector is blind to one case: a shading change that relocates the
global peak while barely moving the tracked power (e.g. the shade swapping
from one panel to the other). The optional `rescan_period` re-runs the
search every $N$ tracking steps as a backstop, at the price of the search's
energy cost each period — the same knob `ScanAndTrack` has. See
`restart_policy.md` for the derivation behind the deployed period.

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
max_iterations, track_step, seed, restart_threshold, restart_samples,
rescan_period, …)`. A fixed `seed` makes runs reproducible, as required by
the project's reproducibility policy.

Swarm size matters more than it looks on a real (or dynamic-simulated) rig:
each particle's fitness is measured one control period after commanding it,
while the input capacitor is still slewing, so the first (coarse-scan)
iteration sees lag-corrupted powers. On the 2-panel Hissuma rig at a 1 kHz
loop, 6 particles locate the global basin for only ~60 % of seeds after a
shading change; 8 particles are reliable.

Because the swarm's convergence depends on the RNG stream, `harness/compare_seeds.py`
runs PSO (8 particles) over 30 seeds on the cyclic schedule: eta energy
93.9 % +/- 0.7 and 7.9 +/- 1.7 trapped plateaus, against the deterministic
Scan&Track at 95.0 % eta and 5 traps with zero variance. Scan&Track beats
PSO's mean on both metrics with no seed dependence, which makes it the
stronger MCU deployment candidate.

## References

Kennedy & Eberhart (1995), *Particle swarm optimization*, ICNN. Miyatake et al.
(2011), *MPPT of multiple PV arrays: a PSO approach*, IEEE TAES. Liu et al.
(2012), *A PSO-based MPPT for PV under partial shading*, IEEE TEC. Dolara et al.
(2018), *An Evolutionary-Based MPPT Algorithm for Photovoltaic Systems under
Dynamic Partial Shading*, Applied Sciences.
