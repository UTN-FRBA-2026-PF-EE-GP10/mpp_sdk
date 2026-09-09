# Rationale

The *why* behind the project's design decisions. For *how the system works*,
see `general_information.md`; for *what each algorithm does*, see
`docs/algorithms/`.

## Why a control SDK at all

The Python PV ecosystem has a strong **modelling** library (`pvlib`) but no
shared **control** library. Most MPPT comparison work in the literature
uses MATLAB/Simulink, with code that is rarely released and per-paper
bespoke metrics. That makes cross-paper comparison and sim-to-real
validation hard to reproduce. `mpp-sdk` is the missing piece: a uniform
`MPPTAlgorithm.step(V, I) → D` interface, so adding a controller is a
one-file change, plus a comparison harness that measures every algorithm
the same way.

## Why the hardware-abstraction seam

The single most important design decision is the `SignalSource` seam. An
algorithm only sees `read() → (V, I)` and `write(D)`. This buys three
things:

1. **Sim-to-real parity.** The same controller code runs against a
   simulated panel and against the real SEPIC board. There is no separate
   "simulation version" and "hardware version" to drift apart.
2. **Independent verification.** Each pillar (models, converters,
   algorithms, IO) is tested in isolation. A test that needs two pillars
   at once means the abstraction leaks — fix the seam, not the test.
3. **A natural MCU deployment target.** The seam sits exactly where the
   firmware boundary falls: from the Pi's point of view, the RP2040 *is*
   a `SignalSource`.

## Why SEPIC

A SEPIC (Single-Ended Primary-Inductance Converter) can step the panel
voltage **up or down**. The panel MPP voltage can sit on either side of
the load voltage, with no change in topology. For a demonstrator that
sweeps a wide irradiance range, this avoids redesigning the power stage
for each operating condition. The reflected input resistance
$R_\text{eff}(D) = R_\text{load}\left(\tfrac{1-D}{D}\right)^2$ is
monotonic in the duty cycle. That gives a clean, single-valued mapping
from $D$ to the operating point.

### Continuous vs discontinuous conduction mode (CCM/DCM)

In ideal Continuous Conduction Mode (CCM), the voltage transfer ratio is
strictly $V_\text{out} = V_\text{in} \cdot \frac{D}{1-D}$. On the physical
bench, the converter runs in Discontinuous Conduction Mode (DCM) at light
loads (high load resistance). In DCM, the inductor current falls to zero
within each switching cycle. That breaks the continuous flux-balance
assumption and pushes the output voltage above the ideal CCM ratio.

During bench bring-up (plan 002), at a fixed commanded duty $D = 0.5$ and
$V_\text{in} = 3.3\text{ V}$, the measured output voltage varied a lot
with load:

- **~3.3 V into a 10 $\Omega$ load** — matches the ideal CCM ratio
  $3.3 \cdot \frac{0.5}{1-0.5} = 3.3\text{ V}$.
- **~6.0 V into a 10 k$\Omega$ load** — DCM boost behavior under light
  load.
- **~7.0 V open-circuit** — the unloaded DCM ceiling.

Knowing this regime transition matters for hardware validation and
characterization.

### Firmware operating modes

To simplify converter characterization on the bench, with no host-side
control loop needed, the RP2040 firmware has two operating modes
(`FIRMWARE_MODE`):

- **`FirmwareMode::MppTracker`**: the RP2040 acts as a pure hardware I/O
  proxy. The algorithm on the Raspberry Pi reads $(V, I)$ and commands the
  duty cycle $D$ over SPI. A link-lost watchdog forces $D = 0$ if SPI
  communication drops for more than 500 ms.
- **`FirmwareMode::PowerSupply`**: the RP2040 runs as an autonomous
  closed-loop bench power supply. It regulates output voltage
  $V_\text{out}$ to a fixed setpoint (`POWER_SUPPLY_VOUT_MV`, e.g. 12 V)
  using on-chip ADC feedback (`MEAS_ADC_VOUT_MV`). In this mode the local
  regulator keeps running even if the host SPI connection drops.

