"""Fake curve-tracer source for `curve_tracer_server.py --demo`: lets the
frontend be exercised on any machine, no Pi/Pico/`spidev` required.

Implements exactly the four methods `_poll_loop` calls on a source
(`start_sweep`, `release_relay`, `request_sweep`, `poll_sweep_progress`)
plus the context-manager protocol - duck-typed against `SpiMcuSource`,
not a subclass, so this module pulls in nothing beyond the stdlib and
`SpiMcuSource`/`spidev` are never imported in demo mode.

`poll_sweep_progress()`'s return value is duck-typed against
`SweepProgress` (`index`/`voltage`/`current`/`active`/`final_point`)
rather than importing that class - it lives in `mpp_sdk.io.spi_mcu`,
which requires `spidev` at import time, exactly what demo mode exists to
avoid needing.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

_DEMO_VOC = 21.3
_DEMO_ISC = 0.215
_DEMO_POINTS = 20
_DEMO_KNEE = 0.82  # fraction of Voc where the knee sits
_DEMO_NOISE = 0.01  # fraction of Isc, per-point jitter
_DEMO_POINT_INTERVAL_S = 0.2  # snappier than a real sweep - this is for quick interaction


@dataclass(frozen=True)
class _DemoProgress:
    index: int
    voltage: float
    current: float
    active: bool
    final_point: bool


def _generate_points(rng: random.Random) -> list[tuple[float, float]]:
    """A plausible single-diode-shaped sweep - descending voltage, same
    order as a real sweep (`SpiMcuSource.request_sweep()`'s convention)."""
    points = []
    for idx in range(_DEMO_POINTS):
        v = _DEMO_VOC * (1 - idx / (_DEMO_POINTS - 1))
        shape = 1 / (1 + math.exp((v / _DEMO_VOC - _DEMO_KNEE) * 18))
        jitter = (rng.random() - 0.5) * _DEMO_NOISE * _DEMO_ISC
        i = max(0.0, _DEMO_ISC * shape + jitter)
        points.append((round(v, 4), round(i, 5)))
    return points


class DemoSweepSource:
    """One simulated sweep at a time, paced by wall-clock time rather than
    a background thread - `poll_sweep_progress()`/`request_sweep()` derive
    "how far along" from elapsed time since `start_sweep()`, so there is no
    shared mutable state to lock and nothing to tear down on exit."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._rng = random.Random()
        self._points: list[tuple[float, float]] | None = None
        self._started_at: float | None = None
        self._fetched = False

    def __enter__(self) -> DemoSweepSource:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def _points_captured(self) -> int:
        if self._started_at is None:
            return 0
        elapsed = self._clock() - self._started_at
        return min(_DEMO_POINTS, int(elapsed / _DEMO_POINT_INTERVAL_S) + 1)

    def start_sweep(self) -> None:
        # A sweep already running ignores further triggers - matches
        # mode_curve_tracer.rs's curve_tracer_task (a trigger mid-sweep is
        # impossible by construction there; mirrored here rather than
        # restarting mid-curve).
        if self._started_at is not None and self._points_captured() < _DEMO_POINTS:
            return
        self._points = _generate_points(self._rng)
        self._started_at = self._clock()
        self._fetched = False

    def release_relay(self) -> None:
        pass  # no relay to release in demo mode

    def request_sweep(self) -> list[tuple[float, float]] | None:
        """Matches `SpiMcuSource.request_sweep()`'s one-shot-delivery
        contract: `None` until the (simulated) sweep completes, the full
        point list exactly once, `None` again after. No actual polling -
        there is no transport latency to wait out in demo mode, so unlike
        the real method this takes no `poll_attempts`/`poll_interval_s` -
        `_poll_loop` never passes them (it calls `request_sweep()` bare)."""
        if self._points is None or self._fetched:
            return None
        if self._points_captured() < _DEMO_POINTS:
            return None
        self._fetched = True
        return self._points

    def poll_sweep_progress(self) -> _DemoProgress | None:
        if self._points is None:
            return None
        n = self._points_captured()
        index = n - 1
        v, i = self._points[index]
        active = n < _DEMO_POINTS
        return _DemoProgress(
            index=index, voltage=v, current=i, active=active, final_point=not active
        )
