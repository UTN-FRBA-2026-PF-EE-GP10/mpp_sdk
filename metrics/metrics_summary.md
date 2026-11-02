# MPPT Algorithm Metrics Summary

This document consolidates the full catalogue of metrics evaluated for the `mpp-sdk` project: their mathematical formulation, applicability, implementation status, and **explicit selection for our comparative benchmark**.

---

## 1. General Metrics Table & Selection

**Selection legend:**
- **Selected (Core)** 🎯: Primary metric used in the thesis / benchmark comparison.
- **Selected (Dynamic)** ⚡: Unlocked specifically by Scenario 3 (stepped dynamic dimmer profile) and cyclic simulation.
- **Secondary** ⚠️: Calculable but redundant or noise-limited; used only as supporting diagnostic.
- **Discarded / Lab-Limited** ❌: Impracticable on our bench setup or formally discarded.

| # | Metric | Symbol | Formula | Range / Unit | Implementation Status | Selection for Project | Notes / Role in Benchmark |
|---|---|:---:|---|:---:|:---:|:---:|---|
| **1** | **Static tracking efficiency** | $\eta$ | $\displaystyle \frac{\langle P \rangle}{P_{mpp}} = \frac{1}{N \cdot P_{mpp}} \sum_{k=1}^{N} P_k$ | $[0, 1]$ or $\%$ | **Developed** ✅ | **Secondary** ⚠️ | Blends transient and steady state. Arbitrarily affected by run duration ($10\text{ s}$ vs $30\text{ s}$). Use $\eta_{ss} + E_{loss}$ instead. |
| **2** | **Dynamic energy efficiency** | $\eta_E$ | $\displaystyle \frac{\sum_{k=1}^N P_k}{\sum_{k=1}^N P_{mpp}(t_k)}$ | $[0, 1]$ or $\%$ | **Developed** ✅ | **Selected (Dynamic)** ⚡ | **Headline metric for Scenario 3 (dynamic dimmer)** and cyclic sim (`compare_cyclic.py`). Evaluated against pre-calibrated plateau sweeps. |
| **3** | **Steady-state efficiency** | $\eta_{ss}$ | $\displaystyle \frac{1}{M \cdot P_{mpp}} \sum_{k=N-M+1}^{N} P_k$ | $[0, 1]$ or $\%$ | **Developed** ✅ | **Selected (Core)** 🎯 | Implemented as `final_efficiency`. Evaluates operating point quality after transients extinguish. |
| **4** | **Settling / convergence time** | $T_c$ ($t_s$) | $\displaystyle \min \{ t \mid \forall \tau \ge t, \, P(\tau) \ge (1 - \text{band}) P_{mpp} \}$ | $[s]$ and steps | **Developed** ✅ | **Selected (Core)** 🎯 | Measures initial lock speed. **Report in both seconds and steps** to bridge hardware (~46 ms) with sim (1 ms). |
| **5** | **Peak-to-peak power ripple** | $\Delta P_{pp}$ | $\displaystyle \max_{k \in \text{tail}} P_k - \min_{k \in \text{tail}} P_k$ | $[W]$ | **Developed** ✅ | **Secondary** ⚠️ | Susceptible to sensor noise floor (~0.05–0.1 W). $nRMSE$ is statistically superior for comparison. |
| **6** | **Relative overshoot** | $OS$ | $\displaystyle \frac{\max_k P_k - P_{settled}}{P_{settled}}$ | $[0, \infty)$ or $\%$ | **Developed** ✅ | **Secondary** ⚠️ | Non-physical for concave PV curves (bench values were $< 1.5\%$ across all runs). |
| **7** | **Local trap depth** | $D_{trap}$ | $\displaystyle \frac{P_{settled}}{P_{global\_mpp}}$ | $[0, 1]$ or $\%$ | **Developed** ✅ | **Selected (Core)** 🎯 | **Decisive for Scenario 2 (partial shading)**. Cleanly separates local traps (~87%) from global tracking (~100%). |
| **8** | **Steady-state RMSE** | $RMSE$ | $\displaystyle \sqrt{\frac{1}{M} \sum_{k=N-M+1}^{N} (P_k - P_{mpp})^2}$ | $[W]$ | **Planned** ⚠️ | **Secondary** ⚠️ | Absolute dimensional error. Subsumed by normalized version ($nRMSE$). |
| **9** | **Normalised RMSE** | $nRMSE$ | $\displaystyle \frac{RMSE}{P_{mpp}} \times 100\%$ | $\%$ | **Planned** ⚠️ | **Selected (Core)** 🎯 | Penalizes oscillations quadratically and normalizes across different light levels (e.g. 7.7 W vs 4.3 W). |
| **10** | **Mean absolute error** | $MAE$ | $\displaystyle \frac{1}{M} \sum_{k=N-M+1}^{N} \| P_k - P_{mpp} \|$ | $[W]$ | **Planned** ⚠️ | **Secondary** ⚠️ | Linear tail error; highly collinear with $nRMSE$. |
| **11** | **Mean relative error** | $RE$ | $\displaystyle \frac{1}{M} \sum_{k=N-M+1}^{N} \frac{\| P_k - P_{mpp} \|}{P_{mpp}} \times 100\%$ | $\%$ | **Planned** ⚠️ | **Secondary** ⚠️ | Redundant with $1 - \eta_{ss}$. Kept only as literature cross-reference. |
| **12** | **Transient energy loss** | $E_{loss}$ | $\displaystyle \sum_{k=1}^{T_c} (P_{mpp,k} - P_k) \cdot \Delta t$ | $[J]$ | **Planned** ⚠️ | **Selected (Core)** 🎯 | Quantifies the exact energy cost of the search transient in Joules. Differentiates algorithms that reach the same $\eta_{ss}$. |
| **13** | **EN 50530 tracking loss** | $\varepsilon_{TL}$ | $\displaystyle 1 - \eta_{dyn} = 1 - \frac{\sum P_k \Delta t}{\sum P_{mpp,k} \Delta t}$ | $\%$ (Classes A to D) | **Planned** ⚠️ | **Discarded / Lab-Limited** ❌ | Requires certified solar simulator continuous ramps (0.5 to 100 W/m²·s). Replaced by $\eta_E$ on our dimmer profile. |
| **14** | **Euro / CEC weighted efficiency** | $\eta_{EUR} / \eta_{CEC}$ | $\displaystyle \sum_{i} w_i \cdot \eta_{st}(G_i)$ | $[0, 100\%]$ | **Planned** ⚠️ | **Discarded / Lab-Limited** ❌ | Requires calibrated light source at 7 exact irradiance percentages (5% to 100%). Impracticable with manual lamps. |
| **15** | **Global capture rate (GMPP hit rate)** | $HR_{GMPP}$ | $\displaystyle \frac{N_{success}}{N_{attempts}} \times 100\%$ | $[0, 100\%]$ | **Planned** ⚠️ | **Selected (Core)** 🎯 | **Critical for global methods (PSO, Scan&Track)**. Evaluated over repeated runs under partial shading. |
| **16** | **Simulation vs. real fidelity** | $MAPE$ | $\displaystyle \frac{100\%}{N} \sum_{k=1}^N \left\| \frac{P_{sim,k} - P_{real,k}}{P_{real,k}} \right\|$ | $\%$ | **Planned** ⚠️ | **Selected (Validation)** 🎯 | Replays recorded hardware $D(k)$ through the digital twin (`DynamicSimulatedSource`). Target: $< 5\%$. |
| **17** | **Two-way analysis of variance** | $ANOVA$ | $F_{alg}, F_{cond}, F_{int}, p\text{-value}$ | Dimensionless | **Planned** ⚠️ | **Selected (Validation)** 🎯 | Statistical proof of significance across Algorithm × Condition ($N \ge 5$ runs per cell). |
| **18** | **Computational complexity per cycle** | $t_{step}, Ops$ | $\displaystyle t_{exec} / \text{cycle}, \; \text{Flash/RAM}$ | $[\mu s], [B]$ | **Planned** ⚠️ | **Selected (Core)** 🎯 | Evaluates feasibility on RP2040 MCU within 1 ms loop budget. Measured directly on firmware port. |
| **19** | **Panel voltage ripple** | $\Delta V_{pp}$ | $\displaystyle \max_{k \in \text{tail}} V_k - \min_{k \in \text{tail}} V_k$ | $[V]$ | **Planned** ⚠️ | **Selected (Core)** 🎯 | Measures electrical stress and input bus voltage oscillation induced by the controller. |
| **20** | **ASTM E2848 multivariable regression** | $P_{reg}$ | $P = aG + bG^2 + cGT + dGv$ | $[W]$ | **Discarded** ❌ | **Discarded** ❌ | Macroscopic utility-scale standard for long-term plant acceptance. Inapplicable to millisecond MPPT dynamics. |
| **21** | **Direct impact on LCOE** | $\Delta LCOE$ | $\displaystyle \frac{CAPEX + OPEX}{\sum E_{annual} / (1+r)^t}$ | $[\$/MWh]$ | **Discarded** ❌ | **Discarded** ❌ | Involves 25-year financial/O&M macroeconomic assumptions outside the scope of control firmware. |
| **22** | **Converter conversion efficiency** | $\eta_{conv}$ | $\displaystyle \frac{P_{out,dc}}{P_{in,dc}}$ | $[0, 100\%]$ | **Discarded** ❌ | **Discarded** ❌ | Reflects SEPIC power-stage hardware losses (MOSFET/diode), not MPPT tracking intelligence. |

