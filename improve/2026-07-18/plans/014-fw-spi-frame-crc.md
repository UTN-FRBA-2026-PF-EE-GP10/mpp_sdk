# Plan 014: CRC/checksum + telemetry expansion on the SPI frame

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written alongside PR #46 (merged as commit `2aa9d35`). Run
> `git diff --stat 2aa9d35..HEAD -- firmware/pipico_board/src/spi_slave_pio.rs`
> and, if it changed, re-check the excerpt below before editing.

## Progress note

Implemented: checksum (XOR) on both frame directions, Vout/Temp-placeholder
fields on MISO, all within the existing 12-byte frame (final layout in
Design below). Firmware rejects a checksum-mismatched MOSI frame without
touching `DUTY` and without counting it toward `consecutive_timeouts`.
Python side (`spi_mcu.py`/`spi_test.py`) matches byte-for-byte, keeps
last-good telemetry on a MISO checksum mismatch, and plan 015's independent
fixes to the same file landed alongside this. `cargo build --release
--locked`/`fmt`/`clippy` clean; `uv run pytest -q`/`ruff check .` clean
(`tests/test_spi_mcu.py` covers the checksum-mismatch/keep-last-good path).

**Not yet done - needs real hardware, cannot be verified in this session**:
on-target fault injection (Done criteria's 5th item) and the SPI
clock-speed re-evaluation (6th item). Both require a bench session with
the actual board.

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

**Scope note (folded in after this plan was first written)**: alongside
the checksum, the operator asked to also use this same pass through the
frame layout to send two more telemetry values the Pico already computes
but doesn't yet transmit: `MEAS_ADC_VOUT_MV` (Vout, plan 010's on-chip
ADC) and a placeholder temperature field (the MAX31865/PT100 driver is
implemented but disabled - incompatible probe on the bench, see
`firmware/pipico_board/README.md`'s "Panel temperature" section - so this
field always carries a fixed "not available" sentinel until that lands).
Doing both in one pass avoids redesigning the padding-byte layout twice.
Vin/Iin are **already** sent today (`V`/`I` are the INA229's panel-side
bus voltage and shunt current, i.e. exactly "Vin"/"input current" -
nothing new needed there, just naming clarity).

## Design

1. **Checksum, not full CRC, to start**: an 8-bit XOR checksum over the
   meaningful bytes is enough to catch the single/few-bit corruption this
   project has actually observed, is trivial to compute on both a
   `no_std` Cortex-M0+ target and in plain Python, and costs one padding
   byte per direction. A full CRC-8/CRC-16 (e.g. via the `crc` crate,
   no_std-compatible) is a drop-in upgrade later if the simple checksum
   proves insufficient - do not reach for a CRC crate on day one without
   evidence a plain checksum misses real corruption.
2. **Final byte layout** (both directions still 12 bytes, no growth):

   ```text
   MOSI (RPi -> Pico): [ DUTY_H | DUTY_L | CHECKSUM | 0x00 x 9 ]
   MISO (Pico -> RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L
                          | TEMP_H | TEMP_L | CHECKSUM | 0x00 x 3 ]
   ```

   - MOSI `CHECKSUM = DUTY_H ^ DUTY_L`.
   - MISO `CHECKSUM = V_H^V_L^I_H^I_L^VOUT_H^VOUT_L^TEMP_H^TEMP_L` (XOR of
     all 8 data bytes, now that Vout/Temp are added too - covers the new
     fields, not just V/I).
   - `TEMP_H`/`TEMP_L` are a big-endian `i16`, centi-Celsius, matching the
     disabled `MEAS_T_CC` static's units. Until the MAX31865 is
     re-enabled, always send the sentinel `i16::MIN` (bit pattern
     `0x8000`) - an implausible real temperature, unambiguous as "no
     reading" on the Python side, no new static needed (no live source to
     read from yet).
   - This formula must match byte-for-byte in `spi_slave_pio.rs`,
     `mpp_sdk/io/spi_mcu.py`, and `scripts/spi_test.py`.
