# Plan 039: The PIO SPI slave cannot recover from an idle timeout

> **Executor instructions**: this is a hardware-in-the-loop debugging plan,
> not a code change with a known answer. The root cause is *not* identified
> yet - three fixes were tried on-target and all were rejected by
> measurement (see "What was already tried"). Do not start by writing a
> fix. Start by reproducing the measurement in Step 1, and if your
> reproduction disagrees with the numbers below, trust yours and say so.
>
> Needs the board, the Pi, and a debug probe. A logic analyser on
> SCK/CS/MISO/MOSI is strongly recommended - see "Why this needs a scope".

## Status

- **Priority**: P1 - the workaround holds today, but it constrains the Pi's
  polling rate forever and it is under every future closed-loop run.
- **Effort**: M-L, mostly bench time.
- **Risk**: MED. `spi_slave_pio.rs` is the most on-target-fragile code in
  the firmware and has a history of changes that looked right and made
  things worse.
- **Depends on**: nothing. Blocks nothing outright, but plan 034's
  closed-loop runs inherit the constraint.
- **Category**: correctness / firmware.
- **Found at**: commit `1f900c8`, 2026-09-13, while chasing a flickering
  web UI.

## Why this matters

When a frame does not arrive within `FRAME_TIMEOUT` (100 ms), the firmware
aborts the TX DMA and calls `resync()`. The state machine does not come
back cleanly: the next real frame gets a slave that drives a byte or two
and then goes quiet. The Pi reads a frame that is mostly `0x00` or mostly
`0xFF`.

Measured at 200 kHz, varying only the Pi's inter-frame interval:

| Pi cadence | Result |
|---|---|
| 2.0 s | mostly corrupt |
| 0.5 s | ~50% corrupt, alternating almost perfectly |
| 0.05 s | 37/37 clean; 60 s of continuous server polling with zero mismatches |

The alternation is the tell: a corrupt frame times out, `resync()` runs
again, and the *next* frame is clean - then that one's trailing timeout
breaks the one after it.

This was invisible before 2026-09-13 because the frames carried an XOR
checksum. An all-zero frame XORs to zero and matches its own zero checksum
byte; an all-`0xFF` frame does the same. **Both degenerate frames passed
validation**, and `_transact()` replays last-good telemetry on a failure,
so the Pi showed plausible, stable numbers throughout. The CRC-8 that
replaced it (same commit) rejects them, which is what made the defect
countable.

## Current state (the workaround, already shipped)

`curve_tracer_server.py --poll-period-s` defaults to **0.05**, below
`FRAME_TIMEOUT`, so the timeout never fires and the broken recovery path
never runs. That is why the link is healthy today.

It is a workaround, not a fix:

- Any pause in the Pi's polling longer than 100 ms still produces a bad
  frame or two - a GC pause, a slow request handler, an ssh hiccup, the
  operator restarting the server.
- It forces every future Pi-side consumer to poll fast, including
  `run_algorithm.py`, whose control-loop period is a *scientific* choice
  (it sets the sampling rate of the captured run) and should not be
  dictated by a firmware recovery bug.
- `request_sweep()` already polls internally at 50 ms for exactly this
  reason, which is coupling that should not exist.

## What was already tried, and rejected by measurement

All three were flashed and measured on the board on 2026-09-13. All are
reverted; none are in the tree. **Do not re-try these first.**

1. **Move the CS test above `out` in the PIO bit loop.** Theory: the last
   bit of a frame falls through `jmp pin done` (a master drops CS only
   after the final falling edge), so the loop runs one extra `out`, which
   autopulls against an empty FIFO and blocks. Result: **no change at
   all**, same alternating corruption. The theory is at best incomplete.
2. **Skip `resync()` when zero words were received** (an idle master has
   no alignment to fix). Result: **worse** - every slow frame corrupt. So
   the restart is genuinely load-bearing.
