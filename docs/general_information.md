# General Information

A starting point for anyone new to the project. It explains what the system
does, how the pieces fit together, what `pvlib` contributes, and the minimum
PV theory needed to be productive.

## What this project is

`mpp-sdk` is a Python SDK for **designing, comparing, and deploying Maximum
Power Point Tracking (MPPT) algorithms** for photovoltaic (PV) systems. It
backs an Electronics Engineering thesis whose final deliverable is an
MPPT algorithm running on a microcontroller, validated end-to-end through the
same codebase that compares it against the classical methods.

The guiding principle: **the same controller code runs in simulation today and
on real hardware tomorrow**, with no changes — only the underlying source is
swapped.

## The physical system

```text
  PV panels  ──►  SEPIC converter  ──►  load
   (2× Hissuma      (DC-DC stage,         (resistor /
    in series)       duty-cycle D)          battery)
        ▲                  ▲
        │ V, I             │ PWM duty
        └──────────────────┴──► RP2040 (firmware, Rust)
                                    │ SPI
                                    ▼
                            Raspberry Pi 5 (Python SDK)
```

- **Panels:** two Hissuma PSF10MONO (10 W each) in **series**. Series wiring is
  deliberate — it is what makes partial-shading experiments meaningful (see
  *Why series* below).
- **SEPIC converter:** a DC-DC stage whose duty cycle $D$ sets the panel
  operating point. SEPIC is chosen because the panel MPP voltage can sit
  **above or below** the load voltage without changing topology.
- **RP2040 (Raspberry Pi Pico):** drives the converter PWM, reads voltage and
  current (INA226 + op-amps), and talks to the Pi over SPI. Firmware is in
  **Rust**. It is also the deployment target for the final algorithm.
- **Raspberry Pi 5:** hosts the Python SDK and the algorithm during
  hardware-in-the-loop (HIL) testing.

## The four SDK pillars

The library is decoupled into four pillars, each verifiable in isolation:

| Pillar          | Package              | What it provides                                   |
| --------------- | -------------------- | -------------------------------------------------- |
| **Models**      | `mpp_sdk.models`     | Panel I-V models (ideal, pvlib-backed, string)     |
| **Converters**  | `mpp_sdk.converters` | Power-stage models (`SEPICConverter`)              |
| **Algorithms**  | `mpp_sdk.algorithms` | MPPT controllers (`PerturbAndObserve`, `FuzzyLogic`, …) |
| **IO**          | `mpp_sdk.io`         | Hardware-abstraction seam (`SignalSource`)         |

The seam is `SignalSource`: an algorithm only ever calls `read() → (V, I)` and
`write(D)`. Whether that is a simulation or a real board is invisible to it.

## Minimum PV theory

A solar panel's current–voltage (I-V) relationship follows the **single-diode
model**:

$$I(V) = I_\text{ph} - I_0\left(e^{V/(n V_t)} - 1\right) - \frac{V + I R_s}{R_{sh}},$$

where $I_\text{ph}$ is the light-generated (photo) current, $I_0$ the diode
saturation current, $R_s, R_{sh}$ the series/shunt resistances, and $V_t$ the
thermal voltage. The key consequences:

- **Short circuit:** at $V=0$, $I \approx I_\text{sc}$ (proportional to irradiance).
- **Open circuit:** at $I=0$, $V = V_\text{oc}$ (falls with temperature).
- **Maximum power point (MPP):** the single $(V_\text{mp}, I_\text{mp})$ where
  $P = VI$ peaks. MPPT's whole job is to *find and hold* this point as
  irradiance and temperature change.

**Power curve:** $P(V) = V\cdot I(V)$ is bell-shaped with one peak — *under
uniform light*. The MPP moves with conditions, which is why a closed-loop
tracker is needed rather than a fixed operating point.

## What pvlib contributes

[`pvlib`](https://pvlib-python.readthedocs.io/) is the de-facto open-source
library for PV **performance modelling**. It provides validated single- and
two-diode I-V solvers, temperature/irradiance models, and the `bishop88`
partial-shading method.

What pvlib does **not** provide: closed-loop MPPT controllers, time-stepping
control simulation, or any hardware abstraction. It returns *the* MPP for a
given panel and environment — not a controller that discovers it from a stream
of $(V, I)$ measurements.

`mpp-sdk` fills exactly that gap and **adopts** pvlib rather than competing with
it: `PvlibPanelModel` wraps pvlib's solver behind the SDK's `PanelModel`
interface, so controllers benefit from validated panel physics without
re-implementing them. We fit the De Soto 5-parameter model from the panel's
datasheet values (Voc, Isc, Vmp, Imp + temperature coefficients).

## Why series (partial shading)

Two panels in **series** share one current. When one is shaded, its bypass
diode conducts over part of the curve, producing a **multi-peak** P-V curve.
Classical trackers (P&O, InCond, fuzzy) follow the local gradient and can get
**stuck on a local maximum** — losing power. This is the motivation for a
*global* MPPT method (scan-and-track), and the series string is what lets us
demonstrate it. Two panels in **parallel** would keep a single-peak curve and
hide the effect.

Hardware limits for the series string: $V_\text{oc} \approx 34$ V,
$I_\text{sc} \approx 0.79$ A — the SEPIC is designed for $\le 40$ V, $\le 1$ A.

## Getting started

```bash
uv sync --extra pvlib            # install with the pvlib adapter
uv run harness/compare_static.py # full-sun vs partial-shade comparison
uv run harness/animate.py --shade --duty 0.1   # watch the local-maximum trap
uv run pytest -q                 # run the test suite
```

See `docs/algorithms/` for one-page references on each MPPT method and
`docs/rationale.md` for the design decisions behind the project.
