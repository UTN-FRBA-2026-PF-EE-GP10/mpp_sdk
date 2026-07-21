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

## Progress note

Executed as two passes per an operator decision. Done:
`onchip_adc_task` reads all three channels every 100 ms, logs at ~1 Hz
alongside `MEAS_I_MA`. `ADC_PWR`/`ADC_VOUT` apply the theoretical divider
scaling (3x 75k + 10k, `V_actual = V_adc * 23.5`, resistor values
confirmed by the operator from the board). `ADC_Input_Curr` is raw pin
mV - the INA281 A3's gain and shunt aren't resolved yet.

On-target check found `ADC_PWR` reading ~9% high versus the INA229's
calibrated `MEAS_V_MV` on the same node family. Root-caused in two steps:

1. Measured the Pico's `ADC_VREF` pin (physical pin 35) directly: 3.218 V,
   not the nominal 3.3 V `raw_to_mv()` assumed. Fixed by replacing the
   hardcoded `3300` with a named `ADC_VREF_MV = 3218` constant - closed
   about a quarter of the 9% gap.
2. The divider resistors are 1% tolerance, which bounds their worst-case
   contribution to ~2% - not enough to explain the rest. The remaining
   ~4.5% is most likely the RP2040's own ADC gain/offset error (confirmed:
   unlike the ESP32, the RP2040 has no factory calibration data readable
   back per chip - checked both `embassy-rp`'s ADC driver and the raw
   `rp-pac` register definitions, no calibration/trim/VREF registers
   exist).

**Two-point calibration against a known reference is deliberately left
pending** for that residual ~4.5% - operator decision: current accuracy is
good enough for this channel's role as a redundant sanity/fault
cross-check, not a precision measurement. Revisit if tighter agreement is
ever needed.

Separately: at bench voltages (~4 V), the as-built 235k/10k divider only
puts ~5.5% of the ADC's 4095 codes to use, which is why a fixed ADC offset
error shows up as a much larger relative error at low voltages than it
will at the design's full range. Added `AdcDividerRange` (`Full`/`Mid`/
`Low`) so the operator can bridge out 1 or 2 of the three series 75k
resistors (jumpers, both channels ganged) to trade full-scale range for
resolution when testing at lower voltages - `ADC_DIVIDER_RANGE` in
`main.rs` must be set to match whichever jumpers are physically shorted;
logged once at boot as a cross-check. See README for the range table.

**Confirmed on-target**: with 2 jumpers shorted (`Low`, 85k/10k divider,
~14.6% of ADC codes in use at ~4 V vs ~5.5% at `Full`), `ADC_PWR` reads
3901 mV against the INA229's 3900 mV - ~0.03% error, down from the
original ~9%. The offset-error theory is confirmed; `Low` is the range to
use for bench/low-voltage testing. `Full`/`Mid` remain available for
higher operating voltages (design ceiling ~40 V) where more codes are
naturally in play even with the larger divider.

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
