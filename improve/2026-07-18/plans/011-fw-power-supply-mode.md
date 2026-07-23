# Plan 011: Firmware `power_supply` mode vs `mpp_tracker` mode

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report - do not improvise, especially on the
> watchdog-interaction question below. Update this plan's row in
> `README.md` when done.
>
> Drift check: written after plan 002 merged (commit `d88e25e`). `git diff
> --stat d88e25e..HEAD -- firmware/pipico_board/src/main.rs` - if it
> changed, re-check the excerpt below before editing.

## Why

Firmware today has exactly one behavior: apply the Pi's raw commanded
`DUTY` directly to the SEPIC gate every 1 ms (clamped at 95 %, forced to 0
on SPI link loss - see `main.rs`/`spi_slave_pio.rs`). Control
decision-making lives entirely on the Pi, per this project's architecture
(`AGENTS.md`: "Algorithms never import models or converters... consume
`(V, I)` from a `SignalSource` and emit a duty cycle `D`"). That is
correct for real MPPT operation, but it makes bench characterization
awkward: plan 002's bring-up found that the same commanded duty (D=0.5)
produced 3.3 V, 6 V, or 7 V depending purely on the load (CCM vs DCM
behavior, not a bug) - holding a *fixed output voltage* for repeatable
bench work currently requires the Pi to manually chase a moving target.

A firmware-local closed-loop "power supply mode" that regulates `Vout` to
a fixed setpoint using the already-available `MEAS_ADC_VOUT_MV` (plan 010)
would make bench characterization (efficiency curves, transfer-ratio
sweeps, driving a known-good test rail for other work) repeatable without
needing a host-side control loop, while leaving the real MPPT path
untouched.

## Current state

- `firmware/pipico_board/src/main.rs`: the main loop unconditionally does
  `let duty = DUTY.load(Ordering::Relaxed).min(DUTY_MAX); pwm_cfg.compare_b
  = (duty as u32 * 1250 / 65536) as u16; pwm.set_config(&pwm_cfg);` every
  1 ms. `DUTY` is written only by `spi_slave_pio::spi_pio_task` from the
  Pi's SPI frame.
- `MEAS_ADC_VOUT_MV` (an `AtomicU16`, calibrated in mV) is already
  populated by `onchip_adc_task` at ~10 Hz, but nothing reads it except
  the periodic log line - it is not used as feedback anywhere.
- No firmware-side control loop of any kind exists. Per `AGENTS.md`'s
  Phase 1 HIL design, the firmware is meant to stay "a dumb I/O proxy" for
  the real MPPT path - this plan must not compromise that for
  `mpp_tracker` mode.
- The link-lost watchdog (`spi_slave_pio.rs`, `LINK_LOST_TIMEOUTS`) forces
  `DUTY` to 0 after ~500 ms of SPI silence, unconditionally, regardless of
  mode.

## Design

Proposed - the watchdog question below needs an explicit operator
decision before implementation, do not assume an answer.

1. **Mode selection**: a compile-time enum + const, the same pattern as
   `AdcDividerRange`/`ADC_DIVIDER_RANGE` (plan 010):

   ```rust
   enum FirmwareMode { MppTracker, PowerSupply }
   const FIRMWARE_MODE: FirmwareMode = FirmwareMode::MppTracker; // default: no behavior change
   ```

   Runtime/SPI-selectable switching is explicitly **out of scope** here -
   it would mean extending or repurposing the frozen 12-byte SPI frame,
   which plan 010 already flagged as "a separate, larger decision the
   operator has not made." Const-selected + reflash is the deliberate
   starting point, matching how the operator described this plan.

2. **`MppTracker` mode**: unchanged from today - apply the Pi's `DUTY`
   directly, clamped, link-lost watchdog active exactly as it is now.

3. **`PowerSupply` mode**: firmware ignores the Pi's `DUTY` value for gate
   control (the SPI frame still exchanges normally, so `spi_test.py` keeps
   working for telemetry/monitoring) and instead runs a local closed-loop
   controller targeting a fixed `POWER_SUPPLY_VOUT_MV: u16` const, using
   `MEAS_ADC_VOUT_MV` as feedback. Start with the simplest control law
   that can plausibly work - proportional-only (or even a fixed-step
   increment/decrement on sign-of-error) rather than a tuned PI. This is a
   bench utility, not a fast-dynamics requirement; a simple law is far
   easier to reason about for safety on first bring-up, and a fancier law
   can follow once the simple one is proven stable on real hardware.

4. **Safety interaction - STOP and get an explicit operator decision on
   both of these before writing the controller**:
   - `DUTY_MAX` (95 %) must still bound whatever duty `PowerSupply` mode's
     controller computes - the inductor-current-runaway risk that
     motivated the clamp (plan 002) applies regardless of who set the
     duty.
   - The link-lost watchdog currently means "no SPI host talking for
     ~500 ms -> stop switching." In `PowerSupply` mode, is that still the
     right behavior, or should the local regulator keep running
     standalone even with no Pi attached (arguably the entire point of a
     bench "power supply" that shouldn't need a host heartbeat)? This is
     a real safety-vs-usability tradeoff, not an implementation detail -
     do not pick one silently.

## Scope

**In**: `firmware/pipico_board/src/main.rs` (mode enum/const, the
`PowerSupply` control loop), `firmware/pipico_board/README.md` (document
both modes, the setpoint const, and the watchdog-interaction decision made
in step 1 below).

**Out**: runtime/SPI mode switching, PI or PID tuning and stability
analysis beyond a basic working proportional law, any change to the
12-byte SPI frame, `spi_slave_pio.rs` (other than reading, not modifying,
its watchdog behavior).

## Steps

1. Get the operator's decision on both safety-interaction questions above
   before writing any controller code.
2. Add the mode enum/const, defaulting to `MppTracker`.
   Verify: `cargo build --release --locked` clean, `cargo fmt --check`
   clean, behavior unchanged (this step alone must be a no-op).
3. Implement `PowerSupply` mode's control loop, writing `compare_b`
   through the same clamp `MppTracker` uses.
   Verify: `cargo build --release --locked` / `cargo fmt --check` clean.
4. On-target: flip `FIRMWARE_MODE` to `PowerSupply`, set a safe low
   setpoint (e.g. 1-2 V, matching the 10 Ohm-load bench setup already
   validated in plan 002), flash, confirm `Vout` settles near the setpoint
   and holds there even while the Pi sends unrelated duty commands (which
   should now be ignored for gate control).
   Verify: multimeter and/or `MEAS_ADC_VOUT_MV` within a documented
   tolerance of the setpoint, stable (no visible oscillation) over ~30 s.
5. Flip back to `MppTracker`, confirm behavior is bit-identical to before
   this plan (regression check) - a stray branch or shared state bug could
   otherwise leak `PowerSupply` behavior into the real MPPT path.

## Done criteria

- [x] Mode enum/const added, defaults to `MppTracker` (step 2 alone is a
      behavior no-op)
- [x] Link-lost-watchdog interaction decided explicitly by the operator
      and documented in the README (not assumed by the executor)
- [x] `DUTY_MAX`-equivalent clamp verified to still apply in `PowerSupply`
      mode
- [x] `PowerSupply` mode regulates `Vout` to the setpoint within a
      documented tolerance, on-target confirmed
- [x] `MppTracker` mode regression-checked as unchanged
- [x] README documents both modes

## STOP conditions

- Either safety-interaction question in step 4 of the design section is
  unresolved - do not implement the controller before both are answered.
- A proportional-only law oscillates or is unstable on real hardware:
  STOP and report rather than ad hoc adding integral/derivative terms -
  this is a controls decision, especially relevant if the mode is meant
  to ever run unsupervised on a bench.

## Maintenance notes

- This is a bench/characterization utility, not part of the MPPT
  deployment path - `AGENTS.md` is explicit that the firmware stays "a
  dumb I/O proxy" for that path. Keep `PowerSupply` mode's control loop
  entirely out of the `MppTracker` code path so it can never accidentally
  affect real MPPT operation.
- If `PowerSupply` mode proves useful, plan 003's bench duty sweep could
  be redone as a bench *voltage* sweep using it instead of manually
  picking duties by hand - worth noting as a possible follow-up, not
  required now.
