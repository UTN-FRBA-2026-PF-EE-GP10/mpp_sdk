---
title: "Incremental Conductance (InCond)"
subtitle: "MPPT algorithm reference"
geometry: "margin=2.2cm"
fontsize: 11pt
header-includes:
  - \usepackage{amsmath}
---

## Idea

Incremental Conductance tracks the MPP by comparing the panel's *incremental*
conductance $\Delta I/\Delta V$ against its *instantaneous* conductance $-I/V$.
At the maximum power point the two are equal, which gives an explicit
"at-the-MPP" test that P&O lacks.

## Theory

The maximum of $P = V\cdot I$ occurs where $dP/dV = 0$. Expanding,

$$\frac{dP}{dV} = \frac{d(VI)}{dV} = I + V\frac{dI}{dV} = 0
\;\Longrightarrow\;
\frac{dI}{dV} = -\frac{I}{V}.$$

This yields the three-way decision:

$$
\begin{aligned}
\frac{\Delta I}{\Delta V} &> -\frac{I}{V} &&\Rightarrow\; \text{left of MPP, raise } V,\\
\frac{\Delta I}{\Delta V} &= -\frac{I}{V} &&\Rightarrow\; \text{at MPP, hold},\\
\frac{\Delta I}{\Delta V} &< -\frac{I}{V} &&\Rightarrow\; \text{right of MPP, lower } V.
\end{aligned}
$$

## Division-free form

To avoid dividing by $\Delta V$ (which is zero when the operating point is
steady), multiply through by $V\,\Delta V$ and compare signs:

$$\operatorname{sign}\!\big(\Delta I\, V + I\, \Delta V\big)
\quad\text{against}\quad \operatorname{sign}(\Delta V).$$

When they agree, the operating point is left of the MPP. The special case
$\Delta V \approx 0$ falls back to the sign of $\Delta I$.

## SEPIC sign convention

Same as P&O: $R_\text{eff}(D)=R_\text{load}\left(\tfrac{1-D}{D}\right)^2$ is
decreasing in $D$, so "raise $V$" maps to "decrease $D$". InCond is a drop-in
replacement for P&O.

## Advantages and limits

- **vs. P&O:** the explicit MPP condition lets it hold still at the peak,
  reducing steady-state oscillation, and it responds more cleanly to fast
  irradiance changes.
- **Partial shading:** still a local, gradient-following method — it is
  **trapped on local maxima** just like P&O.

## Implementation

`mpp_sdk.IncrementalConductance(initial_duty, step_size, min_duty, max_duty)`.

## References

Hussein et al. (1995), *Maximum photovoltaic power tracking: an algorithm for
rapidly changing atmospheric conditions*, IEE Proc.
