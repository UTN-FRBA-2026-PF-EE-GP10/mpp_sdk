"""Scan-and-track global MPPT for a SEPIC converter (partial-shading capable)."""

import math

from . import restart
from .base import MPPTAlgorithm
from .perturb_observe import PerturbAndObserve


class ScanAndTrack(MPPTAlgorithm):
    """Two-stage global MPPT: full-range scan, then local tracking.

    Under partial shading the P-V curve is multi-modal and gradient-following
    methods (P&O, InCond, fuzzy) get trapped on a local maximum. ScanAndTrack
    avoids the trap by **scanning** the whole duty-cycle range first, recording
    the power at each point, then **jumping to the global peak** and handing off
    to a local tracker (P&O) for fine, low-ripple steady-state operation.

    Two re-acquisition mechanisms cover changing conditions. A
    change-detection restart (on by default) re-scans as soon as the tracked
    power moves by more than ``restart_threshold`` — the shading pattern
    changed, so the old global peak is stale. A periodic re-scan every
    ``rescan_period`` steps (off by default) is a belt-and-braces fallback for
    changes the detector cannot see (e.g. a new, higher peak appearing
    elsewhere while the tracked power stays put).

    Phases
    ------
    1. **SCAN** — sweep ``D`` from ``min_duty`` to ``max_duty`` in steps of
       ``scan_step``. The measurement at each call corresponds to the duty
       commanded on the *previous* call, so powers are recorded with one step
       of latency.
    2. **TRACK** — seed a :class:`PerturbAndObserve` at the best duty found and
       delegate to it.

    The scan costs ``ceil((max−min)/scan_step)`` control steps of swept power
    before locking on — the price of guaranteeing the global peak.

    Parameters
    ----------
    initial_duty :
        Accepted only for interface uniformity with the local trackers (so the
        harness can construct every algorithm the same way). A global scan starts
        from its own grid and explores the whole range, so the start point does
        not bias the result; it is merely the duty reported by ``duty`` before the
        first ``step``.
    scan_step :
        Duty increment during the scan. Smaller ⇒ finer (won't miss a narrow
        peak) but a longer scan.
    track_step :
        Step size of the P&O tracker used after the scan.
    rescan_period :
        Re-scan every N steps to follow changing shade. ``None`` disables it.
    restart_threshold :
        Relative power change ``|ΔP|/P`` during TRACK that triggers an
        immediate re-scan (change-detection restart). ``None`` disables it.
    restart_samples :
        Consecutive out-of-band samples required before restarting (debounce
        against measurement noise).
    """

    def __init__(
        self,
        initial_duty: float = 0.5,
        scan_step: float = 0.04,
        track_step: float = 0.005,
        min_duty: float = 0.05,
        max_duty: float = 0.95,
        rescan_period: int | None = None,
        restart_threshold: float | None = 0.2,
        restart_samples: int = 3,
    ) -> None:
        restart._validate_duty_range(min_duty, max_duty)
        restart._validate_finite_positive("scan_step", scan_step)
        restart._validate_finite_positive("track_step", track_step)
        restart._validate_rescan_period(rescan_period)
        self._min = min_duty
        self._max = max_duty
        self._scan_step = scan_step
        self._track_step = track_step
        self._rescan_period = rescan_period
        self._detector = restart._make_restart_detector(restart_threshold, restart_samples)

        self._scan_duties = self._build_scan_grid()
        self._begin_scan()
        self._duty = self._scan_duties[0]
        self._steps_since_scan = 0

    def _build_scan_grid(self) -> list[float]:
        n = int(math.ceil((self._max - self._min) / self._scan_step)) + 1
        return [min(self._max, self._min + k * self._scan_step) for k in range(n)]

    def _begin_scan(self) -> None:
        self._scanning = True
        self._scan_idx = 0
        self._pending: float | None = None
        self._powers: list[float] = []
        self._tracker: PerturbAndObserve | None = None
        if self._detector is not None:
            self._detector.reset()

    def step(self, voltage: float, current: float) -> float:
        self._steps_since_scan += 1

        if not self._scanning and restart._restart_due(
            self._detector, self._rescan_period, self._steps_since_scan, voltage * current
        ):
            self._begin_scan()

        if self._scanning:
            # The measurement we just received belongs to the previously
            # commanded duty (`_pending`); record its power.
            if self._pending is not None:
                self._powers.append(voltage * current)

            if self._scan_idx < len(self._scan_duties):
                d = self._scan_duties[self._scan_idx]
                self._pending = d
                self._scan_idx += 1
                self._duty = d
                return d

            # Scan complete — pick the global-best duty and start tracking.
            best_idx = max(range(len(self._powers)), key=self._powers.__getitem__)
            best_duty = self._scan_duties[best_idx]
            self._tracker = restart._make_local_tracker(
                best_duty, self._track_step, self._min, self._max
            )
            self._scanning = False
            self._steps_since_scan = 0
            self._duty = best_duty
            return best_duty

        self._duty = self._tracker.step(voltage, current)
        return self._duty

    @property
    def duty(self) -> float:
        return self._duty

    @property
    def scanning(self) -> bool:
        return self._scanning