3. **`clear_fifos()` instead of the full `resync()` on an idle timeout.**
   Result: also every slow frame corrupt. Consistent with `clear_fifos()`
   not clearing the OSR: autopull pre-loads a word into it as soon as the
   DMA fills the FIFO, and only `restart()` clears that.

Taken together, (2) and (3) say the OSR/FIFO state after an aborted
`dma_push` is the problem, and (1) says it is not simply a trailing `out`.

## Leading hypothesis

The abort path leaves the DMA channel and the PIO OSR in states that
`resync()` does not fully reconcile, and the order matters:
`set_enable(false)` / `clear_fifos()` / `exec_jmp(origin)` / `restart()` /
`set_enable(true)` happens *before* the next `dma_push` arms, but the
aborted channel may still be mid-transaction, or may re-trigger on DREQ
after the FIFO is cleared, re-filling it behind the restart.

Worth reading closely: whether `dma_push`'s `Drop` actually waits for the
channel to quiesce, or only requests an abort. If it only requests one, a
word can land in the FIFO after `clear_fifos()` - which would explain a
slave that transmits exactly one stale byte and then starves.

## Why this needs a scope

Every hypothesis so far has been plausible and wrong, and each
guess-and-flash cycle costs about two minutes while telling you only
"still broken". A logic analyser on SCK/CS/MISO answers directly what the
slave does on the first bad frame: does it drive nothing, drive stale
bytes, or drive shifted data? Those three point at completely different
causes, and the frame contents alone cannot distinguish them - `0x02FF`
could be "one correct byte then idle-high" or "shifted".

## Steps

1. **Reproduce.** `mpp-sdk curve-tracer-web --poll-period-s 0.5` on the Pi,
   or `scripts/spi_test.py --duty 0 --interval 0.5`, and confirm the
   alternating pattern in the `crc?` column. Then confirm `--interval 0.05`
   is clean. If both hold, the bug is unchanged since this plan was
   written.
2. **Scope the first bad frame.** Trigger on CS falling. Capture the frame
   after an idle gap > 100 ms. Record what MISO does across the whole frame
   and where it stops.
3. **Classify** from Step 2: not driving at all / stale bytes / shifted
   bits. Only then form a hypothesis.
4. **Check the DMA abort contract** in the embassy-rp version in
   `Cargo.lock` - whether dropping `dma_push` waits for quiescence.
5. **Fix, then measure at 0.5 s and 2.0 s cadence**, not just at 0.05 s.
   The pass condition is the slow cadence, since that is what is broken.
6. **Re-point the workaround.** If the fix lands, `--poll-period-s`'s
   default and its help text both need updating - the text currently
   explains, correctly for today, why the value must stay *below* the frame
   timeout.

## Verification

- `scripts/spi_test.py --duty 0 --interval 2.0`: at least 30 consecutive
  frames, zero CRC failures. This is the gate.
- `--interval 0.05`: still clean (no regression in the fast path).
- A curve-tracer sweep and a bulk read complete at a 0.5 s server cadence.
- `cargo clippy --release -- -D warnings` and `cargo fmt --check` clean.
- Firmware's own `checksum mismatch` counter stays at zero across a
  10-minute idle soak with the server polling slowly.

## STOP conditions

- **If a fix works only at one cadence, it is not a fix.** The current
  workaround already does that. Report the cadence dependence.
- If the answer turns out to be "the PL022-replacement PIO design cannot
  recover from a mid-frame abort", say so and propose the redesign
  (for instance: never arm TX until CS asserts) as its own plan rather
  than forcing it into this one.
- Do not raise `FRAME_TIMEOUT` to paper over it. That trades a corruption
  window for a slower link-lost detection, and link-lost is what forces
  duty to 0 when the Pi dies - a safety path.

## Maintenance notes

The XOR-accepts-degenerate-frames lesson generalises: any checksum on a
frame that is mostly zeros in normal operation needs to be
position-sensitive. The bulk-read frame keeps its XOR only because it
opens with `BULK_MAGIC` and carries its own point count.
