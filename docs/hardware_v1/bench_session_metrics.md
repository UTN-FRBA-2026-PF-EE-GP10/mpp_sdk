# Bench Session Metrics: Two Panels, 50 Ohm

This document evaluates the 15 closed-loop hardware runs from `data/bench/two_panels_50R_20261017/` (commit `15d427f`), retaining **only the core metrics selected for the project's comparison benchmark** (as formalized in [`metrics/metrics_summary.md`](../../metrics/metrics_summary.md) and [`metrics/metrics_analysis.md`](../../metrics/metrics_analysis.md)).

Redundant metrics (static $\eta$, raw power ripple $\Delta P_{pp}$, non-physical overshoot $OS$, $MAE$, $RE$) have been omitted in favor of normalized, physically discriminative indicators.

---

## 1. Selected Core Metrics Applied

| Metric | Symbol | Definition / Setting | Role in Comparison |
|---|:---:|---|---|
| **Steady-State Efficiency** | $\eta_{ss}$ | Mean of $P$ over the final 30 % of the run divided by $P_{mpp}$. | Checks convergence quality after search transients extinguish. |
| **Local Trap Depth** | $D_{trap}$ | $\frac{P_{settled}}{P_{global\_mpp}}$ (equivalent to $\eta_{ss}$ on multi-peak curves). | **Decisive under partial shading**: quantifies power lost when stuck on a secondary peak. |
| **Settling Time** | $T_c$ | First sample after which the entire trace remains inside $\pm 5\%$ of $P_{mpp}$. Reported in **seconds and steps**. | Measures initial acquisition speed. Step count provides the invariant bridge to simulation ($1\text{ ms}$ vs $\sim 46\text{ ms}$). |
| **Transient Energy Loss** | $E_{loss}$ | $\sum_{k=1}^{T_c} (P_{mpp} - P_k) \cdot \Delta t_k$ [Joules]. | Exact energy cost burned during the convergence search. Differentiates algorithms that reach the same $\eta_{ss}$. |
| **Normalized RMSE** | $nRMSE$ | $\frac{1}{P_{mpp}}\sqrt{\frac{1}{M}\sum_{tail}(P_k - P_{mpp})^2} \times 100\%$ | Penalizes tail oscillations quadratically; normalized across different light levels. |
| **Panel Voltage Ripple** | $\Delta V_{pp}$ | $\max(V_{tail}) - \min(V_{tail})$ [Volts]. | Measures electrical stress and input bus voltage oscillation induced by duty dithering. |

---

## 2. Scenario 1: Uniform Irradiance (B @ 90°, Single Peak)

- **Reference $P_{mpp}$:** **7.69 W** (sweep best).
- **Setup:** 10 s runs. P&O, InCond, and Fuzzy start at duty 0.45. Scan&Track and PSO use their native initialization.

| Algorithm | $\eta_{ss}$ | Settling Time ($T_c$) | Transient Loss ($E_{loss}$) | $nRMSE$ | Voltage Ripple ($\Delta V_{pp}$) | Settled Duty | Settled Voltage |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **P&O** | 100.4 % | 2.12 s (44 steps) | 4.63 J | 0.6 % | 1.27 V | 0.352 | 29.6 V |
| **InCond** | 100.1 % | 2.05 s (43 steps) | 4.52 J | 0.6 % | 1.24 V | 0.355 | 29.2 V |
| **Fuzzy** | 100.1 % | 5.67 s (119 steps) | **12.65 J** | 0.4 % | **0.78 V** | 0.349 | 29.9 V |
| **Scan&Track** | 100.2 % | 1.10 s (22 steps) | 5.20 J | 0.6 % | 0.85 V | 0.352 | 29.6 V |
| **PSO** | 100.6 % | 1.13 s (21 steps) | **3.36 J** | 0.8 % | 1.23 V | 0.356 | 29.2 V |

### Observations on Scenario 1
- **Steady-State Holding:** All five algorithms converge near 100% $\eta_{ss}$ ($7.70\text{–}7.74\text{ W}$), confirming that single-peak steady state does not discriminate between algorithms.
- **Convergence Cost ($E_{loss}$):** Although Fuzzy reaches 100% $\eta_{ss}$, its slow convergence (119 steps / 5.67 s) burns **12.65 J** of energy—nearly triple that of P&O (4.63 J) and quadruple that of PSO (3.36 J).
- **Electrical Stress ($\Delta V_{pp}$):** P&O, InCond, and PSO exhibit $\sim 1.2\text{–}1.3\text{ V}$ bus voltage ripple from active dithering. Fuzzy operates with significantly lower voltage ripple (0.78 V).

---

## 3. Scenario 2: Partial Shading (B @ 45°, Two Peaks)

- **Reference $P_{mpp}$:** **4.29 W** (refined from runs; the coarse 20-point sweep missed the narrow apex at 4.03 W).
- **Topography:** Global peak is at high voltage ($\sim 4.29\text{ W}$, $31.5\text{ V}$, $D \approx 0.26$). Local sub-peak is at low voltage ($\sim 3.77\text{ W}$, $13.8\text{ V}$, $D \approx 0.46$).

