# Plan 036: The board as a control-theory learning platform (PID -> optimal control + observer -> Kalman filter)

> **Executor instructions**: Read this whole plan before starting - it is
> a **staged spike**, not a uniform to-do list. Stage 0 and Stage 1 are
> specified to the same executable, verifiable detail as this repo's other
> plans. Stages 2 and 3 are **deliberately not** specified to that detail -
> they are a feasibility investigation with a recommended path, because
> committing to an implementation-ready LQR/observer/Kalman design before
> Stage 1's simulation groundwork exists would be guessing, not planning.
> Follow the "STOP conditions" and "Decision gates" sections closely -
> this plan expects you to stop and report at defined checkpoints, not
> push straight through to a finished Kalman filter.
>
> When done with whatever stage you reach, update the status row for this
> plan in `improve/2026-07-18/plans/README.md` (do not otherwise edit that
> file) - note exactly which stage was reached, since this plan will very
> likely be picked up and put down across multiple sessions.
>
> **Drift check (run first)**: `git diff --stat 742e9e7..HEAD --
> firmware/pipico_board/src/mode_power_supply.rs
> mpp_sdk/converters/sepic.py mpp_sdk/io/dynamic.py mpp_sdk/io/noisy.py`.
> If any of these changed since this plan was written, re-read them in
> full before proceeding; on a mismatch with the excerpts below, treat it
> as a STOP condition for whichever stage that file affects.

## Status

- **Priority**: P3 - this is an educational/exploratory use of hardware
  built for a different primary purpose (the MPPT thesis), not a
  replacement for `mpp_sdk.algorithms`'s MPPT controllers. It has real
  value (a working SEPIC with real sensing and real noise is a genuinely
  good hands-on control-theory demonstrator, and the classical-vs-modern
  comparison could make a strong thesis discussion chapter), but it does
  not block or compete with the MPPT deliverable.
- **Effort**: L overall, but front-loaded: Stage 1 (PID) is M on its own
  and fully specified; Stages 2-3 are explicitly open-ended research, not
  estimated to S/M/L with any confidence yet - see each stage's own note.
- **Risk**: MED-HIGH once real hardware is involved (Stage 1's on-target
  step and any hardware work in Stage 2) - a mistuned PID or an
  incorrectly-derived state-feedback gain is a real way to drive a real
  SEPIC's voltage or current somewhere bad. Every on-target step in this
  plan requires the same board-limit safety abort pattern as plan 034 -
  see "Safety" below, non-negotiable.
- **Depends on**: none structurally, but plan 034
  (`improve/2026-07-18/plans/034-hardware-mppt-runs.md`) already builds
  the `run_control_loop`-style safety-abort pattern this plan reuses -
  if 034 has landed, Stage 1's on-target step should reuse its abort
  logic rather than reimplementing it; if not, Stage 1 implements its own
  copy (see Stage 1, Step 4).
- **Category**: feature / spike (operator request, not the September
  audit).
- **Planned at**: commit `742e9e7`, 2026-09-08.

## Why this matters

