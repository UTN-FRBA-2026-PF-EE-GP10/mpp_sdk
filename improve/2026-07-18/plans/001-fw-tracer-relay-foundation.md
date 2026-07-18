# Plan 001: Curve-tracer relay + Tracer_pwm foundation

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written at commit `6fc47a0`. `git diff --stat 6fc47a0..HEAD
> -- firmware/pipico_board/` - if `main.rs` changed, re-check the excerpts
> below before editing.

## Why

The final board carries a curve-tracer subcircuit on the SepicConverter
sheet: relay K1 (Omron G5LE-1 SPDT) switches the panel input over to a
bleed path (`V_Bleed` / `CurveTracer` nets) so the rig can sweep the panel
I-V curve as its own ground-truth instrument (PLAN.md methodology: "a
calibration duty sweep with the condition held"). The firmware currently
drives neither control line; both must come up in a known-safe state
before any bench work, and the README GPIO table is stale for these pins.

## Hardware facts (traced from the merged final schematic, PR #34)

- Pico left-column label order in `hardware/Pico.kicad_sch` maps:
  **GPIO0 = But1, GPIO1 = But2, GPIO2 = Tracer_En, GPIO3 = Tracer_pwm**.
  (`firmware/pipico_board/README.md` GPIO table still shows the old
  LED1/LED2/general-purpose names for GPIO0-3.)
- `Tracer_En` drives the K1 coil through an NPN transistor (the GPIO
  never sees coil current). Polarity confirmed by the operator
  (2026-07-18): **GPIO2 = 1 energizes the coil and switches the panel
  input to the curve-tracer circuit; GPIO2 = 0 releases the relay and the
  SEPIC path is active.** Idle-low is therefore both the safe default and
  normal MPPT operation.
- `Tracer_pwm` feeds the bleed/tracer PWM input (`Tracer_Coil`,
  `V_Bleed` labels nearby).

## Scope

**In**: `firmware/pipico_board/src/main.rs` (pin init only),
`firmware/pipico_board/README.md` (GPIO table rows 0-3 + a short
"Curve tracer" note).

**Out**: any actual tracing logic, relay sequencing, Pi-frame extension,
button (But1/But2) handling, the bleed PWM waveform itself.

## Steps

1. In `main()`, claim both pins at boot, before any task spawns:
   `Output::new(p.PIN_2, Level::Low)` (relay released) and
   `Output::new(p.PIN_3, Level::Low)` (tracer PWM idle). Bind them at
   `main`'s top level like the chip selects, so they are never dropped
   (drop would reset funcsel and let the lines float).
   Verify: `cargo build --release` and `--features sim-adc`, exit 0, no
   new warnings; `cargo fmt --check` clean.
2. Fix the README GPIO table rows for GPIO0-3 (But1, But2, Tracer_En,
   Tracer_pwm) and add two sentences under a "Curve tracer" heading:
   what K1 switches, and that both lines idle low.
   Verify: table matches the schematic mapping above.

## Done criteria

- [ ] Both pins driven low from boot in both feature configurations
- [ ] README GPIO table matches the final schematic
- [ ] No other behavior change (diff touches only pin init + docs)

## STOP conditions

- Bench observation contradicts the confirmed polarity above (relay
  audibly clicks or the tracer path engages while GPIO2 is low): stop and
  report - do not flip the idle level without re-tracing the schematic.
