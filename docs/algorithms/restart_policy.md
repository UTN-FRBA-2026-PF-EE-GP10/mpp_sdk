---
title: "Restart Policy (Global MPPT re-triggering)"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Why a trigger policy

A global search (`ScanAndTrack`'s full duty sweep, or a PSO pass) physically
drives the converter across its range: exploration costs energy, so it cannot
run continuously. After the search hands off, the controller is a plain local
tracker (`PerturbAndObserve`) and cannot escape a local maximum once the
shading pattern changes again. The open question is *when to search again* -
it moves the results more than the choice of search itself. Two mechanisms,
both on the controller side and both fed only by $(V, I)$, answer it: a step
detector and a periodic backstop.

## Step detector

`PowerChangeDetector` (`mpp_sdk/algorithms/restart.py`) watches
$P = V\,I$ during tracking and restarts the global search when the power has
deviated from its reference by more than `threshold` (relative, default
20 %) for `samples` consecutive steps (default 3) - the classic $|\Delta
P|/P$ restart condition used by PSO-MPPT schemes [Liu et al. 2012].

- **Arming after reset**: after a reset (construction, or right after a
  search hands off) the detector simply follows the raw samples until
  `samples` consecutive readings agree within the band before it arms. This
  makes it immune to the electrical settling transient that follows the jump
  to a newly-found peak, with no plant-specific hold-off constant needed.
- **In-band reference follow**: once armed, the reference follows the power
  only while it stays inside the band (an EMA; `smoothing=1.0` by default
  pins it to the last in-band sample). The converter's own continuous
  transients and slow irradiance ramps - which the local tracker follows on
  its own - never trigger a restart.
- **Step detector, blind to ramps**: a change that creeps in over many
  control periods is followed, not flagged. An abrupt shading change is a
  discontinuity and fires within `samples` steps.
- State is four scalars (`_ref`, `_count`, `_armed`, plus the fixed
  `threshold`/`samples`/`smoothing`) and the update is branch-light -
  MCU-portable by design. See the docstring at
  `mpp_sdk/algorithms/restart.py:7-53` for the authoritative behavior; this
  page is explanatory.

## Periodic backstop

The detector has one blind spot: a new, higher peak appearing elsewhere
while the tracked power barely moves (e.g. shade swapping from one panel to
another in a series string). The `rescan_period` backstop covers it by
re-running the search every $M$ control steps unconditionally:

$$\text{if } (\text{steps since last scan}) \ge M \;\Rightarrow\; \text{restart the search.}$$

It bounds the worst-case trapped time to one period, at the price of one
search's energy cost per period.

## Choosing the period: expected-loss model

`harness/compare_rescan.py` sweeps `rescan_period` over {250, 500, 1000,
2000, off} for the global trackers on the cyclic schedule and derives the
optimum from first principles, then checks it against the measurement. The
loss, as a fraction of available energy, is modelled as

$$L(P) = \frac{A}{P} + B \cdot P,$$

where the first term is the search tax and the second is trap exposure:

- **$A$ (search tax)**: a periodic re-search costs a fixed energy $e_s$,
  measured in a steady-full-sun calibration run where re-scanning is the
  *only* loss (backstop off vs. backstop on every `CAL_PERIOD` steps, same
  unchanging condition - the extra energy lost divided by the re-search
  count gives $e_s$). Over $N$ schedule steps there are about $N/P$
  periodic re-searches, so $A = e_s \cdot N / E_\text{available}$.
- **$B$ (trap exposure)**: with the backstop off, stealth traps cost a
  fraction $L_\text{off}$ of the available energy (measured on the same
  backstop-off run used for the calibration above). A trap persists until
  the next periodic re-search, on average $P/2$; for periods below the mean
  plateau length $D$ the exposure scales with $P$, so $B = L_\text{off} /
  D$.

Minimising $L(P)$ gives the derived optimum

$$P^\star = \sqrt{A / B} \approx 1034 \text{ control steps},$$

which lands on the empirical best: Scan&Track's eta energy peaks at
**95.0 %** at period **1000** (the nearest swept value to $P^\star$).
Over-frequent re-scanning (period 250) actually traps *more* often, not
less - each sweep is itself a window during which a mid-scan shading change
can go undetected, so shortening the period below the plateau timescale adds
risk instead of removing it. `harness/compare_rescan.py` regenerates this
table and the accompanying figure (`harness/output/compare_rescan.png`).

## Measured behavior

Local trackers (no restart policy) trap in roughly half the shaded plateaus
of the cyclic schedule, settling at 44-67 % of available power on those
traps (`docs/methodology.md`). The configured global trackers
(`rescan_period=1000`, detector on) cut traps to a handful at the price of
up to ~1 s re-acquisition when only the backstop can free them.

Stochastic search is measured the same way, over seeds rather than periods:
`harness/compare_seeds.py` runs PSO (8 particles, `rescan_period=1000`) over
30 seeds on the cyclic schedule and reports eta **93.9 % +/- 0.7** and
**7.9 +/- 1.7** trapped plateaus, against the deterministic Scan&Track at
**95.0 %** eta and **5** traps with zero variance. Scan&Track beats PSO's
mean on both metrics and removes seed-to-seed variance entirely, which is
why it is the MCU deployment candidate - see `scan_and_track.md` and
`particle_swarm.md` for the per-algorithm detail.

## References

Liu et al. (2012), *A PSO-based MPPT for PV under partial shading*, IEEE
TEC.
