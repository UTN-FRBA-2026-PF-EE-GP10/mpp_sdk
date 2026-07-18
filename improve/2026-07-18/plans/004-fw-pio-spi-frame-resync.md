# Plan 004: Make the PIO SPI-slave re-synchronize on every frame

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- firmware/pipico_board/src/spi_slave_pio.rs`
> If the file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (PIO timing change; needs on-target verification against the Pi)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

The PIO SPI-slave program claims to re-sync byte alignment on every CS
cycle, but its resync preamble is unreachable in steady state: the only way
back to it is `jmp pin done`, which executes right after an SCK rising
edge - and on a clean frame the master deasserts CS after the last clock,
so CS is never high at that check. Frame alignment therefore survives ONLY
because both sides always move exactly 96 bits. One short, aborted or
noise-corrupted frame leaves residue in the shift counters and desyncs the
link **permanently** (until reboot). A desynced RX silently decodes garbage
`DUTY`, which drives the SEPIC gate PWM on a live power stage.

## Current state

`firmware/pipico_board/src/spi_slave_pio.rs:58-71` - the PIO program:

```rust
let prg = pio_asm!(
    ".wrap_target",
    "    wait 1 gpio 13", // CS idle (deasserted)
    "    wait 0 gpio 13", // CS asserted -> start of transaction
    "bit_loop:",
    "    out pins, 1",    // setup MISO bit (autopull from TX FIFO)
    "    wait 1 gpio 10", // SCK rising edge
    "    in pins, 1",     // sample MOSI bit (autopush every 8 bits)
    "    jmp pin done",   // CS deasserted? exit (resync at top)
    "    wait 0 gpio 10", // SCK falling edge - next bit setup
    "    jmp bit_loop",
    "done:",
    ".wrap",
);
```

After the 96th `in pins, 1`, CS is still low, so the SM proceeds through
`wait 0 gpio 10` back to `out pins, 1` (a 13th autopull that stalls on the
empty TX FIFO) and then blocks at `wait 1 gpio 10` across the whole
CS-high gap. The `wait 1 gpio 13 / wait 0 gpio 13` preamble never runs
again.

`spi_slave_pio.rs:142-158` - the frame task pushes exactly 12 TX words via
DMA and does exactly 12 `wait_pull`s per iteration; a short frame (< 96
SCK edges) makes the 12th `wait_pull` block forever, and the next frame's
words then land shifted by the missing count.

Frame contract (must NOT change): 12 bytes, SPI mode 0, MSB-first; MOSI =
`[DUTY_H, DUTY_L, 0 x 10]`, MISO = `[V_H, V_L, I_H, I_L, 0 x 8]`. The Pi
side is `mpp_sdk/io/spi_mcu.py` and `firmware/pipico_board/README.md:77-87`
documents the layout.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Build | `cd firmware/pipico_board && cargo build --release` | exit 0 |
| Build (sim path) | `cargo build --release --features sim-adc` | exit 0 |
| Format | `cargo fmt --check` | exit 0 |
| Flash + logs | `cargo run --release` (probe attached) | defmt stream |
| Pi-side exerciser | `uv run scripts/spi_test.py` on the wired Pi | duty/V/I round-trips |

## Scope

**In scope**:

- `firmware/pipico_board/src/spi_slave_pio.rs` (PIO program, task, comments)
- `firmware/pipico_board/src/main.rs` ONLY if the task's spawn signature
  must change (avoid if possible)

**Out of scope** (do NOT touch):

- The 12-byte frame layout and mode-0 protocol (frozen contract with
  `mpp_sdk/io/spi_mcu.py` - zero Pi-side changes allowed).
- `ina229.rs`, `max31865.rs`, sensing task, PWM code.
- Duty range clamping (plan 002 owns it).

## Design (recommended - deviate only with a reported reason)

Two cooperating changes:

1. **Per-frame SM restart from the CPU side.** After each completed frame
   (12 RX words pulled), and before pushing the next TX frame: disable the
   SM, clear both FIFOs and the ISR/OSR shift counters
   (`sm.restart()` / the embassy-rp equivalents - check what the pinned
   embassy revision exposes: `StateMachine::restart`, `clear_fifos`, and
   re-exec of the program's entry via `PioInstrExec`/`exec_jmp` if needed),
   then re-enable. The program then genuinely runs its
   `wait 1 gpio 13 / wait 0 gpio 13` preamble every frame, making the
   documented per-frame resync real. CS is guaranteed high between frames
   (the Pi's spidev raises CE0 between transfers), so a restart in the gap
   is race-free as long as it completes before the master starts the next
   frame - at 1 kHz control period the gap is ~1 ms, plenty.
2. **Timeout on the RX side.** Wrap the 12-`wait_pull` loop in
   `embassy_time::with_timeout` (e.g. 100 ms). On timeout (short frame /
   master stopped): drop the partial frame, do the same restart + FIFO
   clear, and continue the loop WITHOUT storing a duty (keep the last good
   one). Log at most one defmt warning per timeout event.

Keep the module's top comments in sync: the "resyncs byte alignment" claim
must describe the actual mechanism after this change.

## Steps

### Step 1: Restructure the frame task with restart + timeout

Implement the design above in `spi_pio_task` + `init` (whatever helper
split keeps `init` returning what `main.rs` spawns today).

**Verify**: all three build/format commands exit 0.

### Step 2: On-target happy path

Flash; from the Pi run `scripts/spi_test.py` in a loop. Duty/V/I
round-trips must behave exactly as before the change (same values, no
missed frames at the normal cadence).

**Verify**: 1000+ consecutive frames with correct V/I echo and duty
acceptance (script output), no defmt timeout warnings.

### Step 3: On-target fault injection

From the Pi, send ONE deliberately short transfer (e.g. a 5-byte
`spidev.xfer2`), then resume normal 12-byte frames.

**Verify**: the firmware logs one timeout/short-frame event, and the very
next normal frame round-trips correctly (pre-fix behavior: permanent
corruption). Repeat 10x.

## Test plan

No host test infra for the firmware crate (accepted). The test surface is
the build gates plus steps 2-3 on hardware, whose observed outputs go in
your report. If you have no hardware access, complete step 1, report
"blocked: no hardware", and set the status row to BLOCKED accordingly.

## Done criteria

- [ ] Both build configs + `cargo fmt --check` exit 0
- [ ] Frame layout unchanged (no `spi_mcu.py` edits, README table untouched)
- [ ] Step 3 fault injection recovers within one frame (or BLOCKED: no
      hardware, with step 1 done)
- [ ] Module comments describe the real resync mechanism
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- The pinned embassy-rp revision exposes no way to restart the SM / clear
  FIFOs from the task (API missing): report what IS available instead of
  inventing unsafe register pokes.
- Step 2 shows missed frames at the normal cadence after the change (the
  restart is too slow for the inter-frame gap): report measured timings.
- Fixing this appears to require changing the 12-byte frame or the Pi side.

## Maintenance notes

- Plan 002 (SEPIC gate PWM) makes wrong-duty consequences physical; land
  this before trusting HIL runs. The duty CLAMP lives in plan 002, the
  frame INTEGRITY lives here - both are needed.
- A future frame-format v2 (e.g. temperature in the padding bytes) must
  revisit the word-count constants here and in `spi_mcu.py` together.
