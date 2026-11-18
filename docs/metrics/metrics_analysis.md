# Metrics Analysis for Comparing MPPT Algorithms

This document details the mathematical justification, experimental feasibility, and practical selection of the metrics
used to benchmark MPPT algorithms in the `mpp-sdk` framework.

---

## 1. Selected Core Metrics and Implementation

### 1.1. Dynamic Energy Efficiency ($\eta_E$) - Implemented (`energy_efficiency`)

$$\eta_E = \frac{\sum_{k=1}^N P_k \cdot \Delta t_k}{\sum_{k=1}^N P_{mpp}(t_k) \cdot \Delta t_k}$$

- **Role:** Energy-weighted efficiency against a time-varying $P_{mpp}(t)$. Used in cyclic simulation
  (`harness/compare_cyclic.py`).

---

### 1.2. Steady-State Efficiency ($\eta_{ss}$) & Local Trap Depth ($D_{trap}$) - Implemented (Selected)

$$\eta_{ss} = \frac{1}{M \cdot P_{mpp}} \sum_{k=N-M+1}^{N} P_k, \qquad D_{trap} = \frac{P_{settled}}{P_{global\_mpp}}$$

- **Code:** `final_efficiency` and `trap_depth` in `mpp_sdk/metrics.py`.
- **Role:** Evaluates operating point quality once transients extinguish (averaged over the tail of the run:
  `final_efficiency` uses the last `last_n` samples, default 100).
- **Discrimination:**
  - On single-peak curves ($90^\circ$), all functional algorithms reach $\eta_{ss} \approx 100\%$.
  - On multi-peak partial-shading curves ($45^\circ$, Scenario 2), $D_{trap}$ cleanly separates local trackers trapped
    on the low-voltage peak ($D_{trap} \approx 87\text{–}89\%$) from global trackers reaching the global MPP
    ($D_{trap} \approx 100\%$).

---

### 1.3. Convergence Time ($T_c$) - Implemented (Selected)

$$T_c = \min \{ t \mid \forall \tau \ge t, \, P(\tau) \ge (1 - \text{band}) P_{mpp} \}$$

- **Code:** `settling_time` in `mpp_sdk/metrics.py`.
- **Role:** Measures tracking speed from cold start.
- **Hardware Units:** Must be reported in **both seconds and control steps**. Because the physical HIL step takes
  $\sim 46\text{ ms}$ (due to ADC settling waits and filtering) while simulation runs at $1\text{ kHz}$ ($1\text{ ms}$),
  step counts provide the true invariant metric between simulation and real hardware.

---

### 1.4. Transient Energy Loss ($E_{loss}$) - Planned (Selected)

$$E_{loss} = \sum_{k=1}^{T_c} (P_{mpp,k} - P_k) \cdot \Delta t_k$$

- **Role:** Quantifies the exact energy penalty (in Joules) incurred during the search transient.
- **Why It Matters:** Two algorithms can converge to the same $\eta_{ss} = 100\%$ and even have similar settling times,
  but one may stay closer to the peak during the climb while the other wanders or oscillates wildly. In the bench data,
  Fuzzy and P&O both settled at $100\%$, but Fuzzy lost $12.54\text{ J}$ during convergence compared to P&O's
  $4.54\text{ J}$.

---

### 1.5. Steady-State Normalized RMSE ($nRMSE$) - Planned (Selected)

$$RMSE = \sqrt{\frac{1}{M} \sum_{k=N-M+1}^{N} (P_k - P_{mpp})^2}, \qquad nRMSE = \frac{RMSE}{P_{mpp}} \times 100\%$$

- **Role:** Replaces raw peak-to-peak ripple ($\Delta P_{pp}$).
- **Statistical Superiority:** Peak-to-peak ripple is easily dominated by single-sample ADC spikes or noise floor
  (0.07–0.17 W peak-to-peak over the tail in the bench runs). $nRMSE$ averages deviations over the entire tail,
  penalizes large excursions quadratically, and
  normalizes across different power levels.

---

### 1.6. GMPP Hit Rate ($HR_{GMPP}$) - Planned (Selected)

$$HR_{GMPP} = \frac{N_{success}}{N_{total}} \times 100\%$$

- **Role:** Critical for evaluating global MPPT methods (Scan&Track, PSO) under partial shading (Scenario 2).
- **Requirements:** Requires repeated runs ($N \ge 10$) with varying initial duties $D_0$ and RNG seeds for PSO.

