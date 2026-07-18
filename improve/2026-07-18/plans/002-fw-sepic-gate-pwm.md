# Plan 002: SEPIC gate PWM on GPIO15 at 100 kHz

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written at commit `6fc47a0`. `git diff --stat 6fc47a0..HEAD
> -- firmware/pipico_board/` - if `main.rs` changed, re-check the excerpt
> below before editing.

## Why

The MPPT control variable is the SEPIC duty cycle, but the firmware still
drives its PWM placeholder on `PIN_25` (the on-board LED), updated only
every 100 ms. The board's real gate-driver net is **GPIO15 = PWM_Gate**
(through a 10R + 3.3nF network into the driver stage). Until PWM lands on
that pin at a realistic switching frequency, no closed-loop bench test is
possible. This is the last firmware gap before plan 003 (bench duty
sweep).

## Current state (`firmware/pipico_board/src/main.rs`)

```rust
let mut pwm_cfg = PwmConfig::default();
pwm_cfg.top = 0xFFFF;
pwm_cfg.compare_b = 0x8000;
let mut pwm = Pwm::new_output_b(p.PWM_SLICE4, p.PIN_25, pwm_cfg.clone());
...
loop {
    let duty = DUTY.load(Ordering::Relaxed);
    pwm_cfg.compare_b = duty;
    pwm.set_config(&pwm_cfg);
    Timer::after_millis(100).await;
}
```

`DUTY` is a `AtomicU16` initialized to `0x8000` (50 %), written by the Pi
over the SPI frame (u16, 0 = 0 %, 65535 = 100 %).

## Design (follow it)

1. **Pin/slice**: GPIO15 is PWM slice 7, channel B on the RP2040
   (`slice = (gpio/2) % 8`; odd GPIO = channel B). Embassy:
   `Pwm::new_output_b(p.PWM_SLICE7, p.PIN_15, cfg)`.
2. **Frequency**: `fsw = 100 kHz` (the `design_sepic` default). At the
   125 MHz default sysclk with divider 1: `top = 1249`. Duty resolution is
   then 1250 steps (~10.3 bits) - more than the sensing chain resolves.
3. **Duty mapping**: `compare_b = DUTY as u32 * 1250 / 65536` (never
   exceeds top; 0xFFFF maps to 1249, not wraparound).
4. **Update cadence**: every 1 ms (the SDK control period), not 100 ms.
   Use `pwm.set_duty_cycle`-style compare update if available on the
   pinned embassy revision; otherwise keep `set_config` with the cached
   config - measure nothing here, just do not glitch `top`.
5. **Safe boot**: change `DUTY`'s initial value from `0x8000` to `0`.
   A live gate must come up at 0 % and only move when the Pi commands it.
   The `sim-adc` build keeps the same initial value (no reason to
   diverge).
6. **Input clamp** (added 2026-07-18 after the firmware audit): the raw
   SPI `DUTY` word is applied unvalidated today - a desynced or
   misbehaving master can command 100 % duty, which on a SEPIC means an
   unbounded inductor current ramp. Clamp at the point of use, where
   `DUTY` is loaded to compute the compare value:
   `const DUTY_MAX: u16 = 62258; // 0.95 * 65535, mirrors the SDK's max_duty`
   then `DUTY.load(...).min(DUTY_MAX)`. Zero stays allowed (it is the
   safe state). No logging on clamp - it is a steady-state guard, not an
   event. (Frame-integrity hardening is plan 004's job; this clamp is the
   defense-in-depth layer behind it.)
7. **LED mirror (optional, keep if free)**: keep `PIN_25` PWM as a visual
   duty indicator on its old slice. If it costs more than a handful of
   lines, drop it.
8. **README**: update the "What it does" section (gate PWM on GPIO15 at
   100 kHz, boots at 0 % duty, clamped at 95 %) and the PWM_Gate row note.

## Scope

**In**: `firmware/pipico_board/src/main.rs`,
`firmware/pipico_board/README.md`.

**Out**: the 12-byte frame, `spi_slave_pio.rs`, sensors, any soft-start /
slew limiting (note it as follow-up if the bench shows steps are too
harsh), INA_OOR fast-shutdown wiring (follow-up).

## Steps

1. Move the PWM to GPIO15 per the design, with `DUTY` initial 0.
   Verify: `cargo build --release` and `--features sim-adc` exit 0, no
   new warnings; `cargo fmt --check` clean.
2. On-target smoke (probe attached, NO power stage input connected):
   `cargo run --release`, then scope or logic-analyze GPIO15: expect a
   flat low line at boot; write a duty from the Pi (`scripts/spi_test.py`)
   and see a 100 kHz square wave whose high fraction tracks the
   commanded value.
   Verify: boot = 0 %, commanded 25 % reads ~25 % high time at 100 kHz.

## Done criteria

- [ ] GPIO15 carries 100 kHz PWM, duty tracks the Pi-commanded u16
- [ ] Boots at 0 % duty in both feature configurations
- [ ] Commanded 0xFFFF produces the 95 % clamp, not 100 % (scope or
      defmt-verified)
- [ ] PIN_25 placeholder loop is gone
- [ ] README updated

## STOP conditions

- The gate-driver stage inverts (scope shows the MOSFET on when GPIO15 is
  low): report - the duty mapping must then be inverted in exactly one
  place, and that decision is the operator's.
- 100 kHz is unreachable with divider 1 at the configured sysclk (i.e.
  sysclk is not 125 MHz): recompute `top`, do not silently change fsw.
