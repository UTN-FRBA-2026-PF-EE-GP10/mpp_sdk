# Plan 010: Read the RP2040's on-chip ADC channels

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- firmware/pipico_board/src/main.rs`
> If the file changed since this plan was written, re-check the excerpt
> below against the live code; mismatch = STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (read-only, no control-loop or PWM changes; wrong scaling
  only affects a logged/reported value, not the SEPIC gate)
- **Depends on**: none
- **Category**: direction / feature
- **Planned at**: commit unknown at write time (post plan-004 merge), 2026

## Why this matters

Three RP2040 ADC channels are wired but unread by firmware:

| GPIO | Net | ADC | Purpose |
|------|-----|-----|---------|
| 26 | ADC_PWR | ADC0 | power measurement |
| 27 | ADC_VOUT | ADC1 | SEPIC output voltage |
| 28 | ADC_Input_Curr | ADC2 | input current (INA281 analog cross-check) |

`ADC_Input_Curr` is documented (`docs/general_information.md`) as the
INA281 analog redundancy path for the INA229's digital current reading -
useful as a sanity cross-check (log both, alert on disagreement). `ADC_VOUT`
is currently the **only planned way to measure the SEPIC's output voltage**
at all - the INA229 only sees the panel (input) side. Without it there is
no visibility into what the converter is actually delivering to the load,
which matters for plan 003's bench sweep (currently relies on a handheld
multimeter) and for the eventual algorithm-comparison bench validation.

## Current state

`firmware/pipico_board/src/main.rs` - no ADC peripheral use anywhere;
`embassy_rp::adc` is not imported. `sensors_task` currently reads only the
INA229 over SPI0.

The three ADC nets' analog scaling (voltage dividers / gain stages ahead of
each pin) are **not yet known to this plan** - check
`hardware/Proyecto0.1V-schematic.pdf` / `hardware/*.kicad_sch` (the
AnalogConverters sheet, `hardware/untitled.kicad_sch`) for the actual
divider ratios and the INA281 gain before writing any conversion math.

## Scope

**In scope**:

- `firmware/pipico_board/src/main.rs` (new ADC read path)
- A new `firmware/pipico_board/src/onchip_adc.rs` if the conversion logic
  is non-trivial enough to warrant its own module (match `ina229.rs`'s
  style if so)
- `firmware/pipico_board/README.md` (document the new readings and their
  scaling)

**Out of scope**:

- Any change to the INA229/MAX31865 SPI0 sensing path
- Adding these values to the 12-byte Pi SPI frame (frozen contract) -
  publish them as new `Atomic` statics and log lines only, same pattern as
  `MEAS_V_MV`/`MEAS_I_MA`; extending the Pi-visible frame is a separate,
  larger decision the operator has not made
- PWM / gate control changes

## Steps

### Step 1: Determine the analog scaling

Read the schematic sheet(s) covering `ADC_PWR`, `ADC_VOUT`, `ADC_Input_Curr`
and record: any voltage-divider ratio, the INA281 gain (for
`ADC_Input_Curr`) and its shunt resistor value, and each net's expected
full-scale range relative to the RP2040 ADC's 0-3.3 V input.

**Verify**: scaling factors written down with their schematic source
(component references), same rigor as plan 005's R_SHUNT resolution. If
any value cannot be determined from the schematic, STOP and ask the
operator (do not guess a divider ratio).

### Step 2: Implement the ADC read task

Use `embassy_rp::adc::{Adc, Channel, Config}`. Add a new low-priority task
(or fold into `sensors_task` if the timing budget allows - these channels
change slowly, ~10 Hz polling is plenty, no need to compete with the 1 kHz
INA229 loop) that reads all three channels, applies the Step 1 scaling, and
publishes to new statics (e.g. `MEAS_PWR_ADC_RAW`, `MEAS_VOUT_MV`,
`MEAS_IIN_CROSSCHECK_MA` - naming is the executor's call, follow the
`MEAS_*` convention already established).

**Verify**: `cargo build --release --locked` exits 0, no new warnings.

### Step 3: Cross-check log line

Add a ~1 Hz log line (same throttling discipline as the existing
`V=... I=...` line) showing the new readings, and specifically for
`ADC_Input_Curr`: log it alongside the INA229's `MEAS_I_MA` so a human can
visually compare them.

**Verify**: on-target, with the panel/PSU connected, the two current
readings agree within a documented tolerance (establish what's reasonable
given the INA281's gain error and the ADC's resolution - do not invent a
number without justifying it from the datasheet figures).

## Done criteria

- [ ] All three ADC channels read and published as `Atomic` statics
- [ ] Scaling documented in README.md with its schematic source
- [ ] `cargo build --release --locked` exits 0, no new warnings
- [ ] On-target cross-check between `ADC_Input_Curr` and `MEAS_I_MA`
      reported (or BLOCKED: no hardware, with steps 1-2 done)
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- Any analog scaling factor cannot be determined from the schematic.
- The 1 kHz INA229 loop timing is measurably disturbed by adding ADC reads
  to the same task (if so, use a separate lower-priority task instead of
  folding in).

## Maintenance notes

- This is the natural place to wire up the INA229-vs-INA281 disagreement
  alert mentioned in plan 005's maintenance notes.
- `ADC_VOUT` becomes directly useful for plan 003's bench sweep (replacing
  or cross-checking the handheld multimeter reading) - consider sequencing
  after this plan if that bench work hasn't happened yet.