---

### 1.7. Panel Voltage Ripple ($\Delta V_{pp}$) - Planned (Selected)

$$\Delta V_{pp} = \max_{k \in \text{tail}} V_k - \min_{k \in \text{tail}} V_k$$

- **Role:** Measures electrical stress induced by duty dithering on the SEPIC converter's input bus capacitor.
- **Benchmark Observation:** P&O dithering induced $\sim 1.0\text{–}1.3\text{ V}$ ripple, whereas Fuzzy Logic converged
  with lower voltage ripple ($\sim 0.3\text{–}0.8\text{ V}$).

---

### 1.8. Computational Complexity per Cycle ($t_{step}$) - Post-Port (Selected)

- **Role:** Feasibility of MCU deployment on the RP2040.
- **Budget:** The target control loop runs at $1\text{ kHz}$ ($1000\ \mu s$ total budget).
- **Execution Metric:** Execution time per step ($\mu s$), RAM usage (out of 264 KB), and Flash footprint (out of 2 MB)
  measured on the Rust firmware port.

---

### 1.9. Simulation vs. Reality Fidelity ($MAPE$) - Validation

$$MAPE = \frac{100\%}{N} \sum_{k=1}^{N} \left| \frac{P_{sim,k} - P_{real,k}}{P_{real,k}} \right|$$

- **Role:** Validates the accuracy of the digital twin (`DynamicSimulatedSource`) against the real SEPIC converter.
- **Replay Methodology:** The recorded hardware duty sequence $D(k)$ is replayed open-loop on the simulator configured
  with the measured I-V curve (`MeasuredPanel`), the matched step time ($46\text{ ms}$), and the actual load
  ($50\ \Omega$). Target: $MAPE < 5\%$.

---

### 1.10. Two-Way ANOVA - Validation

- **Role:** Rigorous statistical hypothesis testing:
  - **Factor A:** Algorithm (P&O, InCond, Fuzzy, Scan&Track, PSO).
  - **Factor B:** Scenario (B1: Single Peak, B2: Partial Shading).
  - **Dependent Variable:** $\eta_{ss}$ (or $nRMSE$).
- Proves whether performance differences are statistically significant or attributable to bench noise ($p < 0.05$). See
  [anova_analysis.md](anova_analysis.md).

---

## 2. Deprioritized and Discarded Metrics

| Metric | Status | Reason for Deprioritization / Discard |
|---|:---:|---|
| **Static $\eta$ (whole run)** | Secondary | Conflates transient search and steady-state holding; sensitive to arbitrary run length. |
| **Power Ripple $\Delta P_{pp}$** | Secondary | Limited by ADC sensor noise floor; subsumed by $nRMSE$. |
| **Overshoot $OS$** | Secondary | PV P-V curves are concave; power monotonically climbs unless flash irradiance occurs. Recomputed on the bench runs, $OS$ is $0.7\text{–}1.9\%$. |
| **MAE & RE** | Secondary | Highly collinear with $nRMSE$ and $1 - \eta_{ss}$. Redundant. |
| **Standard dynamic MPPT efficiency (EN 50530, IEC 62891)** | Discarded | Needs a PV simulator with defined irradiance profiles. Not available on our bench. |
| **ASTM E2848 / LCOE** | Discarded | Utility-scale plant acceptance and financial models; outside the scope of embedded control. |
| **Converter $\eta_{conv}$** | Discarded | Measures power stage semiconductor losses, not MPPT tracking intelligence. |

---

## 3. Required Measurements Across the Planned Test Scenarios

| Data Required | Source / Tool | Metrics Fed | Needed in Scenarios |
|---|---|---|---|
| `t`, `voltage`, `current`, `duty` per step (`RunSample`) | `RunRecord.samples` | All metrics | Scenarios 1, 2 |
| Ground-truth $P_{mpp}$ curve(s) | Pre-run `CurveRecord` sweep(s) | $\eta_{ss}, D_{trap}, T_c, nRMSE, E_{loss}$ | Scenarios 1, 2 |
| Algorithm RNG seeds / $D_0$ | Run metadata | $HR_{GMPP}$, ANOVA | Scenarios 1, 2 |
| Replayed simulation trace | `DynamicSimulatedSource` | $MAPE$ (Sim-vs-Real) | Scenarios 1, 2 |
| MCU execution cycles | RP2040 hardware timer | Computational complexity ($t_{step}$) | Firmware deployment |
