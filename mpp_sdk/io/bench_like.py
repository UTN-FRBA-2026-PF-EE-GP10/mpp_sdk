"""Bench-like measurement wrapper around any ``SignalSource``."""

import math

from .base import SignalSource


class BenchLikeSource(SignalSource):
    """Makes a source behave like the bench measurement chain.

    The wrapped source gives the steady-state ``(V, I)`` for a duty. This
    wrapper adds three bench effects, so the harness can reproduce what the
    algorithms see on hardware:

    - lag: V and I move toward the new operating point with a first-order
      time constant ``settle_tau_s`` (the converter settling time);
    - sample-and-hold: the power monitor gives a new pair only every
      ``sample_period_s``; between samples the last pair is held;
    - quantisation: the held pair is rounded to ``v_step`` and ``i_step``
      (the firmware reports whole mV and mA).

    The clock is simulated. Each ``write()`` is one SPI exchange and advances
    time by ``exchange_period_s``; ``read()`` does not advance it. There is no
    sleep and no wall clock, so runs are deterministic.

    Parameters
    ----------
    source :
        The wrapped source, also reachable as ``.source``. Its ``read()`` after
        a write is used as the target of the lag. Do not wrap a source that
        already has its own slow dynamics unless you want both.
    sample_period_s :
        Time between new measurements [s].
    v_step, i_step :
        Quantisation steps for V [V] and I [A]. Zero disables rounding.
    settle_tau_s :
        Lag time constant [s]. Zero means no lag.
    exchange_period_s :
        Simulated time per exchange [s]; 1/1000 is 1000 decisions per second.
    """

    def __init__(
        self,
        source: SignalSource,
        sample_period_s: float = 2e-3,
        v_step: float = 1e-3,
        i_step: float = 1e-3,
        settle_tau_s: float = 10e-3,
        exchange_period_s: float = 1e-3,
    ) -> None:
        for name, value, positive in (
            ("sample_period_s", sample_period_s, True),
            ("exchange_period_s", exchange_period_s, True),
            ("settle_tau_s", settle_tau_s, False),
            ("v_step", v_step, False),
            ("i_step", i_step, False),
        ):
            if not math.isfinite(value) or value < 0.0 or (positive and value == 0.0):
                raise ValueError(f"{name} out of range; got {value!r}")
        self._source = source
        self._sample_period = sample_period_s
        self._v_step = v_step
        self._i_step = i_step
        self._tau = settle_tau_s
        self._dt = exchange_period_s
        # Lag toward the target for one exchange; exact for a constant target.
        self._alpha = (
            1.0 if settle_tau_s == 0.0 else 1.0 - math.exp(-exchange_period_s / settle_tau_s)
        )
        self._n = 0  # exchanges so far; integer count avoids float drift
        self._sample_index = 0
        self._fv, self._fi = source.read()
        self._v, self._i = self._quantise(self._fv, self._fi)

    @property
    def source(self) -> SignalSource:
        """The wrapped source (e.g. to call ``set_panel`` on a simulated one)."""
        return self._source

    @property
    def time_s(self) -> float:
        """Simulated time since construction [s]."""
        return self._n * self._dt

    def _quantise(self, v: float, i: float) -> tuple[float, float]:
        if self._v_step > 0.0:
            v = round(v / self._v_step) * self._v_step
        if self._i_step > 0.0:
            i = round(i / self._i_step) * self._i_step
        return v, i

    def read(self) -> tuple[float, float]:
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        self._source.write(duty_cycle)
        tv, ti = self._source.read()
        self._fv += self._alpha * (tv - self._fv)
        self._fi += self._alpha * (ti - self._fi)
        self._n += 1
        # Small offset keeps exact multiples (e.g. 2 ms / 1 ms) off float edges.
        index = math.floor(self._n * self._dt / self._sample_period + 1e-9)
        if index > self._sample_index:
            self._sample_index = index
            self._v, self._i = self._quantise(self._fv, self._fi)

    @property
    def duty(self) -> float:
        return self._source.duty
