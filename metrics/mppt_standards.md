# International Standards for MPPT Evaluation

Summary of the three main normative frameworks for evaluating MPPT algorithms,
based on the comparative analysis *"Comparación Crítica de Normas MPPT en
Sistemas Fotovoltaicos"* (Critical Comparison of MPPT Standards in Photovoltaic
Systems) (`papers/Comparacion_Critica_de_Normas_MPPT_en_Sistemas_Fot.pdf`).

---

## 1. EN 50530:2018

**Scope:** evaluates the **inverter** only (not the complete system). It is the
strictest standard for characterising the core of an MPPT algorithm in the
laboratory.

### Metrics

**Static efficiency:**

$$\eta_{stat} = \frac{P_{dc,measured}}{P_{mpp,simulator}}$$

Measured in steady state at 7 power levels (5 %, 10 %, 20 %, 30 %, 50 %, 75 %,
100 % of nominal) and multiple voltage levels. The goal is to map how the
algorithm behaves at different operating points of the panel.

**Dynamic efficiency:**

$$\eta_{dyn} = \frac{\int P_{dc}\,dt}{\int P_{mpp}\,dt} \times 100\%$$

Measured during synthetic **irradiance ramps** with defined slopes between 0.5
and 100 W/(m²·s). These ramps represent transitions such as a passing cloud. The
profiles are defined in Annex B of the standard.

**Weighted efficiency (CEC/EUR):**

To obtain a single number representative of annual performance, the standard
weights η_stat at different load levels with standardised factors:

$$\eta_{CEC} = \sum a_i \cdot \eta_i$$

| Power level | CEC weight | EUR weight |
|:-:|:-:|:-:|
| 5 % | — | 0.03 |
| 10 % | 0.04 | 0.06 |
| 20 % | 0.05 | 0.13 |
| 30 % | 0.12 | 0.10 |
| 50 % | 0.21 | 0.48 |
| 75 % | 0.53 | 0.20 |
| 100 % | 0.05 | — |

The CEC weights reflect the climate of California (lots of sun → high weight at
75 %); the EUR weights reflect central Europe (more hours at medium power →
high weight at 50 %).

### Test requirements

| Parameter | Value |
|-----------|-------|
| Sampling frequency | ≥ 10 Hz |
| Maximum uncertainty | ≤ 0.5 % |
| Inter-lab reproducibility | CV < 0.25 % |
| Test temperature | T = 25 °C fixed (static) |
| Dynamic profiles | Synthetic ramps (Annex B) |

### Limitations

- Focuses exclusively on the inverter → ignores losses from mismatch between
  modules, partial shading or multi-MPPT configurations.
- Does not address P-V curves with multiple local maxima (partial shading).
- Temperature fixed at 25 °C → does not capture degradation from heating.
- Does not link the efficiency metrics to economic indicators (LCOE).

---

## 2. IEC 62816:2014

**Scope:** evaluates the **complete system** (modules + inverter). It is the
standard with the best balance between technical rigour and representativeness
of real conditions.

### Main metric: εTL (Tracking Loss)

$$\varepsilon_{TL} = \frac{E_{mpp} - E_{dc}}{E_{mpp}} \times 100\%$$

Quantifies the **energy loss** caused by imperfections in tracking the MPP. It is
the complement of the energy efficiency:

$$\varepsilon_{TL} = (1 - \eta_{energy}) \times 100\%$$

The standard classifies algorithms into categories according to εTL:

| Class | εTL |
|:-----:|:---:|
| A | < 1 % |
| B | 1 – 2 % |
| C | 2 – 5 % |
| D | 5 – 10 % |
| E | > 10 % |

**Main advantage:** εTL translates directly into energy not generated
(kWh/year) and therefore into economic impact ($/year). If a 1 kW system with a
20 % capacity factor has εTL = 2 %, it loses ~3.5 kWh/year — scaled to MW, the
differences are significant.

### Methodological approach

Unlike EN 50530, IEC 62816 allows:

- Using **real time series** recorded in situ (not only synthetic ramps).
- Evaluating the complete system including modules, cabling and inverter.
- Capturing the effect of partial shading (generic reference).

### Test requirements

| Parameter | Value |
|-----------|-------|
| Sampling frequency | ≥ 1 Hz |
| Maximum uncertainty | ≤ 1 % |
| Inter-lab reproducibility | CV < 0.40 % |
| Test temperature | Real T, measured |
| Minimum duration | Until covering 90 % of annual variability |

### Limitations

- Lower time resolution (≥ 1 Hz vs. ≥ 10 Hz for EN 50530) → can mask
  ultra-fast transients.
- Makes it hard to tell fast-response algorithms apart in scenarios with very
  abrupt changes.

---

## 3. ASTM E2848

**Scope:** evaluates the **complete plant** (large-scale photovoltaic system).
It prioritises simplicity and low implementation cost.

### Metric: regression model

