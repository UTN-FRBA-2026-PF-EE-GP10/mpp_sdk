---
title: "Fuzzy-Logic MPPT"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

A fuzzy-logic controller climbs the same hill as P&O, but replaces the fixed
step with a *graduated* one obtained from linguistic rules: far from the MPP it
takes large steps, near the MPP it takes small ones. This eases the
speed/oscillation trade-off without an explicit model of the panel.

It remains a **local tracker** — it is trapped on local maxima under partial
shading, so it is not a global MPPT method on its own.

## Inputs

Two normalized inputs are computed each step:

$$E = \frac{\Delta P}{\Delta V} \quad(\text{power--voltage slope}),
\qquad
\Delta E = E_k - E_{k-1}.$$

$E$ is the gradient $dP/dV$: $E>0$ means left of the MPP, $E=0$ at it, $E<0$
right of it. Each input is scaled and clamped to $[-1,1]$:

$$\hat{E} = \operatorname{clip}\!\Big(\frac{E}{s_E},\,-1,\,1\Big),
\qquad
\hat{E}_\Delta = \operatorname{clip}\!\Big(\frac{\Delta E}{s_{\Delta E}},\,-1,\,1\Big).$$

## Fuzzification

Each input is mapped onto five triangular sets — NB, NS, ZE, PS, PB — with
centres at $\{-1,-0.5,0,0.5,1\}$ and half-width $0.5$:

$$\mu_i(x) = \max\!\Big(0,\; 1 - \frac{|x - c_i|}{0.5}\Big).$$

## Rule base and inference

A $5\times5$ Mamdani rule table assigns an output singleton $r_{ij}$ (a duty
step in $[-1,1]$) to each combination of input sets. Because $\Delta D$ must
oppose $E$ (SEPIC: raise $V \Rightarrow$ lower $D$), the table is built so that
large positive $E$ yields a large negative $\Delta D$, and vice-versa.

Rule weights use the product of memberships, $w_{ij} = \mu_i(\hat{E})\,\mu_j(\hat{E}_\Delta)$.

## Defuzzification

Weighted average of the fired singletons gives the normalized step, scaled by
the maximum step $\Delta D_\text{max}$:

$$\Delta D = \Delta D_\text{max}\,
\frac{\sum_{i,j} w_{ij}\, r_{ij}}{\sum_{i,j} w_{ij}},
\qquad
D_{k+1} = \operatorname{clip}(D_k + \Delta D).$$

Singleton outputs (Sugeno-style defuzzification) keep the controller cheap —
no output-set integration — which matters for the MCU port.

## Implementation

`mpp_sdk.FuzzyLogic(initial_duty, e_scale, de_scale, max_step, …)`. The scales
$s_E, s_{\Delta E}$ tune aggressiveness and depend on the panel's current/voltage
ranges.

## References

Esram & Chapman (2007), *Comparison of PV array MPPT techniques*, IEEE TEC.
