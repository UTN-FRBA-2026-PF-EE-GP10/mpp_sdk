"""Restart trigger shared by the global MPPT controllers."""

import math


class PowerChangeDetector:
    """Detects a sustained relative change in tracked power.

    Global MPPT controllers (:class:`ScanAndTrack`, :class:`ParticleSwarm`)
    search once and then hand off to a local tracker — which cannot escape a
    local maximum when the shading pattern later changes. This detector
    watches ``P = V·I`` during the tracking phase and returns ``True`` when
    the power has deviated from its reference by more than ``threshold``
    (relative) for ``samples`` consecutive steps — the classic ``|ΔP|/P``
    restart condition used by PSO-MPPT schemes [Liu et al. 2012].

    The detector **arms itself only once the power is stable**: after a reset
    (construction, or right after a global search hands off) the reference
    simply follows the raw samples until ``samples`` consecutive readings
    agree within the band. This makes it immune to the electrical transient
    that follows the jump to the newly-found peak — without a plant-specific
    hold-off constant. Once armed, the reference follows the power **only
    while it stays inside the band** (an EMA; by default the last in-band
    sample), so the converter's own continuous transients and slow irradiance
    ramps — which the local tracker follows on its own — never trigger a
    restart, while an abrupt shading change is a discontinuity that fires
    within ``samples`` control steps.

    The detector is therefore a *step* detector: a change crept in over many
    control periods is followed, not flagged. That case (a new global peak
    appearing while the tracked power barely moves) is what a periodic
    re-scan is for — see ``ScanAndTrack(rescan_period=...)``.

    State is four scalars and the update is branch-light — MCU-portable by
    design (see ``AGENTS.md``).

    Parameters
    ----------
    threshold :
        Relative deviation ``|P − P_ref| / P_ref`` that counts as a change.
    samples :
        Consecutive out-of-band samples required to fire (debounce, so a
        single noisy measurement cannot trigger a full re-scan).
    smoothing :
        EMA coefficient for the in-band reference update. The default ``1.0``
        pins the reference to the last in-band sample — maximally tolerant of
        the plant's own recovery transients. Smaller values average further
        back, which catches changes spread over a few steps but **must stay
        well above (in-band drift rate / threshold)**: a lagging reference
        turns a legitimate slow recovery — e.g. the capacitor recharging
        after a full-range scan — into a spurious restart, and with it a
        restart *loop*.
    """

    def __init__(self, threshold: float = 0.2, samples: int = 3, smoothing: float = 1.0) -> None:
        if not (math.isfinite(threshold) and threshold > 0):
            raise ValueError(f"threshold must be a finite positive number; got {threshold=}")
        if samples < 1:
            raise ValueError(f"samples must be >= 1; got {samples=}")
        if not 0.0 < smoothing <= 1.0:
            raise ValueError(f"smoothing must be in (0, 1]; got {smoothing=}")
        self._threshold = threshold
        self._samples = samples
        self._alpha = smoothing
        self._ref: float | None = None
        self._count = 0
        self._armed = False

    def reset(self) -> None:
        """Forget the reference and disarm; re-arms once the power is stable."""
        self._ref = None
        self._count = 0
        self._armed = False

    def update(self, power: float) -> bool:
        """Feed one power sample; ``True`` means a sustained change was detected.

        After firing, the detector resets itself — the caller is expected to
        restart its global search and call ``update`` again once tracking
        resumes.
        """
        if self._ref is None:
            self._ref = power
            return False
        deviation = abs(power - self._ref) / max(abs(self._ref), 1e-9)

        if not self._armed:
            # Arming phase: follow the raw power until it is stable, so the
            # settling transient after a search never poisons the reference.
            if deviation <= self._threshold:
                self._count += 1
                if self._count >= self._samples:
                    self._armed = True
                    self._count = 0
            else:
                self._count = 0
            self._ref = power
            return False

        if deviation <= self._threshold:
            self._count = 0
            self._ref += self._alpha * (power - self._ref)
            return False
        self._count += 1
        if self._count >= self._samples:
            self.reset()
            return True
        return False
