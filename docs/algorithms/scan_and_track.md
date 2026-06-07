---
title: "Scan-and-Track (Global MPPT)"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

Under partial shading the P-V curve becomes **multi-modal**: bypass diodes
create several local maxima, only one of which is the global MPP. Gradient
followers (P&O, InCond, fuzzy) climb the nearest peak and get **trapped** on a
local maximum. Scan-and-track avoids this in two stages: first **scan** the
whole operating range to locate the global peak, then **track** it locally for
low-ripple steady state.

## Stage 1 — Scan

Sweep the duty cycle across its full range in fixed increments and record the
power at each point:

$$D_k = D_\text{min} + k\,\Delta D_\text{scan},
\qquad k = 0,1,\dots,N,
\qquad N = \left\lceil \frac{D_\text{max}-D_\text{min}}{\Delta D_\text{scan}} \right\rceil.$$

Because raising $D$ lowers the panel voltage on a SEPIC
($R_\text{eff}(D)=R_\text{load}\left(\tfrac{1-D}{D}\right)^2$), sweeping $D$ sweeps
the *entire* P-V curve, so every local peak — including the global one — is
sampled. The global-best duty is

$$D^\star = D_{\,\arg\max_k P(D_k)}.$$

The scan costs $N{+}1$ control steps of swept (sub-optimal) power before locking
on — the price paid to *guarantee* the global peak rather than a local one.
A measurement at step $k$ corresponds to the duty commanded at step $k{-}1$, so
powers are recorded with one step of latency.

## Stage 2 — Track

Jump to $D^\star$ and hand off to a local tracker (here `PerturbAndObserve`)
with a small step $\Delta D_\text{track}\ll\Delta D_\text{scan}$. This refines
the operating point onto the exact peak and keeps steady-state oscillation low.

## Re-scanning

The shading pattern changes over the day, moving the global peak. An optional
periodic re-scan every $M$ control steps re-acquires it:

$$\text{if } (\text{steps since last scan}) \ge M \;\Rightarrow\; \text{restart Stage 1}.$$

There is a trade-off: frequent re-scans track moving shade better but spend more
time off-MPP during each sweep. Production schemes trigger a re-scan only when a
sudden power drop is detected; the periodic version here is the simplest variant.

## Trade-offs

- **$\Delta D_\text{scan}$:** finer ⇒ won't miss a narrow global peak, but a
  longer (lossier) scan.
- **vs. local methods:** the only one of the four that reaches the global MPP
  under partial shading; in full sun it matches them but pays the one-time scan
  cost at startup.

## Implementation

`mpp_sdk.ScanAndTrack(initial_duty, scan_step, track_step, min_duty, max_duty,
rescan_period)`. State is one power array of length $N{+}1$ plus the embedded
P&O — small and bounded, suitable for the MCU port.

## References

Patel & Agarwal (2008), *MPPT scheme for PV systems operating under partially
shaded conditions*, IEEE TIE. Kobayashi et al. (2006), two-stage global
tracking. Ahmed & Salam (2014), improved scan-and-track.