| Run | Start Duty $D_0$ | $\eta_{ss}$ = $D_{trap}$ | Settling Time ($T_c$) | Transient Loss ($E_{loss}$) | $nRMSE$ | Voltage Ripple ($\Delta V_{pp}$) | Settled Duty | Peak Reached |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **P&O** | 0.20 | 99.6 % | 1.15 s (24 steps) | 0.83 J | 0.6 % | 1.02 V | 0.258 | **Global (High V)** |
| **P&O** | 0.25 | 100.1 % | 0.04 s (0 steps) | 0.00 J | 0.5 % | 0.84 V | 0.259 | **Global (High V)** |
| **P&O** | 0.35 | 100.0 % | 2.34 s (49 steps) | 2.52 J | 0.6 % | 1.00 V | 0.259 | **Global (High V)** |
| **P&O** | 0.45 | **87.6 %** | never | 5.34 J* | 12.4 % | 0.68 V | 0.460 | **Local Trap** |
| **P&O (30 s)** | 0.50 | **88.0 %** | never | 15.19 J* | 12.0 % | 0.89 V | 0.459 | **Local Trap** |
| **InCond** | 0.50 | **87.9 %** | never | 5.55 J* | 12.1 % | 0.54 V | 0.458 | **Local Trap** |
| **Fuzzy** | 0.50 | **86.7 %** | never | 6.56 J* | 13.3 % | 0.28 V | 0.446 | **Local Trap** |
| **Scan&Track** | Native scan | 100.0 % | 1.25 s (24 steps) | 2.42 J | 0.6 % | 1.03 V | 0.259 | **Global (High V)** |
| **PSO** | Native seed | **88.4 %** | never | 6.23 J* | 11.6 % | 0.81 V | 0.459 | **Local Trap** |
| **PSO (20 s)** | Native seed | **88.8 %** | never | 10.67 J* | 11.2 % | 0.71 V | 0.462 | **Local Trap** |

*\*Note: For runs that never enter the $\pm 5\%$ band of the global peak, $E_{loss}$ is integrated over the full run duration.*

### GMPP Hit Rate Summary ($HR_{GMPP}$)

A run is scored as a hit if its settled power is within $\pm 5\%$ of the global MPP (4.29 W):

| Algorithm | Hits / Attempts | $HR_{GMPP}$ | Primary Limitation Identified |
|---|:---:|:---:|---|
| **Scan&Track** | 1 / 1 | **100 %** | Autonomous global lock via deterministic duty sweep. |
| **P&O** | 3 / 5 | 60 % | **Start-duty dependent**: climbs global peak if $D_0 \le 0.35$, trapped if $D_0 \ge 0.45$. |
| **InCond** | 0 / 1 | 0 % | Gradient-only; climbs nearest local peak from $D_0 = 0.50$. |
| **Fuzzy** | 0 / 1 | 0 % | Gradient-only; trapped on local peak from $D_0 = 0.50$. |
| **PSO** | 0 / 2 | 0 % | Trapped on local peak across both run durations (needs seed repetitions to evaluate stochastic probability). |

---

## 4. Key Takeaways from the Selected Metrics

1. **Trap Depth ($D_{trap}$) vs. Error ($nRMSE$):**
   - On the global peak, $nRMSE \approx 0.5\text{–}0.6\%$, reflecting clean tracking.
   - On the local trap, $nRMSE$ jumps to $11\text{–}13\%$, directly reflecting the $12\%$ power deficit.
2. **Transient Cost ($E_{loss}$) vs Settling Time ($T_c$):**
   - $E_{loss}$ in Joules provides a direct physical penalty. Fuzzy settled at 100% $\eta_{ss}$ in Scenario 1, but its sluggish response cost 12.65 J.
   - Reporting $T_c$ in **steps** (e.g. 21 to 44 steps) normalizes hardware execution against the $1\text{ ms}$ simulation model.
3. **Scan&Track Dominance under Static Shading:**
   - Scan&Track is the only algorithm that reached the global peak autonomously without operator bias in initial duty. Its scan cost $2.42\text{ J}$ and 24 steps, easily offset by avoiding the $12\%$ local trap.

---

## 5. Protocol for the Next Measurement Campaign

The next campaign will expand on this baseline by testing **all 5 algorithms across 3 standardized scenarios**:

1. **Scenario 1 (Single Peak — 90°):** Run $N \ge 5$ repeats per algorithm with standardized $D_0 \in \{0.20, 0.35, 0.50\}$.
2. **Scenario 2 (Multi-Peak — 45°):** Run $N \ge 10$ repeats with randomized seeds for PSO and varied $D_0$ for local trackers to establish formal **$HR_{GMPP}$** and feed the **Two-Way ANOVA**.
3. **Scenario 3 (Dynamic Dimmer Profile):**
   - Execute a repeatable dimmer staircase profile ($100\% \to 60\% \to 30\% \to 100\%$, holding 5–10 s per plateau).
   - Compute **Dynamic Energy Efficiency ($\eta_E$)**, **Re-acquisition Time ($T_{reacq}$)**, and verify **Restart Policy** triggers on hardware.