$$P_{model} = a_1 + a_2 \cdot E + a_3 \cdot T_{ambient} + a_4 \cdot v_{wind}$$

where E is the irradiance, T_ambient the ambient temperature and v_wind the wind
speed. The coefficients are determined statistically from historical field data.

It does not define a tracking efficiency metric per se — it infers the loss as
the difference between the power predicted by the model and the measured power.

### Test requirements

| Parameter | Value |
|-----------|-------|
| Sampling frequency | 1/60 Hz (1-min averages) |
| Maximum uncertainty | Not set (σ ≈ 1.1 %) |
| Inter-lab reproducibility | Not set |
| Minimum duration | 3 – 30 field days |

### Limitations

- 1-minute time resolution → completely smooths out the transients of the MPPT
  algorithm.
- High dispersion of results (σ ≈ 1.1 %) → makes inter-laboratory comparison
  difficult.
- **Unsuitable for comparing individual MPPT algorithms** — its purpose is
  plant-level performance characterisation for annual projections.

---

## 4. Consolidated comparison

| Criterion | EN 50530 | IEC 62816 | ASTM E2848 |
|----------|:--------:|:---------:|:----------:|
| **Scope** | Inverter | System | Plant |
| **Metric** | η_dyn | εTL | P_model |
| **Minimum f_s** | ≥ 10 Hz | ≥ 1 Hz | 1/60 Hz |
| **Uncertainty** | ≤ 0.5 % | ≤ 1 % | ~1.1 % |
| **Reproducibility** | CV < 0.25 % | CV < 0.40 % | Not set |
| **Multi-MPPT** | No | Yes | Partial |
| **Partial shading** | No | Generic reference | No |
| **Temperature** | 25 °C fixed | Real T | T_amb in regression |
| **Economic indicators** | No | No | No |
| **Metrological traceability** | Yes | Yes | Recommended |

### Main gap (Type I)

None of the three standards links the performance metrics (η_dyn, εTL) to
economic indicators such as LCOE. According to the comparison paper, this
disconnect:

- Weakens the commercial case for adopting more advanced algorithms.
- Leaves the economic value of MPPT efficiency improvements unquantified.
- The difference of up to **0.7 % absolute** in the efficiency reported for the
  same algorithm (depending on the standard) can change the ranking in
  tenders and has a direct economic impact.

### Partial shading gap

No standard provides a standardised procedure for evaluating behaviour on
multi-peak P-V curves (partial shading). This is precisely what our cyclic
harness (`compare_cyclic.py`) does: it generates partial-shading profiles with
multiple local maxima and evaluates the escape capability of the global
algorithms.

---

## 5. Applicability to our project

| Aspect | EN 50530 / IEC 62816 | Our Implementation & Bench Scenarios |
|---------|----------|----------|
| Sampling frequency | ≥ 10 Hz (EN 50530) / ≥ 1 Hz (IEC 62816) | 1 kHz (sim) / ~22 Hz (~46 ms, hardware HIL) ✅ |
| Dynamic profiles | Synthetic ramps | Simulation: cyclic profile with ramps. Hardware: **Scenario 3 (repeatable stepped dimmer profile)** ✅ |
| Partial shading | Not covered (EN 50530) / Generic (IEC) | **Scenario 2**: `PvString` with bypass diodes, 2 panels @ 45° tilt (multi-peak P-V curve) ✅ |
| Dynamic efficiency | η_dyn | `energy_efficiency()` ≡ η_dyn (scored against pre-calibrated dimmer plateau sweeps) ✅ |
| Tracking loss | εTL = 1 - η_dyn | Calculated as 1 - η_E on our dimmer profile ✅ |
| Test T | 25 °C fixed | Simulation: configurable. Hardware: real T measured via thermocouple ✅ |

> [!NOTE]
> We are evaluating the **isolated MPPT algorithm** running on a SEPIC converter,
> not a complete commercial grid-tied inverter. By implementing **Scenario 3 (repeatable stepped dimmer profile)**,
> we apply the core principles of dynamic tracking characterization from EN 50530 and IEC 62816
> directly to our physical bench without requiring an industrial solar simulator.

---

## 6. References

- EN 50530:2018. *Overall efficiency of grid connected photovoltaic inverters.*

- IEC 62816:2014. *Photovoltaic systems — Test procedure of MPPT performance.*

- ASTM E2848. *Standard test method for reporting photovoltaic non-concentrator
  system performance.*

- *Comparación Crítica de Normas MPPT en Sistemas Fotovoltaicos.*
  → `papers/Comparacion_Critica_de_Normas_MPPT_en_Sistemas_Fot.pdf`

- Femia, N. et al. (2017). *Power Electronics and Control Techniques for
  Maximum Energy Harvesting in Photovoltaic Systems.* CRC Press.
  → `papers/2017_Book_EnergyHarvestingAndEnergyEffic.pdf`
