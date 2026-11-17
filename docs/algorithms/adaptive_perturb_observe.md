---
title: "Adaptive-step Perturb & Observe"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

Adaptive-step P&O keeps the direction rule of [Perturb & Observe](perturb_observe.md).
It changes the step size $\Delta D$ at each call:

- Far from the MPP the power slope is large, so the step grows.
- Near the MPP the slope is small, so the step shrinks.

This removes the fixed-step trade-off: fast convergence and low ripple at the
same time.

## Theory

The step is proportional to the relative power slope, clamped to a range:

$$\Delta D_k = \operatorname{clamp}\!\left(g\,\frac{|\Delta P_k|}{\Delta D_{k-1}\,P_k},\;\Delta D_\min,\;\Delta D_\max\right)$$

- $|\Delta P_k| / \Delta D_{k-1}$ estimates $|dP/dD|$ from the last perturbation.
- Dividing by $P_k$ makes the gain $g$ independent of the panel power rating.
- At the MPP, $dP/dD = 0$, so the step falls to $\Delta D_\min$. This value sets the
  steady-state ripple.
- $\Delta D_\max$ limits the speed far from the MPP.

## SEPIC sign convention

The direction rule is the same as for fixed-step P&O. Raising $D$ lowers the
panel voltage, so:

- $\Delta P\,\Delta V > 0$: decrease $D$.
- $\Delta P\,\Delta V < 0$: increase $D$.
- $\Delta P = 0$: hold.

$$D_{k+1} = D_k - \operatorname{sign}(\Delta P\,\Delta V)\,\Delta D_k$$

On the first call the controller records $(V, P)$ and moves up by
$\Delta D_\min$.

## Trade-offs

- **Ripple:** set by $\Delta D_\min$, not by $\Delta D_\max$.
- **Speed:** set by $\Delta D_\max$ and the gain $g$. A larger $g$ reaches
  $\Delta D_\max$ closer to the MPP.
- **Noise:** the slope estimate uses one pair of samples. Noise can raise the
  step near the MPP. Keep $g$ small on noisy measurements.
- **Partial shading:** it follows the local gradient, so it can stay on a local
  maximum, like fixed-step P&O.

## Implementation

`mpp_sdk.AdaptivePerturbAndObserve(initial_duty, min_step, max_step, gain, min_duty, max_duty)`.

- State: last $V$, last $P$, last step and the duty.
- `step()` uses no loops and no libraries, so it runs on an MCU.
- `last_step` gives the size of the most recent perturbation.
