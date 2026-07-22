# Plan 014: CRC/checksum on the SPI frame

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written after PR #46 (GPIO14 heartbeat LED, on-change duty
> log) merged. `git diff --stat <that merge>..HEAD --
> firmware/pipico_board/src/spi_slave_pio.rs` - if it changed, re-check the
> excerpt below before editing.

## Why

On-target testing surfaced a real gap: a log showed `rx: duty=0%` then
`duty=12%` then `duty=50%` within ~120 ms, far faster than
`scripts/spi_test.py`'s default 500 ms repeat interval and with no ramping
logic anywhere in the Python stack (`spi_mcu.py`/`spi_test.py` both send
one fixed value per write, no soft-start). The likely explanation: the
existing frame-timeout/resync mechanism (plan 004) only catches transfers
that fail to *complete* (fewer than 96 SCK edges). It has no defense
against a frame that completes all 96 edges but with a few corrupted
bits - a plausible outcome of the same breadboard signal-integrity
fragility that already made 8 MHz unreliable (see `spi_slave_pio.rs`'s
module doc comment and the firmware README's "Master clock speed" note).
A corrupted-but-complete frame is silently decoded and applied as a
real duty value today - there is no way for the firmware to detect or
reject it.

This matters more than a cosmetic log glitch: `DUTY` drives a live SEPIC
gate. An undetected bit-flip in `DUTY_H`/`DUTY_L` changes what the
converter does with zero visibility that it happened. `DUTY_MAX` (95%)
bounds the damage but does not detect it.

## Current state

`firmware/pipico_board/src/spi_slave_pio.rs`'s frame layout, both
directions 12 bytes:

```text
MOSI (RPi -> Pico): [ DUTY_H | DUTY_L | 0x00 ... 0x00 ]  (10 zero-padding bytes)
MISO (Pico -> RPi): [ V_H | V_L | I_H | I_L | 0x00 ... 0x00 ]  (8 zero-padding bytes)
```

`spi_pio_task` decodes `rx[0]`/`rx[1]` into `duty` and stores it
unconditionally (`DUTY.store(duty, ...)`) whenever a transfer completes
within `FRAME_TIMEOUT`. No integrity check exists on either direction
today. The 12-byte length and per-byte layout are described elsewhere in
this project's docs (`AGENTS.md`'s indirect reference via the firmware
README, plan 010's "frozen contract" language) as something not to change
without an explicit operator decision - this plan **repurposes existing
unused padding bytes**, it does not grow the frame, specifically to avoid
that larger decision.

## Design

1. **Checksum, not full CRC, to start**: an 8-bit XOR or additive checksum
   over the meaningful bytes is enough to catch the single/few-bit
   corruption this project has actually observed, is trivial to compute on
   both a `no_std` Cortex-M0+ target and in plain Python, and costs one
   padding byte per direction. A full CRC-8/CRC-16 (e.g. via the `crc`
   crate, no_std-compatible) is a drop-in upgrade later if the simple
   checksum proves insufficient - do not reach for a CRC crate on day one
   without evidence a plain checksum misses real corruption.
2. **Byte placement**: MOSI byte 2 (currently zero-padding, right after
   `DUTY_L`) becomes `CHECKSUM = DUTY_H ^ DUTY_L` (or similar simple
   formula - executor's call, document the exact formula in both
   `spi_slave_pio.rs` and `spi_mcu.py`/`spi_test.py`, they must agree
   byte-for-byte). Same idea for MISO byte 4 covering `V_H^V_L^I_H^I_L` if
   the Pi side benefits from validating telemetry too (in scope, low
   additional cost once the pattern exists on the MOSI side).
3. **On checksum mismatch (Pico side)**: treat it like a torn frame - do
   not apply the bad `DUTY`, log once (rate-limited, matching the existing
   `tick % N` throttling pattern elsewhere in this codebase), and keep the
   last-good `DUTY`. Do **not** immediately force `DUTY` to 0 on a single
   mismatch - that would make an occasional bit flip *more* disruptive
   than today, not less. Only the existing `LINK_LOST_TIMEOUTS` sustained-
   silence path should still force 0.
4. **On checksum mismatch (Pi side, `spi_mcu.py`)**: `read()` currently
   always returns whatever `write()`'s `_transact()` decoded. Add the same
   validation there; on mismatch, keep the last-good `(v, i)` rather than
   returning corrupted telemetry to whatever algorithm is consuming it.
5. **Complementary, not required, but worth the same on-target session**:
   the operator raised two related mitigations - re-evaluate both here
   since they change how often corruption happens rather than whether it's
   detected:
   - **Lower the default SPI clock below 1 MHz** and see whether the
     corrupted-frame rate drops further (same margin argument that took
     8 MHz -> 1 MHz in plan 004). This is a `scripts/spi_test.py`
     `SPEED_HZ` / `SpiMcuSource(speed_hz=...)` constant change, not a
     firmware change - cheap to try.
   - **Polling vs. interrupts on the RX path**: already interrupt-driven,
     not polling - verified by reading `embassy-rp`'s `FifoInFuture::poll`
     (`embassy-rp/src/pio/mod.rs`): it registers a waker and enables the
     PIO's `RXNEMPTY` hardware interrupt, returning `Pending` until the
     real IRQ fires; the TX side is DMA-driven the same way. There is no
     busy-poll loop to convert here - this checksum (detection) and the
     clock-speed change (reduced corruption rate) are the two real levers,
     not an event/interrupt architecture change that's already in place.

## Scope

**In**: `firmware/pipico_board/src/spi_slave_pio.rs` (checksum compute +
verify, one padding byte per direction), `mpp_sdk/io/spi_mcu.py`
(matching verify + last-good fallback), `scripts/spi_test.py` (matching
checksum byte + optionally the `ok?` heuristic), README (document the
checksum byte and formula), the SPI clock speed re-evaluation (config
constant only).

**Out**: growing the 12-byte frame; a full CRC-16/32 unless the simple
checksum is shown insufficient; any change to `FRAME_TIMEOUT`/resync
logic (orthogonal - that catches incomplete transfers, this catches
corrupted-but-complete ones); retrying a rejected frame automatically
(the next natural transaction supersedes it - no special retry logic
needed).

## Steps

1. Pick and document the checksum formula (start with XOR, the simplest
   thing that could work - do not pre-optimize into a CRC).
2. Implement on the firmware side: compute + verify, reject-and-keep-last-
   good on mismatch, rate-limited log.
   Verify: `cargo build --release --locked` / `cargo fmt --check` clean.
3. Implement the matching formula in `spi_mcu.py` and `spi_test.py`.
   Verify: `uv run pytest -q` (if any SPI-adjacent tests exist) and a
   manual `--once` round-trip against real hardware.
4. On-target: deliberately reintroduce the earlier fault-injection
   technique from plan 004's bring-up (loose/glitched connection) and
   confirm a corrupted frame is now rejected (logged, `DUTY` unchanged)
   instead of silently applied.
   Verify: defmt log shows the rejection; `DUTY` does not visibly jump to
   an uncommanded value during the glitch.
5. Try a lower `SPEED_HZ`/`speed_hz` on the same glitch-prone wiring;
   record whether the corrupted-frame rate visibly drops.
   Verify: qualitative on-target comparison, documented in this plan's
   progress note - not a formal statistical test.

## Done criteria

- [ ] Checksum byte added to both frame directions, formula documented in
      README and matching exactly in firmware/`spi_mcu.py`/`spi_test.py`
- [ ] Firmware rejects a checksum-mismatched frame without applying its
      `DUTY` or corrupting `MEAS_V_MV`/`MEAS_I_MA` state
- [ ] `spi_mcu.py`'s `read()` never returns telemetry from a failed-
      checksum frame
- [ ] On-target fault injection confirms detection (not just code review)
- [ ] SPI clock-speed re-evaluation recorded (kept at 1 MHz or lowered,
      with the on-target observation either way)
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- The checksum formula disagrees between firmware and Python after
  implementation (every frame rejected, or corruption never caught in
  fault injection): stop and recheck byte order/endianness before adding
  complexity - this is almost always an off-by-one or byte-order bug, not
  a sign the approach is wrong.
- Fault injection shows the simple XOR checksum misses real corruption
  patterns (e.g. corruption that happens to preserve XOR parity): only
  then escalate to a proper CRC-8/16, and say so explicitly rather than
  silently upgrading.

## Maintenance notes

- If plan 013's NeoPixel indicator lands first, a rejected-frame flash
  (distinct color from the packet-received flash) would be a natural,
  low-cost pairing - not required now.
- Revisit `DUTY_MAX`'s 95% figure alongside this plan if fault injection
  shows the clamp and the checksum interact in a way that changes the
  effective worst-case duty a corrupted-but-checksum-passing frame could
  produce (unlikely given an 8-bit checksum's coverage, but worth a
  sentence in the write-up either way).
