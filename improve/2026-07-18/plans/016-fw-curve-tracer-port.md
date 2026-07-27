# Plan 016: Curve-tracer sweep engine on RP2040 (bench-only, no Pi transport yet)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Update (2026-07-27)**: plan 014 has since landed for real - merged
> (PR #51), on-target fault injection confirmed, plan file removed, status
> table below says DONE. The "live discrepancy" this plan originally
> flagged (code done, docs stale) no longer exists; the byte-budget numbers
> below (3 spare MISO bytes, 9 spare MOSI bytes) are the actual final
> state, not a projection.
>
> **Drift check (run first)**: `git diff --stat 92e437e..HEAD --
> firmware/pipico_board/src/main.rs firmware/pipico_board/src/spi_slave_pio.rs`.
> If either changed, re-check the excerpts below before editing - in
> particular re-verify the MISO/MOSI spare-byte counts, since a future
> change could have consumed more of that padding.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED (touches SEPIC-adjacent safety behavior - the gate duty must
  be forced safe whenever the curve-tracer relay reroutes the panel away
  from the SEPIC path; also real relay-switching and thermal considerations
  on the bleed path, per the reference device's own hardware lessons)
- **Depends on**: none (hard) for the scope in this plan. Plan 014 is
  confirmed DONE (see Update above); the natural follow-up plan (Pi
  transport for bulk sweep data, explicitly out of scope here - see STOP
  conditions) can be scoped against the real 3/9 spare-byte counts now,
  not a projection.
- **Category**: direction / feature
- **Planned at**: commit `0bf4e92`, 2026-07-26

## Why this matters

The curve-tracer scaffold (`Tracer_En` GPIO2, `Tracer_pwm` GPIO3) has existed
since plan 001 (merged) with zero real sweep logic behind it - just a
bring-up aid (`But1` energizes the relay directly to "hear it click"), and
`main.rs`'s own comment says to remove that hack "once the curve tracer has
real logic" (`firmware/pipico_board/src/main.rs:304-306`). This plan gives
it that logic.

This project's own framing is why it's worth doing now, not just because the
scaffold exists: `AGENTS.md`'s "Algorithms" section and `docs/rationale.md`
motivate the global-MPPT algorithms (`ScanAndTrack`, `ParticleSwarm`) around
the **multi-modal P-V curve** that partial shading produces
(`mpp_sdk/models/string.py`'s `PvString`, per-panel irradiance). Today that
multi-modal shape is only ever demonstrated in simulation
(`harness/panel_config.py`, `harness/snapshot.py`). A working hardware curve
tracer lets this thesis show a **real** panel/string under **real** partial
shading actually produces the bimodal P-V curve the simulation predicts -
a natural, concrete capstone measurement, and a real validation point for
the whole "same algorithm, sim today, hardware tomorrow" pitch in
`AGENTS.md`'s opening paragraph. It is a distinct capability from the
existing *software* `PanelModel.iv_curve()` (`mpp_sdk/models/base.py:40`),
which samples a model's I(V) analytically/numerically and has nothing to do
with sweeping a real load across a real panel.

## Current state

### The RP2040 scaffold

`firmware/pipico_board/src/main.rs`:

```rust
// line 300-306
    // Curve-tracer relay + bleed PWM: idle low is both the safe default
    // and normal MPPT operation (low releases the relay, SEPIC path active).
    let mut tracer_en = Output::new(p.PIN_2, Level::Low);
    let _tracer_pwm = Output::new(p.PIN_3, Level::Low);
    // Bring-up aid: hold But1 (active-low, switch to GND) to energize the
    // relay and hear it click. Remove once the curve tracer has real logic.
    let but1 = Input::new(p.PIN_0, Pull::Up);
```

and, in the 1 ms main loop:

```rust
// line 370-374
        tracer_en.set_level(if but1.is_low() {
            Level::High
        } else {
            Level::Low
        });
```

Two concrete gaps beyond "no sweep logic exists":

1. **`Tracer_pwm` (GPIO3) is not actually a PWM output today** - it's a plain
   digital `Output` (`_tracer_pwm`, underscore-prefixed = unused), idle low.
   Real sweep logic needs an `embassy_rp::pwm::Pwm` channel here, following
   the exact pattern already used for the SEPIC gate (`main.rs:295-298`):

   ```rust
   let mut pwm_cfg = PwmConfig::default();
   pwm_cfg.top = 1249;
   pwm_cfg.compare_b = 0;
   let mut pwm = Pwm::new_output_b(p.PWM_SLICE7, p.PIN_15, pwm_cfg.clone());
   ```

   GPIO15 maps to `PWM_SLICE7` channel B in that existing code
   (`floor(15/2) = 7`, `15` is odd -> channel B - the RP2040's fixed
   GPIO-to-PWM-slice mapping, datasheet section 4.5.2). By the same rule,
   **GPIO3 maps to `PWM_SLICE1` channel B** (`floor(3/2) = 1`, odd ->
   B) - `embassy-rp`'s peripheral types statically enforce this pairing, so
   picking the wrong slice is a compile error, not a silent runtime bug
   (useful as a cheap verification gate in Step 1 below).
2. **`But1`'s current behavior is a placeholder**, not the trigger this plan
   should end up with - see Design/Steps.

### Sensing (already usable as-is)

`sensors_task` (`main.rs:66-149`) already polls the INA229 over SPI0 at
~1 kHz and publishes `MEAS_V_MV`/`MEAS_I_MA` (`AtomicU16`). This is the
established pattern in this codebase (`onchip_adc_task` follows the same
shape): **one task exclusively owns a peripheral bus and publishes to
atomics; every other task reads the atomics, never touches the bus
directly.** A curve-tracer task must read `MEAS_V_MV`/`MEAS_I_MA`, not open
a second, competing SPI0 transaction - `sensors_task` already owns SPI0 and
`cs_ina` exclusively (`main.rs:328`).

### The Pi-facing SPI frame - a live discrepancy worth flagging up front

`firmware/pipico_board/README.md`'s "Frame protocol" section and
`improve/2026-07-18/plans/README.md`'s status table both currently describe/
imply the **original** 12-byte, V/I-only frame, and list plan 014 (checksum)
as `TODO`. But the actual code in this worktree at commit `0bf4e92` already
implements plan 014's **full** design - checksum on both directions, plus
`Vout`/temperature-placeholder fields on MISO
(`firmware/pipico_board/src/spi_slave_pio.rs:226-236`):

```text
MOSI (RPi->Pico): [ DUTY_H | DUTY_L | CHECKSUM | 0x00 x 9 ]
MISO (Pico->RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L | TEMP_H | TEMP_L | CHECKSUM | 0x00 x 3 ]
```

(`build_tx_frame` at `spi_slave_pio.rs:144-160` and the MOSI checksum-verify
block at `spi_slave_pio.rs:296-324` confirm this; `cargo build --release
--locked` in this worktree succeeds against this code, confirming it is not
a half-finished, non-compiling intermediate state.) So as of this plan being
written: **MISO has only 3 spare padding bytes left, MOSI has 9** - less
headroom than plan 014's own "Current state" section assumed when it was
first drafted. `improve/2026-07-18/plans/README.md`'s status row for 014 is
stale bookkeeping, not a reflection of the real code - the drift check at
the top of this file tells the executor how to re-confirm this rather than
trust either source.

### Python side - no existing hardware curve-tracer support

Grepped `mpp_sdk/`, `harness/`, `examples/`, `docs/`, `scripts/`
case-insensitively for `curve`, `tracer`, `sweep`, `iv_sweep`. Every hit is
**simulated/software** curve handling: `PanelModel.iv_curve()`
(`mpp_sdk/models/base.py:40`, numeric sampling of a model's I(V)),
`TabulatedPanel` (caches it), and harness/visualization code that plots it.
There is **no** existing hardware-sweep transport, wire protocol, or
`SignalSource` in `mpp_sdk/io/` for this. This is a green field on the
transport side - this plan must not invent one silently (see Scope and STOP
conditions).

## Reference implementation (ESP32-C3, `/home/fd/Downloads/solar_panel_curve_tracer`)

Read in full: `main/measurement.c`, `main/drivers/pwm_controller.c`,
`main/app/app_tasks.c`, `main/app/app_state.c`/`.h`, `LESSONS.md`,
`AGENTS.md`. Skimmed only for contrast: `main/drivers/driver_ina219.c`.
Deliberately not read in depth (no RP2040/mpp-sdk equivalent): OLED
(`driver_sh1106.c`), rotary encoder (`driver_encoder.c`), web server
(`server/*`), `json_builder.c`, `led_controller.c`.

**The sweep algorithm** (`producer_task`, `measurement.c:447-574`):

1. A user-set current setpoint (`db_get_current_setpoint_mA()`, from the
   OLED/encoder UI - no RP2040 equivalent) picks the *desired current
   range* for the sweep; defaults to `MAX_CURRENT_MA = 3922.0f` mA
   (`db/db.h:26`) if unset.
2. `calculate_step_size()` (`measurement.c:362-379`) computes a PWM duty
   step so that exactly `DB_MAX_SAMPLES = 20` points
   (`db/db.h:27`) span duty `0` up to whatever duty the desired current
   range implies - **not** a full 0-to-100% sweep. This indirection exists
   because the reference device lets a user dial in a target current live;
   the RP2040 board has no such input.
3. Duty starts at 0, 250 ms settle (`measurement.c:465-466`).
4. For each of the 20 points (`measurement.c:470-568`): average
   `MAX_MEASUREMENTS_PER_CYCLE = 10` (`app_state.h:82`) INA219 reads taken
   over ~1 second (`vTaskDelay(1000/10 ms)` between sub-reads,
   `measurement.c:516`) to reduce noise; compute
   `V = (bus_mV - shunt_mV/1000)` (shunt-drop-corrected) and `I = current_mA`;
   check the averaged power against `LOAD_POWER_LIMIT_MW = 5000.0f` minus a
   `150.0f` mW margin (`app_state.h:100-101`) and **only log a warning** -
   the actual hard stop (`measurement.c:544`, `//break;`) is **commented
   out**, a real gap in the reference device, not something to copy; write
   the averaged point into a mutex-protected circular buffer (`db_add`,
   retried up to 5 times); advance duty by the computed step, 250 ms settle,
   repeat.
5. Stop is cooperative: `measurement_request(false)` sets
   `g_app.measurement_stop_requested` (`measurement.c:315-326`); the
   producer task checks it each loop iteration and each sub-sample, then
   zeroes the PWM and self-deletes
   (`producer_finish`, `measurement.c:381-398`). The caller optionally
   busy-waits (outside any mutex) up to 2 s for the task to actually exit
   (`measurement.c:63-76`).
6. `pwm_controller.c` is a thin LEDC (ESP32's hardware PWM) wrapper: 8 kHz,
   13-bit resolution (`app_state.h`'s config), duty settable either as a
   percentage (rounded) or in raw resolution steps - directly analogous to
   this project's `Pwm::set_config`/`compare_b` pattern, no lessons beyond
   "duty resolution and rounding matter," already understood in this
   codebase from the SEPIC gate PWM work (plan 002).

**Orchestration** (`app/app_tasks.c`, `app/app_state.c`): a single global
`g_app` struct guarded by one mutex; `producer_task`/`dummy_producer_task`
are plain FreeRTOS tasks created on demand by `measurement_start_locked()`
(`measurement.c:289-313`) and left to self-delete when done or stopped -
there is no compile-time "mode" enum for this, it is a runtime-triggered,
one-shot task, orthogonal to whatever the rest of the firmware is doing.
`app_tasks.c` itself is almost entirely OLED/encoder wiring, not sweep
orchestration - not relevant beyond confirming the task-creation pattern
above.

**Hardware lessons from `LESSONS.md`/`AGENTS.md`** worth carrying over: no
copper pour/thermal relief under the MOSFET that dissipates power during
load sweeps - "affecting the VCCS linearity and risking thermal shutdown."
If the RP2040 board's bleed-path element (not reviewed in this plan - no
schematic read) is similarly dissipative, expect the same risk on repeated
or long sweeps; worth a bench thermal check (see Maintenance notes). Secure
Boot and OLED-footprint-mirroring lessons are ESP32/board-specific, not
applicable here.

## Design

1. **Real PWM on GPIO3**: replace `_tracer_pwm`'s plain `Output` with
   `Pwm::new_output_b(p.PWM_SLICE1, p.PIN_3, pwm_cfg)`, mirroring the gate
   PWM setup. Frequency/resolution: executor's call, but there is no reason
   to match the SEPIC gate's 100 kHz - the bleed path is switching a slower
   thermal/electrical process, not a converter inductor; start conservative
   (e.g. 1-10 kHz) and confirm on-target it doesn't audibly/electrically
   misbehave.
2. **Trigger**: replace `But1`'s "hold to energize" hack with **edge-
   triggered** sweep start (debounced falling edge on `But1`, active-low).
   A press starts exactly one sweep; a sweep already running ignores
   further presses.
3. **This is a runtime, one-shot state machine, not a new `FirmwareMode`
   variant.** `MppTracker`/`PowerSupply` are compile-time-selected,
   *continuous* per-1ms-tick duty computations (`main.rs`'s `match
   FIRMWARE_MODE` at the bottom of the main loop). A curve sweep is the
   opposite shape: triggered, runs for tens of seconds, and while it runs
   the SEPIC gate must NOT be actively driven by either existing mode at
   all (the panel is physically rerouted away from the SEPIC by the
   relay). Forcing this into the same per-tick match arm would require
   `MppTracker`/`PowerSupply` to somehow "pause" mid-loop - messier than
   giving the sweep its own `embassy_executor::task` with its own local
   state machine (`Idle -> Sweeping { step } -> Done`), coordinating with
   the main loop through one new shared flag:

   ```rust
   pub static TRACER_ACTIVE: AtomicBool = AtomicBool::new(false);
   ```

   and one line in the main loop:

   ```rust
   let duty = if TRACER_ACTIVE.load(Ordering::Relaxed) {
       0
   } else {
       match FIRMWARE_MODE { /* existing arms, unchanged */ }
   };
   ```

   This is the same "timing-sensitive task publishes an atomic, another
   task/loop reacts to it" shape already used for `PACKET_COUNT` (plan 013)
   and `ADC_SAMPLE_COUNT` (`mode_power_supply.rs`) - consistent with this
   codebase's established pattern, not a new one.
4. **New module** `firmware/pipico_board/src/mode_curve_tracer.rs` (name
   chosen to sit alongside `mode_power_supply.rs`, even though it is not a
   `FirmwareMode`), owning: `tracer_en: Output`, `tracer_pwm: Pwm`, the
   debounced button edge detector, and the sweep state machine. Spawned
   once from `main()` as its own task, same shape as `neopixel_task`/
   `onchip_adc_task`.
5. **Sweep parameters** (concrete starting point - flag all of these as
   needing on-target re-tuning, this project has no schematic-derived time
   constant for the bleed path, unlike the ESP32 reference's known VCCS):
   - `TRACER_SWEEP_POINTS`: start at 20 (matches the ESP32 default), simple
     **linear** sweep from `tracer_pwm = 0` to `TRACER_PWM_MAX` in equal
     steps - drop the reference's "desired current setpoint" indirection
     entirely, there is no user dial on this board and the goal here
     (characterizing the whole P-V curve, per "Why this matters") wants the
     *full* range swept, not a target-current subset.
   - `TRACER_SETTLE_MS`: start at 250 ms (matches the reference), tune on
     bench.
   - Per-step averaging: average `TRACER_AVG_SAMPLES` consecutive
     `MEAS_V_MV`/`MEAS_I_MA` reads (gated on a sample-freshness counter, the
     same fix `mode_power_supply.rs` already had to make for
     `ADC_SAMPLE_COUNT` - do not gate on value-equality). Since
     `sensors_task` free-runs at ~1 kHz (much faster than the ESP32's
     I2C-polled INA219), a 20-50 ms averaging window is a reasonable
     starting point versus the reference's ~1 s/point - far less bleed-path
     settling time needed per point in principle, but this is exactly the
     kind of assumption that needs on-target confirmation, not just
     porting the number.
   - **Safety cutoff, actually enforced**: define `TRACER_I_MAX_MA`
     referencing the INA229's existing calibrated full-scale
     (`ina229::I_MAX_MA = 1000`, `firmware/pipico_board/src/ina229.rs:63`) -
     do not invent a separate arbitrary limit disconnected from what the
     sensor can even measure - plus a `TRACER_P_MAX_MW` power cap. Unlike
     the ESP32 reference (which only logs, `measurement.c:544`), this port
     must **abort the sweep** (de-energize the relay, zero `tracer_pwm`,
     return to `Idle`) on a cutoff breach, matching this codebase's
     existing defense-in-depth conventions (`DUTY_MAX` clamp,
     `MIN_VALID_VIN_MV` gating in `mode_power_supply.rs`).
6. **Results, this plan's scope only**: an in-RAM
   `[(u16, u16); TRACER_SWEEP_POINTS]` (V in mV, I in mA - same units as
   `MEAS_V_MV`/`MEAS_I_MA`), dumped via `defmt::info!` line-by-line when the
   sweep completes or aborts. **No Pi transport in this plan** - see Scope
   and STOP conditions for why that's deliberately deferred, not an
   oversight.
7. **README**: replace the "Bring-up aid" paragraph in the "Curve tracer"
   section with the real trigger/sweep description; document the new
   constants and `TRACER_ACTIVE`'s interaction with gate duty.

## Scope

**In scope**:

- `firmware/pipico_board/src/main.rs` (real `Pwm` on GPIO3, `But1` edge
  trigger replacing the bring-up hack, `TRACER_ACTIVE` static + one-line
  gate-duty override, spawning the new task)
- `firmware/pipico_board/src/mode_curve_tracer.rs` (new file - state
  machine, sweep parameters, safety cutoff, defmt result dump)
- `firmware/pipico_board/README.md` ("Curve tracer" section)

**Out of scope** (do NOT touch):

- `firmware/pipico_board/src/spi_slave_pio.rs` and the 12-byte Pi frame -
  no growth, no repurposing of the 3/9 remaining padding bytes. How sweep
  data eventually reaches the Pi is an explicit open question for a
  follow-up plan (see STOP conditions), not something to resolve here.
- `mpp_sdk/io/`, `mpp_sdk/models/`, `harness/` - no Python-side changes;
  there is nothing there to integrate with yet (see "Current state").
- Any change to `MppTracker`/`PowerSupply`'s own control-loop math beyond
  the single `TRACER_ACTIVE` gate-duty override line.
- Re-litigating plan 014's checksum/Vout/Temp design - treat it as a given,
  already-landed fact (re-verified via the drift check), not something to
  revisit.
- The bleed-path circuit's actual electrical design/schematic - not
  reviewed as part of this plan (see STOP conditions on the sweep-direction
  assumption).

## Steps

1. Convert `Tracer_pwm` to a real PWM channel.
   Add `PWM_SLICE1` channel B output on `PIN_3`, mirroring the `PIN_15`
   gate-PWM setup in `main.rs:295-298`. Pick an initial frequency (e.g.
   `top` for ~1-10 kHz at the default 125 MHz sysclk) and document the
   choice in a comment, same style as the gate PWM's "100 kHz" comment.
   **Verify**: `cargo build --release --locked` - if `PIN_3` doesn't
   type-check against `PWM_SLICE1`'s channel B, this fails at compile time
   (see "Current state" for why); confirm the actual slice/channel from the
   compiler error rather than guessing again.

2. Add `mode_curve_tracer.rs`: constants, state enum, safety cutoff.
   `TRACER_SWEEP_POINTS`, `TRACER_PWM_MAX`, `TRACER_SETTLE_MS`,
   `TRACER_AVG_SAMPLES`, `TRACER_I_MAX_MA` (reference
   `ina229::I_MAX_MA`), `TRACER_P_MAX_MW`; a `TracerState` enum
   (`Idle`, `Sweeping { step: u8 }`, done handled by returning to `Idle`
   after the defmt dump); a function/task that, once triggered, drives
   `tracer_en`/`tracer_pwm`, samples `MEAS_V_MV`/`MEAS_I_MA` with the
   sample-freshness-gated averaging pattern from `mode_power_supply.rs`,
   checks the safety cutoff every step, and aborts (de-energizes, returns
   `Idle`) on breach.
   **Verify**: `cargo build --release --locked` / `cargo fmt --check` clean.

3. Wire it into `main.rs`: `TRACER_ACTIVE` static, the one-line gate-duty
   override in the main loop, `But1` debounced edge detection replacing
   the old level-triggered hack, spawn the new task.
   **Verify**: `cargo build --release --locked` clean; `grep -n
   "But1 (active-low, switch to GND) to energize" firmware/pipico_board/
   src/main.rs` returns no matches (old comment/hack fully removed).

4. On-target: confirm the relay/PWM sequence and safety cutoff.
   Flash, press `But1` once, confirm via defmt/RTT: the relay clicks once
   (not continuously like the old hack), `tracer_pwm` visibly ramps
   (scope or multimeter on GPIO3), the sweep runs to completion and dumps
   `TRACER_SWEEP_POINTS` `(V, I)` lines, then the relay releases and
   `TRACER_ACTIVE` returns to false (confirm the SEPIC gate resumes normal
   behavior in whichever `FIRMWARE_MODE` is active).
   **Verify**: defmt log shows the full sequence; multimeter/scope
   confirms `tracer_pwm` ramps as expected; a deliberately-forced
   over-current/over-power condition (bench technique, executor's call -
   e.g. a lower-resistance bleed load) aborts the sweep instead of
   continuing past the cutoff (this is the one concrete regression risk
   versus the ESP32 reference, which does NOT enforce this - confirm it
   really is enforced here, not just present in the code).

5. Update the firmware README's "Curve tracer" section.
   Replace the "Bring-up aid" paragraph with the real trigger/sweep
   description; document the new constants.

## Done criteria

- [ ] `Tracer_pwm` (GPIO3) is a real `Pwm` output (`PWM_SLICE1`, channel B),
      not a plain `Output`
- [ ] `But1` triggers exactly one sweep per press (edge-triggered), old
      "hold to click the relay" behavior fully removed
- [ ] Sweep runs as an independent task/state machine, not a `FirmwareMode`
      variant; `TRACER_ACTIVE` forces SEPIC gate duty to 0 during a sweep
      regardless of `FIRMWARE_MODE`
- [ ] Safety cutoff (`TRACER_I_MAX_MA`/`TRACER_P_MAX_MW`) actually aborts
      the sweep on breach (confirmed on-target, not just present in code) -
      this is the one place this port deliberately does *more* than the
      ESP32 reference, which only logs
- [ ] Sweep results (V,I pairs) are dumped via defmt on completion; no
      changes to `spi_slave_pio.rs` or any Python file
- [ ] `cargo build --release --locked` / `cargo fmt --check` clean
- [ ] Firmware README's "Curve tracer" section updated
- [ ] `improve/2026-07-18/plans/README.md` row for 016 updated

## STOP conditions

- **How sweep results reach the Pi is NOT resolved by this plan - flag for
  explicit operator sign-off, do not guess.** As of this plan: MISO has
  only 3 spare padding bytes, MOSI has 9 (post plan-014, see "Current
  state" - itself worth re-verifying, since its own README row is stale).
  This project's docs describe the 12-byte frame as a contract not to
  change without an explicit decision. Options to *present*, not silently
  pick: (1) a distinct, larger SPI transaction specifically for a "bulk
  sweep dump," separate from the steady 12-byte telemetry frame; (2) stream
  one sweep point per normal frame using the few remaining padding bytes
  plus a point-index field, consuming the last of that headroom; (3) an
  entirely separate channel (second UART, or an on-chip buffer the Pi
  bulk-reads via a distinct transaction mode); (4) stay off-Pi indefinitely
  (defmt/RTT only, as this plan implements) until a concrete downstream need
  appears. Do not implement 1-3 without the operator choosing one.
- Relatedly, **how a sweep would be triggered *from the Pi*** (once/if
  transport exists) is equally unresolved - same reasoning applies.
- On-target testing shows forcing gate duty to 0 during `TRACER_ACTIVE`
  does not fully isolate the SEPIC path electrically (relay switching
  interacts unexpectedly with the gate driver or inductor current): stop,
  this is a hardware safety question outside this plan's software scope.
- `PIN_3` does not statically type-check against `PWM_SLICE1` channel B:
  stop and re-derive the correct slice/channel from the RP2040 datasheet
  (section 4.5.2) rather than guessing again.
- Bench testing shows the assumed sweep direction is backwards (e.g.
  increasing `tracer_pwm` duty raises V instead of driving it down toward
  0/Isc, the opposite of what "sweeping the full P-V curve" needs): this
  plan did not review the bleed-path schematic - stop and check
  `hardware/*.kicad_sch` or ask the operator before hardcoding a sweep
  direction.
- A step's on-target verification fails twice after a reasonable fix
  attempt.

## Maintenance notes

- **Thermal**: the ESP32 reference's `LESSONS.md` flags MOSFET heating
  during repeated load sweeps from no copper pour/thermal relief under the
  dissipative element. If the RP2040 board's bleed path is similarly
  dissipative (not confirmed here - no schematic reviewed), expect the same
  risk on repeated or long sweeps; do a bench thermal check (e.g. IR
  thermometer on the bleed element after a few back-to-back sweeps) before
  relying on this for repeated characterization runs. Not required by this
  plan's Done criteria, but worth a note in whoever's bench log picks this
  up next.
- Once the Pi-transport STOP condition above is resolved by the operator,
  `mpp_sdk/io/` will need some new sweep-fetch API (not necessarily
  `SignalSource` - a sweep is a bulk, triggered read, not the steady
  `(V, I)` stream that interface is shaped for), and `harness/`/`examples/`
  should get a demo consuming a **real** sweep the way
  `examples/pvlib_demo.py`/`harness/snapshot.py` consume simulated
  `iv_curve()` - explicitly deferred, not in this plan.
- Resolved as of 2026-07-27 (see the Update note at the top of this file):
  plan 014 is DONE, merged, its file removed. If this plan sits unstarted
  long enough for further drift, re-run the drift check at the top before
  trusting the byte-budget numbers again.
