# Rationale

The *why* behind the project's design decisions. For *how the system works*,
see `general_information.md`; for *what each algorithm does*, see
`docs/algorithms/`.

## Why a control SDK at all

The Python PV ecosystem has a strong **modelling** library (`pvlib`) but no
shared **control** library. Most MPPT comparison work in the literature uses
MATLAB/Simulink with code that is rarely released and per-paper bespoke
metrics, making cross-paper comparison and sim-to-real validation hard to
reproduce. `mpp-sdk` aims to be the missing piece: a uniform
`MPPTAlgorithm.step(V, I) → D` interface so adding a controller is a one-file
change, and a comparison harness so every algorithm is measured the same way.

## Why the hardware-abstraction seam

The single most important design decision is the `SignalSource` seam. An
algorithm only sees `read() → (V, I)` and `write(D)`. This buys three things:

1. **Sim-to-real parity.** The exact same controller code runs against a
   simulated panel and against the real SEPIC board. No "simulation version"
   and "hardware version" to drift apart.
2. **Independent verification.** Each pillar (models, converters, algorithms,
   IO) is tested in isolation. A leaky abstraction shows up as a test that
   needs two pillars at once — a signal to fix the seam, not the test.
3. **A natural MCU deployment target.** The seam is exactly where the firmware
   boundary falls: the RP2040 *is* a `SignalSource` from the Pi's point of view.

## Why SEPIC

A SEPIC (Single-Ended Primary-Inductance Converter) can step the panel voltage
**up or down**, so the panel MPP voltage may sit on either side of the load
voltage without changing topology. For an academic demonstrator that sweeps a
wide irradiance range, this avoids redesigning the power stage for each
operating condition. The reflected input resistance
$R_\text{eff}(D) = R_\text{load}\left(\tfrac{1-D}{D}\right)^2$ is monotonic in
the duty cycle, giving a clean, single-valued mapping from $D$ to operating
point.

### Continuous vs discontinuous conduction mode (CCM/DCM)

In ideal Continuous Conduction Mode (CCM), the voltage transfer ratio is strictly
$V_\text{out} = V_\text{in} \cdot \frac{D}{1-D}$. However, on the physical bench,
the converter operates in Discontinuous Conduction Mode (DCM) at light loads
(high load resistance). In DCM, the inductor current falls to zero within each
switching cycle, breaking the continuous flux-balance assumption and causing the
output voltage to rise above the ideal CCM ratio.

During bench bring-up (plan 002), at a fixed commanded duty $D = 0.5$ and $V_\text{in} = 3.3\text{ V}$, the measured output voltage varied dramatically with load:
- **~3.3 V into a 10 $\Omega$ load** (matching the ideal CCM ratio $3.3 \cdot \frac{0.5}{1-0.5} = 3.3\text{ V}$)
- **~6.0 V into a 10 k$\Omega$ load** (DCM boost behavior under light load)
- **~7.0 V open-circuit** (unloaded DCM ceiling)

Understanding this operating regime transition is vital for hardware validation and characterization.

### Firmware operating modes

To simplify converter characterization on the bench without needing a host-side control loop, the RP2040 firmware supports two operating modes (`FIRMWARE_MODE`):

- **`FirmwareMode::MppTracker`**: The RP2040 acts as a pure hardware I/O proxy. The algorithm on the Raspberry Pi receives $(V, I)$ measurements and commands duty cycle $D$ over SPI. A link-lost watchdog forces $D = 0$ if SPI communication drops for $> 500\text{ ms}$.
- **`FirmwareMode::PowerSupply`**: The RP2040 operates as an autonomous closed-loop bench power supply, regulating output voltage $V_\text{out}$ to a fixed setpoint (`POWER_SUPPLY_VOUT_MV`, e.g., 12 V) using on-chip ADC feedback (`MEAS_ADC_VOUT_MV`). In this mode, the local regulator continues operating standalone even if the host SPI connection drops.

For full implementation details, setpoint configuration, and watchdog behavior, see [`firmware/pipico_board/README.md`]

## Why these algorithms, in this order

1. **P&O** — the baseline every MPPT paper compares against. Fixed-step,
   minimal state, trivially portable to an MCU.
2. **Incremental Conductance** — the other classical method; has an explicit
   "at-the-MPP" condition that reduces steady-state oscillation.
3. **Fuzzy logic** — a *local* tracker with a graduated step. Included to show
   the speed/oscillation trade-off can be eased without a panel model. It is
   **not** global, and saying so plainly is part of the contribution.
4. **Scan-and-track** and **Particle Swarm Optimization** — the genuine
   **global** MPPT methods, needed to escape the local maxima that partial
   shading creates. Scan-and-track is deterministic and the easiest to bound in
   static RAM and defend mathematically; PSO is the popular population-based
   alternative. Both ship so the paper can compare them, but scan-and-track is
   the leading candidate for the MCU port.

The ordering matters: each algorithm needs at least one predecessor to compare
against, and the metrics only become clear once several controllers run side by
side.

## Why a dynamic source, not just static

The simplest simulation jumps instantly to the operating point — a snapshot,
not a trajectory. To see *how long* an algorithm takes, whether it overshoots,
and how it oscillates, the source models the SEPIC input capacitor:

$$C\frac{dV}{dt} = I_\text{panel}(V) - \frac{V}{R_\text{eff}(D)}.$$

`DynamicSimulatedSource` integrates this each control step. This is still a
*quasi-static* electrical model (no switching ripple) — switching-level fidelity
is left to PLECS, which simulates the converter cycle by cycle. The two are
complementary: the SDK validates the **algorithm**, PLECS validates the
**hardware**.

## Why a restart policy instead of a smarter detector

Once a global tracker hands off to its local stage it is blind to new
peaks, so *something* must decide when to search again. We use two
deliberately simple mechanisms (see `methodology.md`): a step detector on
$|\Delta P|/P$ for abrupt changes, and a periodic re-search for everything
the detector cannot see (slow ramps, power-preserving peak moves). The
split is honest about information: with only $(V, I)$ at one operating
point, gradual curve reshaping is *provably* invisible, so the right tool
is a bounded-cost backstop, not a cleverer detector. Both mechanisms are a
few scalars of state, which keeps them inside the MCU portability budget.

## Why noise lives in a source wrapper

Measurement noise belongs to the acquisition chain, not to the plant or
the controller. `NoisySource` wraps any `SignalSource` and perturbs only
what the controller *sees*, which keeps models and algorithms free of
noise flags and makes the noise level an explicit, seeded experiment
parameter. The same wrapper later doubles as a bench sanity check: measure
the real sense chain's sigma, run the harness at that level, and the
simulated degradation should bracket the measured one.

## Why tabulated panels in the harness

`PvString` solves a nested bisection through a pvlib-backed solver — far too
slow to call thousands of times in a dynamic run. `TabulatedPanel` samples the
I-V curve once and interpolates thereafter, which makes the dynamic and
animated harnesses tractable without changing the physics the algorithm sees.

## On the use of AI

The project uses LLM assistance as a deliberate productivity choice under an
explicit policy (disclosed in `PLAN.md`): every change is human-reviewed,
tested, and the human author remains accountable for correctness. The framework
and scaffolding are AI-leveraged so the team's limited hours go to the original
contributions — hardware design, algorithm analysis, and experimental
validation.