For implementation details, setpoint configuration, and watchdog
behavior — including the `ClosedLoop` feed-forward-plus-trim algorithm —
see [`firmware/pipico_board/README.md`'s "Operating Modes"
section](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/blob/main/firmware/pipico_board/README.md#operating-modes).
That file lives outside `docs/`, so it is linked directly on GitHub.

## Why these algorithms, in this order

1. **P&O** — the baseline every MPPT paper compares against. Fixed-step,
   minimal state, trivial to port to an MCU.
2. **Incremental Conductance** — the other classical method. It has an
   explicit "at-the-MPP" condition that reduces steady-state oscillation.
3. **Fuzzy logic** — a *local* tracker with a graduated step. It shows
   that the speed/oscillation trade-off can be eased without a panel
   model. It is **not** global, and saying so plainly is part of the
   contribution.
4. **Scan-and-track** and **Particle Swarm Optimization** — the genuine
   **global** MPPT methods, needed to escape the local maxima that
   partial shading creates. Scan-and-track is deterministic, and the
   easiest to bound in static RAM and defend mathematically. PSO is the
   popular population-based alternative. Both ship so the paper can
   compare them, but scan-and-track is the leading candidate for the MCU
   port.

The order matters: each algorithm needs at least one predecessor to
compare against, and the metrics only make sense once several
controllers run side by side.

## Why a dynamic source, not just static

The simplest simulation jumps instantly to the operating point: a
snapshot, not a trajectory. To see *how long* an algorithm takes, whether
it overshoots, and how it oscillates, the source models the SEPIC input
capacitor:

$$C\frac{dV}{dt} = I_\text{panel}(V) - \frac{V}{R_\text{eff}(D)}.$$

`DynamicSimulatedSource` integrates this each control step. This is still
a *quasi-static* electrical model, with no switching ripple. Switching-
level fidelity is PLECS's job — it simulates the converter cycle by
cycle. The two are complementary: the SDK validates the **algorithm**,
PLECS validates the **hardware**.

## Why a restart policy instead of a smarter detector

Once a global tracker hands off to its local stage, it is blind to new
peaks. So *something* must decide when to search again. We use two
deliberately simple mechanisms (see `methodology.md`): a step detector on
$|\Delta P|/P$ for abrupt changes, and a periodic re-search for
everything the detector cannot see (slow ramps, power-preserving peak
moves). The split is honest about what the controller can know: with
only $(V, I)$ at one operating point, gradual curve reshaping is
*provably* invisible. So the right tool is a bounded-cost backstop, not a
cleverer detector. Both mechanisms need only a few scalars of state,
which keeps them inside the MCU portability budget.

## Why noise lives in a source wrapper

Measurement noise belongs to the acquisition chain, not the plant or the
controller. `NoisySource` wraps any `SignalSource` and perturbs only what
the controller *sees*. That keeps models and algorithms free of noise
flags, and makes the noise level an explicit, seeded experiment
parameter. The same wrapper doubles as a bench sanity check later:
measure the real sense chain's sigma, run the harness at that level, and
the simulated degradation should bracket the measured one.

## Why tabulated panels in the harness

`PvString` solves a nested bisection through a pvlib-backed solver — far
too slow to call thousands of times in a dynamic run. `TabulatedPanel`
samples the I-V curve once and interpolates after that. This makes the
dynamic and animated harnesses fast enough to use, with no change to the
physics the algorithm sees.

## On the use of AI

The project uses LLM assistance as a deliberate productivity choice,
under an explicit policy (disclosed in `PLAN.md`): every change is
human-reviewed and tested, and the human author stays accountable for
correctness. The framework and scaffolding are AI-leveraged so the
team's limited hours go to the original contributions: hardware design,
algorithm analysis, and experimental validation.
