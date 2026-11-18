# MPPT Algorithm Metrics Summary

This document consolidates the full catalogue of metrics evaluated for the `mpp-sdk` project: their mathematical
formulation, applicability, implementation status, and **explicit selection for our comparative benchmark**.

---

## 1. General Metrics Table & Selection

**Selection legend:**

- **Selected (Core)**: Primary metric used in the thesis / benchmark comparison.
- **Selected (Dynamic)**: Used in cyclic simulation.
- **Secondary**: Calculable but redundant or noise-limited; used only as supporting diagnostic.
- **Discarded / Lab-Limited**: Impracticable on our bench setup or formally discarded.

| # | Metric | Symbol | Formula | Range / Unit | Implementation Status | Selection for Project | Notes / Role in Benchmark |
|---|---|:---:|---|:---:|:---:|:---:|---|
| **1** | **Static tracking efficiency** | $\eta$ | $\displaystyle \frac{\langle P \rangle}{P_{mpp}} = \frac{1}{N \cdot P_{mpp}} \sum_{k=1}^{N} P_k$ | $[0, 1]$ or $\%$ | **Implemented** | **Secondary** | Blends transient and steady state. Arbitrarily affected by run duration ($10\text{ s}$ vs $30\text{ s}$). Use $\eta_{ss} + E_{loss}$ instead. |
| **2** | **Dynamic energy efficiency** | $\eta_E$ | $\displaystyle \frac{\sum_{k=1}^N P_k}{\sum_{k=1}^N P_{mpp}(t_k)}$ | $[0, 1]$ or $\%$ | **Implemented** | **Selected (Dynamic)** | Used in cyclic simulation (`compare_cyclic.py`), against the time-varying MPP of the profile. |
| **3** | **Steady-state efficiency** | $\eta_{ss}$ | $\displaystyle \frac{1}{M \cdot P_{mpp}} \sum_{k=N-M+1}^{N} P_k$ | $[0, 1]$ or $\%$ | **Implemented** | **Selected (Core)** | Implemented as `final_efficiency`. Evaluates operating point quality after transients extinguish. |
| **4** | **Settling / convergence time** | $T_c$ ($t_s$) | $\displaystyle \min \{ t \mid \forall \tau \ge t, \, P(\tau) \ge (1 - \text{band}) P_{mpp} \}$ | $[s]$ and steps | **Implemented** | **Selected (Core)** | Measures initial lock speed. **Report in both seconds and steps** to bridge hardware (~46 ms) with sim (1 ms). |
| **5** | **Peak-to-peak power ripple** | $\Delta P_{pp}$ | $\displaystyle \max_{k \in \text{tail}} P_k - \min_{k \in \text{tail}} P_k$ | $[W]$ | **Implemented** | **Secondary** | Susceptible to sensor noise floor (0.07–0.17 W peak-to-peak over the tail in the bench runs). $nRMSE$ is statistically superior for comparison. |
| **6** | **Relative overshoot** | $OS$ | $\displaystyle \frac{\max_k P_k - P_{settled}}{P_{settled}}$ | $[0, \infty)$ or $\%$ | **Implemented** | **Secondary** | Non-physical for concave PV curves (bench values are $0.7\text{–}1.9\%$). |
| **7** | **Local trap depth** | $D_{trap}$ | $\displaystyle \frac{P_{settled}}{P_{global\_mpp}}$ | $[0, 1]$ or $\%$ | **Implemented** | **Selected (Core)** | **Decisive for Scenario 2 (partial shading)**. Cleanly separates local traps (~87-89%) from global tracking (~100%). |
| **8** | **Steady-state RMSE** | $RMSE$ | $\displaystyle \sqrt{\frac{1}{M} \sum_{k=N-M+1}^{N} (P_k - P_{mpp})^2}$ | $[W]$ | **Planned** | **Secondary** | Absolute dimensional error. Subsumed by normalized version ($nRMSE$). |
| **9** | **Normalised RMSE** | $nRMSE$ | $\displaystyle \frac{RMSE}{P_{mpp}} \times 100\%$ | $\%$ | **Planned** | **Selected (Core)** | Penalizes oscillations quadratically and normalizes across different light levels (e.g. 7.7 W vs 4.3 W). |
| **10** | **Mean absolute error** | $MAE$ | $\displaystyle \frac{1}{M} \sum_{k=N-M+1}^{N} \| P_k - P_{mpp} \|$ | $[W]$ | **Planned** | **Secondary** | Linear tail error; highly collinear with $nRMSE$. |
| **11** | **Mean relative error** | $RE$ | $\displaystyle \frac{1}{M} \sum_{k=N-M+1}^{N} \frac{\| P_k - P_{mpp} \|}{P_{mpp}} \times 100\%$ | $\%$ | **Planned** | **Secondary** | Redundant with $1 - \eta_{ss}$. Kept only as literature cross-reference. |
| **12** | **Transient energy loss** | $E_{loss}$ | $\displaystyle \sum_{k=1}^{T_c} (P_{mpp,k} - P_k) \cdot \Delta t$ | $[J]$ | **Planned** | **Selected (Core)** | Quantifies the exact energy cost of the search transient in Joules. Differentiates algorithms that reach the same $\eta_{ss}$. |
| **13** | **Standard dynamic MPPT efficiency** | $\eta_{dyn}$ | see EN 50530 / IEC 62891 | % | **Planned** | **Discarded / Lab-Limited** | Needs a PV simulator with defined irradiance profiles. Not available on our bench. See [mppt_standards.md](mppt_standards.md). |
| **14** | **Global capture rate (GMPP hit rate)** | $HR_{GMPP}$ | $\displaystyle \frac{N_{success}}{N_{attempts}} \times 100\%$ | $[0, 100\%]$ | **Planned** | **Selected (Core)** | **Critical for global methods (PSO, Scan&Track)**. Evaluated over repeated runs under partial shading. |
| **15** | **Simulation vs. real fidelity** | $MAPE$ | $\displaystyle \frac{100\%}{N} \sum_{k=1}^N \left\| \frac{P_{sim,k} - P_{real,k}}{P_{real,k}} \right\|$ | $\%$ | **Planned** | **Selected (Validation)** | Replays recorded hardware $D(k)$ through the digital twin (`DynamicSimulatedSource`). Target: $< 5\%$. |
| **16** | **Two-way analysis of variance** | $ANOVA$ | $F_{alg}, F_{cond}, F_{int}, p\text{-value}$ | Dimensionless | **Planned** | **Selected (Validation)** | Statistical proof of significance across Algorithm × Condition ($N \ge 5$ runs per cell). |
| **17** | **Computational complexity per cycle** | $t_{step}, Ops$ | $\displaystyle t_{exec} / \text{cycle}, \; \text{Flash/RAM}$ | $[\mu s], [B]$ | **Planned** | **Selected (Core)** | Evaluates feasibility on RP2040 MCU within 1 ms loop budget. Measured directly on firmware port. |
| **18** | **Panel voltage ripple** | $\Delta V_{pp}$ | $\displaystyle \max_{k \in \text{tail}} V_k - \min_{k \in \text{tail}} V_k$ | $[V]$ | **Planned** | **Selected (Core)** | Measures electrical stress and input bus voltage oscillation induced by the controller. |
| **19** | **ASTM E2848 multivariable regression** | $P_{reg}$ | regression of power on irradiance, temperature and wind speed (exact form: see the standard) | $[W]$ | **Discarded** | **Discarded** | Macroscopic utility-scale standard for long-term plant acceptance. Inapplicable to millisecond MPPT dynamics. |
| **20** | **Direct impact on LCOE** | $\Delta LCOE$ | $\displaystyle \frac{CAPEX + OPEX}{\sum E_{annual} / (1+r)^t}$ | $[\$/MWh]$ | **Discarded** | **Discarded** | Involves 25-year financial/O&M macroeconomic assumptions outside the scope of control firmware. |
| **21** | **Converter conversion efficiency** | $\eta_{conv}$ | $\displaystyle \frac{P_{out,dc}}{P_{in,dc}}$ | $[0, 100\%]$ | **Discarded** | **Discarded** | Reflects SEPIC power-stage hardware losses (MOSFET/diode), not MPPT tracking intelligence. |

---

## 2. Selected Metric Suite

Planned scenarios for the next measurement campaign. Both run on the real converter:

### Test Scenarios

1. **Scenario 1 (planned): single peak, B @ 90°.** Constant uniform irradiance. Baseline tracking test.
2. **Scenario 2 (planned): multi-peak, B @ 45°.** Static partial shading. Tests local maximum trap escape.

### The Selected Benchmark Suite

- **Core tracking performance:** steady-state efficiency ($\eta_{ss}$), trap depth ($D_{trap}$), normalized RMSE
  ($nRMSE$), settling time ($T_c$), transient energy loss ($E_{loss}$).
- **Electrical and embedded quality:** panel voltage ripple ($\Delta V_{pp}$), MCU execution time ($t_{step}$) and
  footprint.
- **Statistical rigor and validation:** GMPP hit rate ($HR_{GMPP}$), two-way ANOVA (Algorithm × Scenario), digital twin
  fidelity (MAPE, sim vs real).
