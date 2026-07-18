"""Measurement-noise wrapper around any ``SignalSource``."""

import math
import random

from .base import SignalSource


class NoisySource(SignalSource):
    """Adds Gaussian measurement noise to another source's ``(V, I)`` readings.

    Real ADC front ends are not clean: thermal noise, quantization and
    reference ripple put a noise floor on every sample. Wrapping a source
    keeps that imperfection where it belongs - in the measurement chain -
    so neither the algorithms nor the plant models grow noise flags, and
    the same wrapper will later sanity-check the bench against the noise
    level the harness was validated at.

    Noise is specified as *absolute* standard deviations in volts and
    amperes, matching how an acquisition chain is specified (e.g. an
    effective noise of 0.4 V on a 40 V range is 1 % of full scale).
    Readings are *not* clamped: a real ADC reads slightly negative around
    zero, and controllers must cope with that.

    The duty path (``write``) is passed through untouched - PWM generation
    is digital and effectively exact compared to the sense path.

    Parameters
    ----------
    source :
        The wrapped ``SignalSource``; also reachable as ``.source`` (the
        harness uses that to drive ``set_panel`` on a simulated inner
        source).
    v_std, i_std :
        Standard deviation of the additive Gaussian noise on voltage [V]
        and current [A]. Zero disables that channel's noise.
    seed :
        RNG seed for reproducible runs (PLAN requires fixed seeds).
    """

    def __init__(
        self,
        source: SignalSource,
        v_std: float = 0.0,
        i_std: float = 0.0,
        seed: int = 0,
    ) -> None:
        if not (math.isfinite(v_std) and v_std >= 0.0):
            raise ValueError(f"v_std must be a finite non-negative number; got {v_std=}")
        if not (math.isfinite(i_std) and i_std >= 0.0):
            raise ValueError(f"i_std must be a finite non-negative number; got {i_std=}")
        self._source = source
        self._v_std = v_std
        self._i_std = i_std
        self._rng = random.Random(seed)

    @property
    def source(self) -> SignalSource:
        """The wrapped source (e.g. to call ``set_panel`` on a simulated one)."""
        return self._source

    def read(self) -> tuple[float, float]:
        v, i = self._source.read()
        if self._v_std > 0.0:
            v += self._rng.gauss(0.0, self._v_std)
        if self._i_std > 0.0:
            i += self._rng.gauss(0.0, self._i_std)
        return v, i

    def write(self, duty_cycle: float) -> None:
        self._source.write(duty_cycle)

    @property
    def duty(self) -> float:
        return self._source.duty
