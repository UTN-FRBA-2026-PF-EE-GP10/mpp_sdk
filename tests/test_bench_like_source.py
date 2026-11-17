"""Unit tests for the BenchLikeSource bench-behaviour wrapper."""

import math

import pytest

import mpp_sdk
from mpp_sdk.io.bench_like import BenchLikeSource


class _Step(mpp_sdk.SignalSource):
    """Inner source: V = 10 * D, I = D, instantly."""

    def __init__(self) -> None:
        self._d = 0.5

    def read(self):
        return 10.0 * self._d, self._d

    def write(self, duty_cycle):
        self._d = duty_cycle

    @property
    def duty(self):
        return self._d


def _make(**kw):
    kw.setdefault("settle_tau_s", 0.0)
    return BenchLikeSource(_Step(), **kw)


def test_invalid_params():
    with pytest.raises(ValueError):
        _make(sample_period_s=0.0)
    with pytest.raises(ValueError):
        _make(exchange_period_s=-1.0)
    with pytest.raises(ValueError):
        _make(settle_tau_s=float("nan"))


def test_reading_held_between_sample_boundaries():
    src = _make(sample_period_s=4e-3, exchange_period_s=1e-3, v_step=0, i_step=0)
    first = src.read()
    seen = []
    for k in range(8):
        src.write(0.6 + 0.01 * k)
        seen.append(src.read())
    assert seen[0] == seen[1] == seen[2] == first  # no boundary yet
    assert seen[3] != first  # boundary at 4 ms
    assert seen[3] == seen[4] == seen[5] == seen[3]
    assert seen[7] != seen[3]


def test_read_is_idempotent():
    src = _make()
    src.write(0.7)
    assert src.read() == src.read()


def test_quantisation_to_step():
    src = _make(sample_period_s=1e-3, v_step=0.01, i_step=0.05)
    src.write(0.5437)
    v, i = src.read()
    assert v == pytest.approx(5.44)
    assert i == pytest.approx(0.55)
    assert abs(v / 0.01 - round(v / 0.01)) < 1e-6


def test_lag_reaches_63_percent_after_tau():
    tau = 10e-3
    src = BenchLikeSource(
        _Step(),
        sample_period_s=1e-3,
        v_step=0,
        i_step=0,
        settle_tau_s=tau,
        exchange_period_s=1e-3,
    )
    v0, i0 = src.read()
    for _ in range(10):  # 10 ms = tau
        src.write(0.9)
    frac = (src.read()[0] - v0) / (9.0 - v0)
    assert frac == pytest.approx(1.0 - math.exp(-1.0), abs=1e-9)
    frac_i = (src.read()[1] - i0) / (0.9 - i0)
    assert frac_i == pytest.approx(1.0 - math.exp(-1.0), abs=1e-9)
    for _ in range(100):
        src.write(0.9)
    assert src.read()[0] == pytest.approx(9.0, abs=1e-3)


def test_deterministic_repeat():
    def run():
        src = BenchLikeSource(_Step())
        out = []
        for k in range(50):
            src.write(0.3 + 0.01 * (k % 7))
            out.append(src.read())
        return out

    assert run() == run()


def test_exchange_rate_changes_what_is_seen():
    def distinct(exchange_period_s):
        src = BenchLikeSource(_Step(), settle_tau_s=0.0, exchange_period_s=exchange_period_s)
        seen = set()
        for k in range(100):
            src.write(0.3 + 0.001 * k)
            seen.add(src.read())
        return len(seen), src.time_s

    fast_n, fast_t = distinct(1e-3)
    slow_n, slow_t = distinct(4e-3)
    assert fast_n < slow_n  # fast decisions see more held repeats
    assert slow_t == pytest.approx(0.4)
    assert fast_t == pytest.approx(0.1)


def test_duty_and_source_passthrough():
    src = _make()
    src.write(0.42)
    assert src.duty == 0.42
    assert isinstance(src.source, _Step)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
@pytest.mark.parametrize("v_step", [0.0, 1e-3])
def test_non_finite_inner_reading_is_held(bad, v_step):
    inner = _Step()
    src = BenchLikeSource(inner, sample_period_s=1e-3, v_step=v_step, settle_tau_s=0.0)
    src.write(0.6)
    good = src.read()
    inner.read = lambda: (bad, bad)
    src.write(0.7)
    assert src.read() == good
    del inner.read
    src.write(0.8)
    assert all(math.isfinite(x) for x in src.read())
    assert src.read()[0] == pytest.approx(8.0, abs=1e-6)