---

## 2. Dynamic Extensions for Scenario 3 (Dimmer Profile)

When evaluating algorithms under a repeatable **dynamic light dimming profile** (Scenario 3), four specialized metrics are unlocked on the physical bench:

| Dynamic Metric | Symbol | Definition | Role in Scenario 3 |
|---|:---:|---|---|
| **Dynamic Energy Efficiency** | $\eta_E$ | $\frac{\sum P_k \Delta t_k}{\sum P_{mpp}(t_k) \Delta t_k}$ | Overall energy score over the full multi-level dimming cycle. |
| **Re-acquisition Time** | $T_{reacq}$ | $\min \{ t \ge t_{step} \mid P(t) \ge 0.95 \cdot P_{mpp,new} \}$ | Time (and steps) required to regain the MPP after a dimming transition. |
| **Plateau Hit Ratio** | $HR_{plat}$ | $N_{settled\_plateaus} / N_{total\_plateaus}$ | Success rate across all held dimming steps (catches loss-of-tracking on downward steps). |
| **Restart Trigger Accuracy** | $N_{trig}$ | Count of full global re-scans triggered | Verifies whether $\Delta P$ threshold detection in Scan&Track / PSO triggers on light drops without false-triggering on noise. |

---

## 3. Selected Metric Suite for the Next Measurement Campaign