3. **On checksum mismatch (Pico side, MOSI)**: treat it like a torn frame
   - do not apply the bad `DUTY`, log once (rate-limited, matching the
   existing `tick % N` throttling pattern elsewhere in this codebase), and
   keep the last-good `DUTY`. Do **not** immediately force `DUTY` to 0 on
   a single mismatch - that would make an occasional bit flip *more*
   disruptive than today, not less. Only the existing `LINK_LOST_TIMEOUTS`
   sustained-silence path (a different failure mode - genuine silence, not
   corrupted-but-present traffic) should still force 0, and a checksum
   failure must NOT itself count toward `consecutive_timeouts` (the master
   is clearly still talking).
4. **On checksum mismatch (Pi side, `spi_mcu.py`)**: `read()` currently
   always returns whatever `write()`'s `_transact()` decoded. Add the same
   validation there; on mismatch, keep the last-good `(v, i, vout, temp)`
   rather than returning corrupted telemetry to whatever algorithm is
   consuming it.
5. **Complementary, not required, but worth the same on-target session**:
   the operator raised two related mitigations - re-evaluate both here
   since they change how often corruption happens rather than whether it's
   detected:
   - **Lower the default SPI clock below its current 200 kHz** (already
     dropped once, from 1 MHz, per plan 013's NeoPixel-crosstalk finding)
     and see whether the corrupted-frame rate drops further. This is a
     `scripts/spi_test.py` `SPEED_HZ` / `SpiMcuSource(speed_hz=...)`
     constant change, not a firmware change - cheap to try.
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
verify, Vout/Temp-placeholder fields, all within existing padding bytes),
`mpp_sdk/io/spi_mcu.py` (matching verify + last-good fallback + new
fields; also folds in plan 015's independent hardening of this same
file - scale defaults, teardown, read-before-write - since both land in
`_transact()`), `scripts/spi_test.py` (matching checksum + new fields),
README (document the final byte layout and formula), the SPI clock speed
re-evaluation (config constant only).

**Out**: growing the 12-byte frame; a full CRC-16/32 unless the simple
checksum is shown insufficient; any change to `FRAME_TIMEOUT`/resync
logic (orthogonal - that catches incomplete transfers, this catches
corrupted-but-complete ones); retrying a rejected frame automatically
(the next natural transaction supersedes it - no special retry logic
needed); re-enabling the MAX31865 itself (separate hardware problem, the
temperature field here is a placeholder sentinel only).

## Steps

1. Pick and document the checksum formula (XOR, the simplest thing that
   could work - do not pre-optimize into a CRC) and the final byte
   layout (see Design's layout diagram).
2. Implement on the firmware side: Vout/Temp fields in `build_tx_frame`,
   checksum compute (MISO) + verify (MOSI), reject-and-keep-last-good on
   mismatch, rate-limited log, without incrementing
   `consecutive_timeouts` on a checksum failure (the master is clearly
   still talking - that's a different failure mode).
   Verify: `cargo build --release --locked` / `cargo fmt --check` clean.
3. Implement the matching formula + fields in `spi_mcu.py` and
   `spi_test.py`; fold in plan 015's fixes to the same file.
   Verify: `uv run pytest -q` and `uv run ruff check .` clean, plus a
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

- [x] Checksum byte added to both frame directions, formula documented in
      README and matching exactly in firmware/`spi_mcu.py`/`spi_test.py`
- [x] Vout and a temperature-placeholder field added to the MISO frame,
      covered by the same checksum
- [x] Firmware rejects a checksum-mismatched frame without applying its
      `DUTY`, without incrementing `consecutive_timeouts`
- [x] `spi_mcu.py`'s `read()` never returns telemetry from a failed-
      checksum frame
- [x] Plan 015's independent fixes (scale defaults, `__exit__`
      try/finally, read-before-write raising, test coverage) landed
      alongside this plan's changes to the same file
- [ ] On-target fault injection confirms detection (not just code review) -
      needs a real bench session, not done this session
- [ ] SPI clock-speed re-evaluation recorded (kept at 200 kHz or lowered,
      with the on-target observation either way) - needs a real bench
      session, not done this session
- [x] `improve/2026-07-18/plans/README.md` row updated

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
