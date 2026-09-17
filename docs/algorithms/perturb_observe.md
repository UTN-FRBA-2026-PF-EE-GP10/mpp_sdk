---
title: "Perturb & Observe (P&O)"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

Perturb & Observe is the canonical hill-climbing MPPT method. It periodically
**perturbs** the converter duty cycle $D$ by a fixed step and **observes** the
resulting change in panel power $P = V\cdot I$. If power increased, it keeps
moving in the same direction; if power dropped, it reverses.

## Theory

The panel power-voltage curve $P(V)$ is unimodal (single peak) under uniform
irradiance, with a single maximum where

$$\frac{dP}{dV} = 0.$$

P&O estimates the sign of $dP/dV$ from successive samples:

$$\Delta P = P_k - P_{k-1}, \qquad \Delta V = V_k - V_{k-1}.$$

The decision rule (in terms of the *voltage* the algorithm should move toward):

| $\Delta P$ | $\Delta V$ | Action            |
| ---------- | ---------- | ----------------- |
| $> 0$      | $> 0$      | keep raising $V$  |
| $> 0$      | $< 0$      | keep lowering $V$ |
| $< 0$      | $> 0$      | lower $V$         |
| $< 0$      | $< 0$      | raise $V$         |
| $= 0$      | any        | hold              |

For the four non-zero rows, the desired voltage move has the sign of
$\Delta P \cdot \Delta V$. The implementation does not compute that product
directly: it holds only when $\Delta P = 0$, and otherwise raises $V$ unless
$\Delta P \cdot \Delta V > 0$. So the edge case $\Delta V \approx 0$ with
$\Delta P \neq 0$ (duty already saturated at a bound, so the last perturbation
did not move $V$) falls into the "raise $V$" branch rather than holding. This
is harmless in practice: it only arises while $D$ is clamped, where the move
is a no-op anyway.

On the very first call there is no previous sample to compare against, so the
controller just records $(V, P)$ as the reference and perturbs by one
$+\Delta D$ step, picking an arbitrary starting direction.

## SEPIC sign convention

For the SEPIC stage, the reflected input resistance is

$$R_\text{eff}(D) = R_\text{load}\left(\frac{1-D}{D}\right)^2,$$

which is **monotonically decreasing** in $D$. So raising $D$ lowers the panel
voltage. The voltage decision is therefore mapped to its inverse in duty: to
raise $V$, decrease $D$; to lower $V$, increase $D$. Written against the
table above,

$$D_{k+1} = D_k - \operatorname{sign}(\Delta P\,\Delta V)\,\Delta D
\quad\text{when } \Delta V \neq 0,$$

with the $\Delta V \approx 0$, $\Delta P \neq 0$ edge case handled as
described above.

## Trade-offs

- **Step size $\Delta D$:** large $\Rightarrow$ fast convergence but large
  steady-state oscillation around the MPP; small $\Rightarrow$ low ripple but
  slow tracking. This accuracy/speed tension is the method's defining limit.
- **Partial shading:** P&O only follows the local gradient, so on a multi-peak
  curve it gets **trapped on a local maximum**. Escaping it requires a global
  method (scan, PSO).

## Implementation

`mpp_sdk.PerturbAndObserve(initial_duty, step_size, min_duty, max_duty)`.
Fixed step, minimal state (last $V$, last $P$), a few branches, no loops.
Ideal for an MCU.

## References

Femia et al. (2005), *Optimization of perturb and observe MPPT*, IEEE TPEL. Ahmed
& Salam (2015), *An Improved Method to Predict the Position of Maximum Power Point
During Partial Shading for PV Arrays*, IEEE TII.