The upcoming measurement campaign will evaluate algorithms across three distinct physical scenarios using the selected core suite:

### Test Scenarios
1. **Scenario 1 (Single Peak — B @ 90°)**: Constant uniform irradiance. Baseline tracking test.
2. **Scenario 2 (Multi-Peak — B @ 45°)**: Static partial shading. Tests local maximum trap escape.
3. **Scenario 3 (Dynamic Dimming — Repeatable Stepped Profile)**: Pre-calibrated dimmer staircase (e.g. $100\% \to 60\% \to 30\% \to 100\%$, holding 5–10 s per plateau). Tests dynamic tracking, re-acquisition, and restart policy triggers.

### The Selected Benchmark Suite

```mermaid
graph TD
    subgraph Core_Performance [1. Core Tracking Performance]
        M3["Steady-State Efficiency (η_ss)"]
        M7["Trap Depth (D_trap)"]
        M9["Normalized RMSE (nRMSE)"]
        M4["Settling Time (T_c)"]
        M12["Transient Energy Loss (E_loss)"]
    end

    subgraph Dynamic_Dimming [2. Dynamic Dimmer Tracking (Scenario 3)]
        M2["Dynamic Energy Efficiency (η_E)"]
        MD1["Re-acquisition Time (T_reacq)"]
        MD2["Plateau Success / Trap Count"]
        MD3["Restart Trigger Accuracy"]
    end

    subgraph Hardware_Implementation [3. Electrical & Embedded Quality]
        M19["Panel Voltage Ripple (ΔV_pp)"]
        M18["MCU Execution Time (t_step) & Footprint"]
    end

    subgraph Statistical_Validation [4. Statistical Rigor & Validation]
        M15["GMPP Hit Rate (HR_GMPP)"]
        M17["Two-Way ANOVA (Algorithm × Scenario)"]
        M16["Digital Twin Fidelity (MAPE Sim-vs-Real)"]
    end
```