This project's MPPT algorithms (`mpp_sdk.algorithms`) are all **heuristic
hill-climbers or search methods** (P&O, IncCond, Fuzzy, ScanAndTrack, PSO),
none of them formal control theory in the classical or modern sense.
The board underneath them, though, is a real physical plant: a SEPIC
converter with real sensing (INA229 for panel-side V/I, on-chip ADC for
`Vout`), real actuation (a hardware PWM gate), and a real closed-loop mode
already running on it today
(`firmware/pipico_board/src/mode_power_supply.rs`'s `PowerSupply` mode)
that is itself not a textbook controller - see "Current state" below. That
is a genuinely good, already-built platform to demonstrate, in order of
sophistication:

1. **Classical control (PID)** - does a real, tunable three-term
   controller out-regulate the ad hoc step-based law already on this
   board?
2. **Modern/optimal control (state feedback + an observer)** - the SEPIC
   has internal states (inductor currents, the coupling capacitor voltage)
   that this board **cannot measure directly** (no inductor-current
   sensing exists in the schematic at all) - this is not a contrived
   classroom example of "why you need an observer," it is this board's
   actual physical constraint.
3. **Stochastic estimation (a Kalman filter)** - the same observer
   problem, but optimal under the sensor noise this project already
   characterizes elsewhere (`mpp_sdk.io.noisy.NoisySource`,
   `docs/methodology.md`'s "Measurement noise" section).

Nothing in `docs/`, `AGENTS.md`, or `PLAN.md` mentions PID, optimal
control, state-space, observers, or Kalman filtering anywhere (confirmed:
`grep -in "PID\|kalman\|observer\|optimal control\|state.space\|LQR"
docs/*.md AGENTS.md PLAN.md` returns nothing) - this is genuinely new
scope for the project, not a rediscovery of a rejected idea.

## Current state

### The existing closed-loop controller is not a PID

`mode_power_supply.rs`'s `ClosedLoopState::step` (the `PowerSupply`
firmware mode's regulator, `POWER_SUPPLY_LOOP = PowerSupplyLoop::ClosedLoop`
by default):

```rust
fn step(&mut self) -> u16 {
    // ... gated on a fresh ADC sample (~10 Hz) ...
    if !self.seeded {
        // one-shot feed-forward jump using the ideal lossless SEPIC ratio
        // D = Vout / (Vin + Vout), then falls through to proportional trim
    }
    let vout_mv = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
    if vout_mv < POWER_SUPPLY_VOUT_MV {
        let step = ((POWER_SUPPLY_VOUT_MV - vout_mv) / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
        self.ps_duty = self.ps_duty.saturating_add(step).min(DUTY_MAX);
    } else if vout_mv > POWER_SUPPLY_VOUT_MV {
        let step = ((vout_mv - POWER_SUPPLY_VOUT_MV) / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
        self.ps_duty = self.ps_duty.saturating_sub(step);
    }
    self.ps_duty
}
```

This is: a one-time open-loop feed-forward jump, then a **clamped
incremental step proportional to error** (`GAIN_DIVISOR = 20`,
`MIN_STEP = 1`, `MAX_STEP = 800` duty counts out of 65535), applied once
per ~10 Hz ADC sample. Its own comment says the gains were "tuned on-target -
both bench trim speed and load-step recovery were too slow at the initial
50/200" - i.e. hand-tuned by trial and error, no derivative term,
no explicit integral gain (though the accumulation itself behaves a bit
like one), no formal margin/bandwidth analysis. **This is Stage 1's
baseline to beat**, not something to delete - keep it selectable
alongside a real PID for A/B comparison on the same board (see Stage 1's
design).

### The software plant model has no internal SEPIC states

`mpp_sdk/converters/sepic.py`'s `SEPICConverter` is a **static,
steady-state** model - `reflected_resistance(duty, load_resistance)`
computes `R_load * ((1-D)/D)^2` and nothing else; there is no inductor or
capacitor state anywhere in this class. `mpp_sdk/io/dynamic.py`'s
`DynamicSimulatedSource` adds exactly **one** dynamic state - the panel-
side terminal voltage, via `C * dV/dt = I_panel(V) - V/R_eff(D)` - and
treats the converter itself as instantaneously at steady state for any
given `D`. **Neither model represents the SEPIC's own internal dynamics**
(inductor currents `iL1`/`iL2`, the coupling capacitor voltage `vC1`, or
`vout`'s own capacitor dynamics beyond the lumped input-side `RC`) - this
is the single biggest feasibility gate for Stage 2, spelled out there.

### What the hardware can and cannot measure

Confirmed via `main.rs`'s static list and
`firmware/pipico_board/README.md`'s "Sensing" section:

- `MEAS_V_MV`/`MEAS_I_MA` (INA229, SPI0): panel-side voltage/current -
  calibrated, trustworthy.
- `MEAS_ADC_VOUT_MV` (on-chip ADC): output voltage - calibrated.
- `MEAS_ADC_PWR_MV`/`MEAS_ADC_IIN_MV`: partially calibrated per plan 010
  (`Input_Curr`'s INA281 gain/shunt still unresolved) - do not build a
  Stage 2/3 design around `Input_Curr` being trustworthy without
  re-checking plan 010's status first.
- **Nothing measures either inductor's current, or the coupling
  capacitor's voltage, directly.** This is a schematic-level fact (no
  current-sense element exists on either inductor), not a firmware
  gap that could be closed by writing more code - it is the actual reason
  an observer is not optional if a full-state design is wanted.

### `NoisySource` already exists for Stage 3

`mpp_sdk/io/noisy.py`'s `NoisySource` wraps any `SignalSource` and adds
seeded Gaussian noise to `(V, I)`, specified as absolute standard
deviations - already the exact tool `docs/methodology.md`'s "Measurement
noise" section uses to characterize the noise floor where simple
controllers degrade (the cliff between 0.25%-0.5% of full-scale, on this
project's 40 V/1 A hardware full scale). Stage 3 reuses this noise
characterization rather than inventing a new one.

## Safety (applies to every on-target step in this plan)

Same reasoning as plan 034's "Safety" section, restated because it
applies here independently: **any on-target test of a new control law
(PID gains, a state-feedback gain matrix) must have a client-side or
firmware-side abort if `voltage > 40.0` or `current > 1.0`** (the board's
documented limits, `docs/general_information.md`). If plan 034 has landed
by the time you execute Stage 1, reuse its `run_control_loop`-style
pattern (or the firmware-side equivalent, if this experiment runs
autonomously in `PowerSupply` mode rather than being driven by the Pi) -
do not skip this because "it's just a PID, how bad could it be" - an
under-damped or unstable gain choice on a real SEPIC is exactly how bad it
could be.

## Stage 0: baseline characterization (do this first, always)

Before comparing anything to anything, quantify what `ClosedLoopState`
already does today. This stage is small and has no open design questions,
unlike Stages 2-3.

**Scope**: `harness/` (new, small module or script) + `tests/`.

**Design**: `mpp_sdk.metrics`'s existing functions
(`tracking_efficiency`, `settling_time`, etc.) are power/MPP-oriented
(they compare captured power against `P_mpp`) - wrong objective for a
voltage-regulation loop. Add a small, separate set of step-response
metrics instead (do not force-fit the existing ones): rise time (10%-90%
of the step), percent overshoot, 2% settling time, and steady-state error -
all standard, textbook definitions, computed from a `(t, v)` or `(t, D)`
trace the same shape as `RunSample` (if plan 034 has landed, reuse
`mpp_sdk.runs.RunSample`'s shape for consistency; if not, a plain list of
`(t, v)` tuples is fine).

**Steps**:

1. In simulation first: build a `DynamicSimulatedSource`-driven harness
   script (mirror `harness/compare_dynamic.py`'s general shape) that
   applies a step change (either a reference-voltage step, if you port
   `ClosedLoopState`'s law to Python for this, or a load-resistance step
   against a fixed duty, to characterize the *plant* alone first) and
   records the response.
2. Add the four step-response metrics as small, pure functions (with
   tests) - either in a new `mpp_sdk/metrics.py` section (if they're
   judged reusable enough to belong there) or a `harness`-local helper
   module if they're too voltage-loop-specific for the SDK's public
   metrics surface - **make this call yourself based on how the functions
   end up looking, don't guess upfront.**
3. On the bench (needs the board): run `PowerSupply`/`ClosedLoop` mode,
   apply a real load step (swap the load resistor, or use a programmable
   load if the bench has one), and log `Vout` over time - by hand via
   `spi_test.py`-style polling if nothing better exists yet, or via
   whatever plan 034 provides if it has landed and can be pointed at
   `PowerSupply` mode's telemetry instead of `MppTracker`'s duty control
   (check whether that's even meaningful - plan 034's `run_control_loop`
   assumes `MppTracker` mode's algorithm-drives-duty model, which doesn't
   apply to `PowerSupply` mode's autonomous on-target loop; you may need a
   simpler bespoke logging script here rather than forcing plan 034's tool
   to fit a mode it wasn't designed for).
4. Compute and record the four metrics for the real, on-target
   `ClosedLoopState` - this number is what Stage 1's PID must beat to be
   worth keeping.

**Done criteria**: a written baseline (rise time / overshoot / settling
time / steady-state error, both simulated-plant and real-hardware
numbers) recorded in this plan file's own "Maintenance notes" or a linked
short report - not just implied.

## Stage 1: PID (fully specified, buildable now)

**Scope**: a new Python `PidController` (design below) +
`firmware/pipico_board/src/mode_power_supply.rs` (new
`PowerSupplyLoop::Pid` variant, `ClosedLoop` kept as-is for comparison) +
tests.

### Design

A textbook discrete PID, position form, with output clamping and
**anti-windup** (freeze the integral term while the output is saturated -
without this, a PID that saturates the duty clamp will wind up its
integral term and overshoot badly on recovery, a classical and well-known
failure mode that would otherwise make this comparison unfair to PID):

```python
class PidController:
    """Discrete PID with clamped output and conditional-integration
    anti-windup. Not an MPPTAlgorithm (mpp_sdk.algorithms) - this
    regulates a voltage/current setpoint (mode_power_supply.rs's job),
    not maximum-power-point tracking, a different control objective."""

    def __init__(self, kp: float, ki: float, kd: float, *, dt: float,
                 output_min: float = 0.0, output_max: float = 1.0) -> None:
        ...

    def step(self, setpoint: float, measurement: float) -> float:
        """Return the next control output (e.g. duty cycle)."""
        error = setpoint - measurement
        # proportional, integral (frozen if the last output saturated),
        # derivative (on measurement, not on error, to avoid derivative
        # kick on a setpoint step) - implement the standard forms, this
        # is not a novel algorithm, just implement it correctly and test
        # the anti-windup behavior explicitly (see Step 3).
        ...
```

Home for this: **not** `mpp_sdk/algorithms/` (that package is specifically
the MPPT-tracker registry per AGENTS.md - `MPPTAlgorithm.step(V, I) -> D`
answers a different question than "regulate this measurement to this
setpoint"). Create `mpp_sdk/control/` as a new, small, sibling package
(mirrors the existing pillar structure - `models/`, `converters/`,
`algorithms/`, `io/`, now `control/`) with `pid.py`. This is a real,
minor architectural addition - note it in `AGENTS.md`'s "Architectural
pillars" section if this plan lands (a one-line addition, not a
restructure).

### Steps

1. **`mpp_sdk/control/__init__.py` + `pid.py`** per the design above.
   Include the standard anti-windup and derivative-on-measurement
   details - both are well-documented, non-controversial textbook
   choices (cite, e.g., Åström & Murray's *Feedback Systems*, ch. 11, or
   any standard controls text - do not need to re-derive from scratch,
   just implement correctly).
2. **Tests** (`tests/test_pid.py`): a pure step-response test against a
   simple first-order plant (not the full SEPIC model - isolate the PID's
   own correctness first): confirm it converges to the setpoint, confirm
   anti-windup actually prevents overshoot growth when the output
   saturates for a while (construct a case that would wind up an
   integrator without the guard, assert the guarded version doesn't), and
   confirm output stays within `[output_min, output_max]` always.
3. **Simulation validation against the real plant model**: a new harness
   script (or extend Stage 0's) driving `DynamicSimulatedSource` with
   `PidController` instead of `ClosedLoopState`'s law (port the Rust law
   to Python too, or just compare against Stage 0's recorded numbers) -
   tune `Kp`/`Ki`/`Kd` here, in simulation, where a bad gain choice costs
   nothing. Compare against Stage 0's baseline metrics.
4. **Port to firmware**: add `PowerSupplyLoop::Pid` to
   `mode_power_supply.rs`'s enum, alongside `OpenLoop`/`ClosedLoop` (not
   replacing `ClosedLoop` - keep both selectable via
   `POWER_SUPPLY_LOOP`'s constant, so on-target A/B testing stays
   possible). Implement the same discrete PID difference equation,
   fixed-point or `f32` (check what the rest of `mode_power_supply.rs`
   uses - match it, don't introduce a new numeric convention). Add the
   same safety-abort reasoning as plan 034 if this loop can be driven
   continuously without supervision - at minimum, keep `DUTY_MAX`'s
   existing 95% clamp, and consider whether a `Vout`/`Iin` hard cutoff
   (mirroring `TRACER_I_MAX_MA`/`TRACER_P_MAX_MW`) belongs in
   `mode_power_supply.rs` now that a second, less battle-tested control
   law lives there too - **this is worth a STOP-and-discuss with the
   operator before wiring an untested gain set to unsupervised continuous
   operation on real hardware**, not something to decide unilaterally.
5. **On-target validation**: same load-step test as Stage 0, with
   `PowerSupplyLoop::Pid` selected. Compute the same four metrics, compare
   against Stage 0's `ClosedLoop` baseline. Report the comparison
   honestly - "PID wasn't actually better" is a valid, useful outcome for
   a learning exercise, not a plan failure.

**Decision gate before Stage 2**: only proceed to Stage 2 if Stage 1's
simulation results (Step 3) are working and someone wants to invest in
Stage 2's model-building work specifically. Stage 1 alone (a real,
working, on-target-validated PID replacing an ad hoc step law) is a
complete, useful, shippable outcome on its own - do not feel obligated to
continue to Stage 2 just because this plan describes it.

## Stage 2: optimal control + observer (feasibility spike - NOT implementation-ready)

**This section intentionally stops short of a step-by-step build plan.**
What follows is the investigation a control engineer needs to do before
this becomes executable, plus the specific prerequisites this repo is
missing. Treat this as a research assignment, not a checklist.

### What needs to happen, in order

1. **Derive the full-order averaged small-signal SEPIC model.** Four
   states are standard for a SEPIC in CCM: both inductor currents
   (`iL1`, `iL2`), the coupling capacitor voltage (`vC1`), and the output
   capacitor voltage (`vC2 = vout`). This is a known, standard state-space-
   averaging derivation (see Erickson & Maksimovic, *Fundamentals of Power
   Electronics*, the SEPIC state-space-averaging worked example, or
   equivalent) - **do not re-derive this from first principles as part of
   plan-writing**; whoever picks up this stage should work the derivation
   by hand or from a reference, using this project's actual component
   values (inductances, capacitances - check `hardware/` schematics/BOM
   for real values, they are not currently in any SDK file) as the
   linearization point's parameters.
2. **Extend the SDK's plant model to represent these four states**, at
   least for simulation/design purposes (does not need to replace
   `DynamicSimulatedSource` - could be a new, parallel
   `FullOrderSepicSource` used only for this experiment). This is real,
   schedulable SDK work once step 1's derivation exists - roughly M
   effort on its own, but cannot be scoped tighter than that without the
   derivation in hand (the state count and coupling terms determine the
   actual implementation shape).
3. **Design a state-feedback gain** (LQR is the natural choice - `scipy`
   is already an allowed dependency per AGENTS.md, "scipy only when a
   hand-rolled solver is awkward," and solving the Riccati equation
   (`scipy.linalg.solve_continuous_are` or a discrete equivalent)
   qualifies) against the model from step 2. Requires choosing `Q`/`R`
   weighting matrices - a real design decision, not a default to copy.
4. **Design a reduced-order observer** (a Luenberger observer estimating
   `iL1`, `iL2`, `vC1` from the measured `vin`, `iin`, `vout` plus the
   known model) - this is the actual "modern control theory" deliverable
   the operator asked about, and it is only meaningful once steps 1-3
   exist (an observer needs a model and a control law to be estimating
   state *for*).
5. **Validate in simulation only, first.** Compare closed-loop
   performance (state-feedback + observer) against Stage 1's PID on the
   *same* Stage-0-style step-response metrics. Compare the observer's
   estimated states against the full-order simulation's true internal
   states (which are only ever the simulation's ground truth - the real
   board never lets you check this against reality) to characterize
   observer convergence and error.

### Explicit feasibility caveats (read before starting this stage)

- **Real component values are not currently anywhere in the SDK.** Step 1
  needs actual inductance/capacitance values from `hardware/`'s schematics
  or BOM - if those aren't documented anywhere machine-readable, that is
  itself a small prerequisite (extracting them once, documenting them
  somewhere the model can cite) before step 2 can proceed.
- **A hardware port of this stage is a separate, later decision**, not
  assumed by this plan. Simulation-only validation (step 5) is the
  deliverable this plan asks for; porting an LQR gain + observer to
  `mode_power_supply.rs` (fixed-point matrix math on an RP2040) is
  meaningfully harder than Stage 1's scalar PID port and should get its
  own plan, written after step 5's simulation results exist, if the
  results justify it.
- **This may reveal the reduced-order model was fine all along** - i.e. a
  legitimate outcome of this spike is "the full-order model's extra
  states barely matter for this converter's actual operating range, PID
  already captures most of the achievable performance" - report that
  honestly if simulation shows it, rather than forcing Stage 3 to happen
  anyway.

## Stage 3: Kalman filter (only after Stage 2 produces a working observer)

**Also a feasibility spike, even more contingent than Stage 2.** Do not
start this stage unless Stage 2's step 5 produced a working, validated
observer worth improving.

### What needs to happen

1. Same full-order state-space model from Stage 2.
2. Define a measurement-noise covariance `R` from `NoisySource`'s existing
   noise-standard-deviation convention (reuse the noise levels
   `docs/methodology.md`'s "Measurement noise" section already
   characterizes for this hardware's full scale - do not invent new
   noise numbers when validated ones already exist in this repo).
3. Define a process-noise covariance `Q` - **this is a genuine, non-
   obvious design choice** (it encodes how much you trust the model vs.
   the measurements) - document the reasoning for whatever value is
   chosen, don't just pick something that makes the numbers look good.
4. Implement the (discrete) Kalman filter - `scipy` or a hand-rolled
   implementation, whichever is more appropriate once the state dimension
   from Stage 2 is known.
5. Compare estimation error against Stage 2's plain Luenberger observer,
   under `NoisySource`-injected noise at the levels from step 2 - this
   comparison (deterministic observer vs. Kalman filter, under realistic
   noise) is the actual pedagogical payoff of this whole plan's third
   stage.

### Feasibility caveat

If Stage 2 shows the reduced-order model is adequate and a full-state
observer wasn't worth building, Stage 3 has no foundation to stand on -
report that as the honest outcome rather than building a Kalman filter
for a state-space model nobody validated was worth having.

## Scope

**In scope**: Stage 0 (fully) and Stage 1 (fully) as described - new
`mpp_sdk/control/` package, `tests/test_pid.py`, a new/extended harness
script, `mode_power_supply.rs`'s new `PowerSupplyLoop::Pid` variant.
Stages 2-3 are in scope only as the feasibility investigation described -
not as a build-it-now instruction.

**Out of scope**:

- Replacing `ClosedLoopState` outright - it stays, for comparison, unless
  a later decision (with real on-target data) says otherwise.
- Any change to `mpp_sdk.algorithms` (the MPPT registry) - PID/LQR/Kalman
  here regulate a voltage/current setpoint, a different control objective
  from MPPT, and must not be confused with or merged into the MPPT
  algorithm interface.
- Porting an LQR gain or observer to firmware (explicitly deferred past
  Stage 2's simulation-only validation - see its feasibility caveats).
- Any change to `mpp_sdk/converters/sepic.py`'s or
  `mpp_sdk/io/dynamic.py`'s existing behavior - Stage 2's full-order model
  is new/parallel, not a replacement (existing harness scripts and tests
  must keep working unmodified).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| PID unit tests | `uv run pytest tests/test_pid.py -v` | all pass |
| Firmware build/clippy/fmt (pipico_board) | `cd firmware/pipico_board && cargo build --release --locked && cargo clippy --release --locked -- -D warnings && cargo fmt --check` | all clean |
| Full Python suite | `uv run pytest -v --tb=short` | all pass |
| Routine checks | `uv run ruff check . && uv run ruff format --check .` | clean |

## Git workflow

- One branch/PR per stage reached (`feat/pid-baseline` for Stage 0+1
  together is reasonable, since Stage 0 has no independent shippable
  value on its own) - do not bundle a not-yet-decided Stage 2/3 outcome
  into the same PR as Stage 1's working code.
- Push and open a PR only after operator confirmation, same as every
  other plan.

## Test plan

- `tests/test_pid.py`: setpoint convergence, anti-windup behavior
  (constructed saturation case), output clamping - see Stage 1 Step 2.
- Stage 0's step-response metrics: unit-tested against a hand-computed
  reference trace (a simple analytic step response, e.g. a first-order
  lag, where rise/settling/overshoot are known in closed form) so the
  metric functions themselves are trusted before using them to judge PID
  vs. `ClosedLoop`.
- Stages 2-3 have no fixed test plan yet - one gets written once the
  full-order model and observer/filter design exist, following this
  repo's existing convention (characterization tests before a risky
  change, per `AGENTS.md`'s "Definition of done").

## Done criteria

Stage 0: baseline metrics recorded (sim + bench).
Stage 1: `mpp_sdk/control/pid.py` + tests passing; firmware
`PowerSupplyLoop::Pid` builds/clippy/fmt clean; on-target comparison
against Stage 0's baseline reported (better, worse, or a wash - all valid
outcomes).
Stages 2-3: a written feasibility report (does the derivation check out,
does simulation show it's worth pursuing, what would a hardware port
need) - not a shipped implementation, unless the decision gates above were
explicitly passed with operator sign-off to continue further.

## STOP conditions

Stop and report if:

- Any on-target test (Stage 0's bench characterization, Stage 1's PID
  validation) shows voltage/current approaching the board's 40 V/1 A
  limits without the safety abort catching it first - that is a bug in
  the abort logic, fix that before continuing, don't just note it and move
  on.
- `mode_power_supply.rs`'s `ClosedLoopState` or its constants
  (`GAIN_DIVISOR`, `MIN_STEP`, `MAX_STEP`, `POWER_SUPPLY_VOUT_MV`) differ
  from what's quoted here (per the drift check) - re-baseline Stage 0
  against the current law before comparing anything to it.
- Stage 2's derivation (once attempted) reveals the SEPIC's actual
  operating range makes a linearized small-signal model a poor fit (e.g.
  because the panel's operating voltage swings too widely for one
  linearization point to be valid) - report this as a real finding, it
  may mean gain-scheduling or a different modern-control approach is
  needed, not a dead end to route around silently.

## Maintenance notes

- Record Stage 0's actual measured baseline numbers here once captured -
  this plan file is the natural home for that record until/unless a
  proper lab report exists elsewhere.
- If plan 034 (closed-loop hardware runs) lands before this plan starts,
  re-check whether `run_control_loop`'s shape can be reused for Stage 0/1's
  on-target logging instead of writing a bespoke script - it was designed
  for `MppTracker`-mode algorithm loops, so confirm it actually fits
  `PowerSupply` mode's different control structure before assuming so.
- If this whole spike is judged not worth pursuing past Stage 1 (a
  legitimate outcome - see Stage 1's own decision gate), consider still
  documenting the working PID as an option in
  `firmware/pipico_board/README.md`'s "Operating Modes" section, since
  it's real, tested, on-target-validated code either way.
