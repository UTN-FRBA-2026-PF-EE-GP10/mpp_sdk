"""Fake curve-tracer source for `curve_tracer_server.py --demo`: lets the
frontend be exercised on any machine, no Pi/Pico/`spidev` required.

Implements `mpp_sdk.io.sweep_source.SweepSource`, structurally - not a
subclass, so this module pulls in nothing beyond the stdlib -
`SpiMcuSource`/`spidev` are never imported in demo mode.

`poll_sweep_progress()`'s return value likewise satisfies
`mpp_sdk.io.sweep_source.SweepProgressLike` rather than importing
`SweepProgress` itself - that class lives in `mpp_sdk.io.spi_mcu`, which
requires `spidev` at import time, exactly what demo mode exists to avoid
needing.
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

    def start_demo_sweep(self, bright: bool = False) -> None:
        # Every sweep is already simulated here, so the firmware's stored
        # curves have no counterpart - just run the normal one.
        self.start_sweep()

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

    def set_divider_ranges(
        self, vin_range: str | int = "low", vout_range: str | int = "low"
    ) -> None:
        self._vin_range = vin_range
        self._vout_range = vout_range

    def set_ron(self, ron_mohm: int = 6) -> None:
        self._ron_mohm = ron_mohm

    def set_max31865(self, enabled: bool = False) -> None:
        self._max31865_enabled = bool(enabled)

    def set_cutoffs(self, i_max_ma: int | None = 1000, v_max_mv: int | None = 40000) -> None:
        if i_max_ma is not None:
            self._cutoff_i_max_ma = i_max_ma
        if v_max_mv is not None:
            self._cutoff_v_max_mv = v_max_mv

    def reset_cutoff(self) -> None:
        pass

    def set_psu_target(self, vout_target_mv: int = 5000) -> None:
        self._psu_vout_target_mv = vout_target_mv

    def set_psu_fixed_duty(self, fixed_duty: float = 0.5) -> None:
        self._psu_fixed_duty = fixed_duty

    def set_power_supply_mode(
        self,
        enabled: bool = False,
        open_loop: bool = False,
        vout_target_mv: int | None = 5000,
        fixed_duty: float | None = 0.5,
    ) -> None:
        self._psu_enabled = bool(enabled)
        self._psu_open_loop = bool(open_loop)
        if vout_target_mv is not None:
            self._psu_vout_target_mv = vout_target_mv
        if fixed_duty is not None:
            self._psu_fixed_duty = fixed_duty

    def configure(self, **kwargs: object) -> None:
        if "vin_range" in kwargs and kwargs["vin_range"] is not None:
            self._vin_range = str(kwargs["vin_range"])
        if "vout_range" in kwargs and kwargs["vout_range"] is not None:
            self._vout_range = str(kwargs["vout_range"])
        if "ron_mohm" in kwargs and kwargs["ron_mohm"] is not None:
            self._ron_mohm = int(kwargs["ron_mohm"])  # type: ignore[arg-type]
        if "max31865" in kwargs and kwargs["max31865"] is not None:
            self._max31865_enabled = bool(kwargs["max31865"])
        if "i_max_ma" in kwargs and kwargs["i_max_ma"] is not None:
            self._cutoff_i_max_ma = int(kwargs["i_max_ma"])  # type: ignore[arg-type]
        if "v_max_mv" in kwargs and kwargs["v_max_mv"] is not None:
            self._cutoff_v_max_mv = int(kwargs["v_max_mv"])  # type: ignore[arg-type]
        if "psu_enabled" in kwargs and kwargs["psu_enabled"] is not None:
            self._psu_enabled = bool(kwargs["psu_enabled"])
        if "psu_open_loop" in kwargs and kwargs["psu_open_loop"] is not None:
            self._psu_open_loop = bool(kwargs["psu_open_loop"])
        if "psu_vout_target_mv" in kwargs and kwargs["psu_vout_target_mv"] is not None:
            self._psu_vout_target_mv = int(kwargs["psu_vout_target_mv"])  # type: ignore[arg-type]
        if "psu_fixed_duty" in kwargs and kwargs["psu_fixed_duty"] is not None:
            self._psu_fixed_duty = float(kwargs["psu_fixed_duty"])  # type: ignore[arg-type]
