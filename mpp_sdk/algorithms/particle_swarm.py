"""Particle Swarm Optimization (PSO) global MPPT for a SEPIC converter."""

import math
import random

from .base import MPPTAlgorithm
from .perturb_observe import PerturbAndObserve


class ParticleSwarm(MPPTAlgorithm):
    """Particle Swarm Optimization global MPPT (partial-shading capable).

    A small swarm of candidate duty cycles ("particles") searches the operating
    range for the global power peak. Because the rig evaluates one duty at a time
    (one panel, one converter), particles are evaluated **sequentially** — one
    per control step — so a full PSO iteration takes ``n_particles`` steps. After
    ``max_iterations`` the swarm has converged near the global MPP and control is
    handed to a local :class:`PerturbAndObserve` for low-ripple steady state.

    Each particle ``i`` keeps a position ``x_i`` (duty), velocity ``v_i``, and
    personal best ``p_i``. The swarm shares a global best ``g``. After every
    particle in an iteration has been evaluated, the standard update is applied:

        v_i ← w·v_i + c1·r1·(p_i − x_i) + c2·r2·(g − x_i)
        x_i ← clip(x_i + v_i,  D_min,  D_max)

    with ``r1, r2 ∼ U(0,1)``. Particles are initialised spread across the duty
    range, so the first iteration doubles as a coarse scan that locates the
    global peak's basin.

    State is ``~4·n_particles`` floats — tiny, MCU-friendly for small swarms.

    Parameters
    ----------
    initial_duty :
        Accepted only for interface uniformity with the local trackers. The swarm
        is seeded across the whole duty range, so the start point does not bias
        the search; it is merely the duty reported by ``duty`` before the first
        ``step``.
    n_particles :
        Swarm size. More ⇒ more reliable global search, longer per iteration.
    inertia, cognitive, social :
        PSO weights ``w``, ``c1``, ``c2``.
    max_iterations :
        Iterations before switching to local tracking.
    track_step :
        Step size of the P&O tracker used after convergence.
    seed :
        RNG seed for reproducible runs (PLAN requires fixed seeds).
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        n_particles: int = 5,
        inertia: float = 0.5,
        cognitive: float = 1.5,
        social: float = 1.5,
        max_iterations: int = 4,
        track_step: float = 0.005,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
        seed: int = 0,
    ) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if n_particles < 2:
            raise ValueError(f"n_particles must be >= 2; got {n_particles=}")
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1; got {max_iterations=}")
        self._min = min_duty
        self._max = max_duty
        self._w = inertia
        self._c1 = cognitive
        self._c2 = social
        self._max_iter = max_iterations
        self._track_step = track_step
        self._rng = random.Random(seed)

        # Particles spread evenly across the range → first pass is a coarse scan.
        span = max_duty - min_duty
        self._x = [min_duty + span * (k + 0.5) / n_particles for k in range(n_particles)]
        self._v = [0.0] * n_particles
        self._pbest_x = list(self._x)
        self._pbest_f = [-math.inf] * n_particles
        self._gbest_x = self._x[0]
        self._gbest_f = -math.inf

        self._optimizing = True
        self._tracker: PerturbAndObserve | None = None
        self._eval_idx = 0
        self._pending: int | None = None
        self._iteration = 0
        self._duty = self._x[0]

    def _update_swarm(self) -> None:
        for k in range(len(self._x)):
            r1 = self._rng.random()
            r2 = self._rng.random()
            self._v[k] = (
                self._w * self._v[k]
                + self._c1 * r1 * (self._pbest_x[k] - self._x[k])
                + self._c2 * r2 * (self._gbest_x - self._x[k])
            )
            self._x[k] = max(self._min, min(self._max, self._x[k] + self._v[k]))

    def step(self, voltage: float, current: float) -> float:
        if self._optimizing:
            # The measurement belongs to the previously commanded particle.
            if self._pending is not None:
                f = voltage * current
                k = self._pending
                if f > self._pbest_f[k]:
                    self._pbest_f[k] = f
                    self._pbest_x[k] = self._x[k]
                if f > self._gbest_f:
                    self._gbest_f = f
                    self._gbest_x = self._x[k]

            if self._eval_idx < len(self._x):
                d = self._x[self._eval_idx]
                self._pending = self._eval_idx
                self._eval_idx += 1
                self._duty = d
                return d

            # Iteration complete: move the swarm, or hand off to local tracking.
            self._iteration += 1
            if self._iteration >= self._max_iter:
                self._optimizing = False
                self._tracker = PerturbAndObserve(
                    initial_duty=self._gbest_x,
                    step_size=self._track_step,
                    min_duty=self._min,
                    max_duty=self._max,
                )
                self._duty = self._gbest_x
                return self._gbest_x

            self._update_swarm()
            self._eval_idx = 0
            d = self._x[self._eval_idx]
            self._pending = self._eval_idx
            self._eval_idx += 1
            self._duty = d
            return d

        self._duty = self._tracker.step(voltage, current)
        return self._duty

    @property
    def duty(self) -> float:
        return self._duty

    @property
    def optimizing(self) -> bool:
        return self._optimizing
