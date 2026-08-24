# Plan 018: Bulk-read SPI transaction for curve-tracer sweep results

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard prerequisite - do not start this plan until confirmed**: plan 016
> (the curve-tracer sweep engine itself) must be DONE - flashed, on-target
> confirmed, `TRACER_ACTIVE`/`mode_curve_tracer.rs` producing real sweep
> results in RAM. This plan only adds a way to get those results to the Pi;
> it has nothing to transport otherwise. `grep -n "TRACER_ACTIVE"
> firmware/pipico_board/src/main.rs` returning a match is the quick check;
> if it doesn't exist yet, stop and do plan 016 first.
>
> **Update (2026-08-24)**: implemented ahead of plan 016's own on-target
> confirmation, at the operator's explicit direction (016's sweep engine
> and 018's transport are being validated together on the bench - the
> visual I-V curve from `request_sweep()` is itself part of confirming 016
> works). Code complete on both sides (`spi_slave_pio.rs`'s `BulkState`
> machine, `SpiMcuSource.request_sweep()`), build/clippy/fmt/pytest all
> clean, adversarially reviewed. **Not yet on-target confirmed** - neither
> this plan's own Done criteria nor plan 016's are checked off until the
> board is on the bench.
>
> **Drift check (run first)**: `git diff --stat 64502d7..HEAD --
> firmware/pipico_board/src/spi_slave_pio.rs firmware/pipico_board/src/main.rs
> mpp_sdk/io/spi_mcu.py`. If any changed, re-read those files in full before
> trusting this plan's "Current state" excerpts - this plan is written
> against the PIO SPI-slave design as of plan 014/015 (checksummed 12-byte
> frame), and any further change to that loop (e.g. plan 016 itself touching
> `main.rs`) must be re-verified here.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH (restructures the one piece of this firmware with the most
  documented on-target fragility - the PIO SPI-slave exchange loop; see
  "Why this is risky" below)
- **Depends on**: plan 016 (hard - see prerequisite above)
- **Category**: direction / feature
- **Planned at**: commit `64502d7`, 2026-08-23

## Why this matters

Plan 016 deliberately shipped the curve-tracer sweep engine with results
going nowhere but a `defmt`/RTT dump - explicitly deferring "how do results
reach the Pi" as an operator decision (see plan 016's STOP conditions). The
operator picked the option that keeps the steady 12-byte telemetry frame
untouched and adds a distinct, separate transaction just for bulk sweep
reads, rather than permanently repurposing the frame's few spare bytes or
streaming one point per telemetry poll. This plan specifies that distinct
transaction in enough detail to implement and test it - without which
"which option" remains a one-line preference instead of a buildable design.

## Current state

### The existing exchange loop (`firmware/pipico_board/src/spi_slave_pio.rs`)

The PIO program itself (`init()`, lines 77-90) is frame-length-agnostic: it
shifts one bit per SCK edge and exits on CS deassert, whatever length that
turns out to be - the master (Pi) controls transaction length purely by how
many bytes it clocks. But `spi_pio_task` (the async loop that actually
drives it) is not agnostic - it hardcodes exactly `FRAME_LEN = 12` words
both ways, every iteration:

```rust
// spi_slave_pio.rs:46
pub const FRAME_LEN: usize = 12;

// spi_slave_pio.rs:258-269 (inside the loop)
let mut rx = [0u32; FRAME_LEN];
let exchange = {
    let (rx_half, tx_half) = sm.rx_tx();
    join(tx_half.dma_push(&mut dma, &tx_buf, false), async {
        for slot in &mut rx {
            *slot = rx_half.wait_pull().await;
        }
    })
};
```

`tx_buf` is likewise always a `[u32; FRAME_LEN]` built by `build_tx_frame()`
(lines 144-160). There is no branch anywhere in this loop for "expect a
different-length transaction this time" - adding one is this plan's central
piece of work.

### Why this is risky (read before starting)

This loop's own doc comments (`spi_slave_pio.rs:199-236`) describe two
on-target lessons learned the hard way this project's history:

1. Calling `resync()` after every frame (instead of only on a genuine
   timeout) corrupted the PIO's IRQ-driven RX wakeup after a couple of
   frames, with no timeout even firing - found only through on-target
   debugging, not something that showed up in a build or a read-through.
2. The `FRAME_TIMEOUT`/`LINK_LOST_TIMEOUTS` recovery path (torn-frame and
   link-loss handling) was itself the subject of plan 004, an earlier
   dedicated plan, because the original PIO SPI-slave implementation had no
   recovery path at all.

Both lessons are evidence that this specific piece of code does not behave
as source-reading alone predicts on this hardware. This plan's design
(below) is written to minimize new surface area in that loop, but the
executor should treat every step's on-target verification as load-bearing,
not a formality, and lean on the STOP conditions rather than pushing through
a surprising result.

### `mpp_sdk/io/spi_mcu.py` - the Pi-side driver

`SpiMcuSource._transact()` currently always sends/receives exactly
`FRAME_LEN` (12) bytes per call via `spidev`'s `xfer2()`, mirroring the
firmware's fixed size. A bulk read needs a second, differently-sized
`xfer2()` call - `spidev.xfer2()` already supports arbitrary-length transfers
(it just clocks however many bytes you pass it), so no `spidev`-level
change is needed, only a new method alongside `_transact()`.

## Design

### Protocol: a two-phase request/ack/bulk-read exchange

The steady 12-byte telemetry frame (plan 014/015's design) is **not**
changed in shape - normal polling during `MppTracker`/`PowerSupply` modes
is untouched. A bulk read is a distinct, rare, three-step exchange that only
happens around a curve-tracer sweep:

1. **Request** (Pi -> Pico, inside a normal 12-byte poll): the Pi writes a
   reserved command byte into one of the 9 spare MOSI bytes (`spare[0]`,
   the first byte after the existing `CHECKSUM` at MOSI index 2) - e.g.
   `CMD_REQUEST_BULK_DUMP: u8 = 0xB1`. This rides on a completely normal
   12-byte frame; nothing about frame size changes here. Pick a value
   unlikely to appear from an uninitialized/zeroed buffer (`0xB1`, not
   `0x00` or `0xFF`).
2. **Ack** (Pico -> Pi, on the *next* normal 12-byte frame): the firmware
   cannot react within the same full-duplex frame it received the command
   in (MISO bytes are already shifting out as MOSI arrives - this is the
   same reason `DUTY` updates only take effect on the *next* frame in the
   existing design, not a new constraint). On the frame after seeing
   `CMD_REQUEST_BULK_DUMP`, if a completed (or aborted) sweep result is
   available, the firmware sets one of MISO's 3 spare bytes to an ack value
   carrying the point count actually captured (`0..=TRACER_SWEEP_POINTS`,
   since a safety-cutoff abort per plan 016 may have stopped early) - e.g.
   `spare[0] = 0x80 | n_points` (top bit marks "bulk dump armed", low 7
   bits the count; 20 max fits in 7 bits with room to spare). If no sweep
   result is available (none has run, or the previous one was already
   consumed), `spare[0] = 0x00`.
3. **Bulk read** (Pi -> Pico, a distinct, larger transaction): once the Pi
   sees the armed ack, it issues one `spidev.xfer2()` call sized for the
   whole payload - not a repeat of the 12-byte poll. Frame shape:

   ```text
   TX (Pi->Pico, dummy bytes, MOSI ignored on this transaction):
     [ 0x00 x BULK_FRAME_LEN ]
   RX (Pico->Pi):
     [ MAGIC | N_POINTS | V0_H | V0_L | I0_H | I0_L | ... | V19_H | V19_L
       | I19_H | I19_L | CHECKSUM ]
   ```

   `MAGIC: u8 = 0xC5` (distinguishes a genuine bulk-dump response from a
   torn/mis-synced read - the Pi checks this byte first before trusting
   anything else in the frame). `N_POINTS` echoes the ack's count (belt and
   suspenders - the Pi already knows it from step 2, but a mismatch here is
   a cheap corruption signal). Each point is `(V_mV, I_mA)` as big-endian
   `u16`, same units and byte order as the existing telemetry frame - no
   new scaling convention to invent. `CHECKSUM` is `xor_checksum()` over
   every preceding byte, reusing the existing helper
   (`spi_slave_pio.rs:134-136`) rather than a new formula.

   With `TRACER_SWEEP_POINTS = 20` (plan 016's default): `BULK_FRAME_LEN =
   2 (magic+count) + 20*4 (points) + 1 (checksum) = 83` bytes. If plan 016
   landed with a different point count, recompute this from the real
   constant - `grep -n "TRACER_SWEEP_POINTS" firmware/pipico_board/src/
   mode_curve_tracer.rs` and use its actual value, do not assume 20.

   After this transaction, the firmware clears its "armed" state (a repeat
   bulk-read request with nothing new pending gets `spare[0] = 0x00` on the
   next ack cycle) - a sweep result is consumed exactly once.

### Firmware: switching frame length for exactly one transaction

`spi_pio_task`'s loop needs to expect `BULK_FRAME_LEN` words instead of
`FRAME_LEN` for the one iteration that follows an acked bulk-dump request,
then immediately return to `FRAME_LEN`. Concretely:

```rust
const BULK_FRAME_LEN: usize = 83; // recompute from TRACER_SWEEP_POINTS - see above
const MAX_FRAME_LEN: usize = if BULK_FRAME_LEN > FRAME_LEN { BULK_FRAME_LEN } else { FRAME_LEN };

// inside the loop, replace the hardcoded `[0u32; FRAME_LEN]` with:
let this_frame_len = if bulk_dump_armed { BULK_FRAME_LEN } else { FRAME_LEN };
let mut rx = [0u32; MAX_FRAME_LEN];
// ... DMA push / wait_pull loop over &tx_buf[..this_frame_len] / &mut rx[..this_frame_len]
```

`tx_buf` similarly needs to hold up to `MAX_FRAME_LEN` words, built by
either `build_tx_frame()` (normal) or a new `build_bulk_tx_frame()`
(the 83-byte payload above), selected by the same `bulk_dump_armed` flag.
`bulk_dump_armed` is set the frame *after* `CMD_REQUEST_BULK_DUMP` is seen
(step 2 above) and consumed (reset to normal) immediately after the bulk
transaction completes (step 3) - it is true for exactly one iteration of
the loop, minimizing how long the loop runs in its less-tested shape (see
"Why this is risky").

### Python: `mpp_sdk/io/spi_mcu.py`

A new method, not a change to `read()`/`write()`'s existing contract
(`SignalSource`'s steady polling shape stays untouched - see AGENTS.md's
hard rule that switching sources must need no algorithm code changes; a
sweep-result fetch is not part of that seam at all, matching plan 016's own
maintenance note that this "will need some new sweep-fetch API, not
necessarily `SignalSource`"):

```python
def request_sweep(self) -> list[tuple[int, int]] | None:
    """Request and fetch curve-tracer sweep results, if any are ready.

    Two-step protocol (see plan 018): sends CMD_REQUEST_BULK_DUMP on a
    normal frame, polls the next frame's ack byte, and if armed, issues
    the distinct bulk-read transaction. Returns a list of (v_mV, i_mA)
    tuples, or None if no sweep result was available to fetch.
    """
```

Executor's call on exact polling/retry shape (e.g. how many normal frames
to wait for the ack before giving up) - follow this module's existing
`_last_good_raw`-style defensive pattern (checksum-verified, falls back
rather than raising on a single corrupt frame) rather than inventing a new
error-handling convention.

## Scope

**In scope, as implemented** (`main.rs` ended up untouched - the
sweep-result storage lives in `mode_curve_tracer.rs` itself, which
`spi_slave_pio.rs` reads directly via `take_last_sweep()`; no wiring
through `main.rs` turned out to be needed):

- `firmware/pipico_board/src/mode_curve_tracer.rs` (`SweepResult`,
  `LAST_SWEEP` storage, `take_last_sweep()`; `run_sweep()` publishes to it)
- `firmware/pipico_board/src/spi_slave_pio.rs` (`BulkState` machine,
  frame-length branching, `build_bulk_tx_frame()`, `CMD`/`ACK` bytes added
  to `build_tx_frame()`)
- `mpp_sdk/io/spi_mcu.py` (`request_sweep()`, `_apply_telemetry()` helper,
  `_transact()` extended with a `cmd` parameter and `ack` in its return)
- `firmware/pipico_board/README.md` (documents the bulk-read transaction
  alongside the existing "Frame protocol" and "Curve tracer" sections)
- `tests/test_spi_mcu.py` (new tests for the bulk-read path, faked `spidev`
  as the existing tests already do)

**Out of scope**:

- Any change to the normal 12-byte telemetry frame's shape, byte order, or
  checksum formula - it stays exactly as plan 014/015 left it.
- `mode_curve_tracer.rs`'s sweep logic itself (plan 016's scope) - this
  plan only reads its finished result buffer.
- A `harness/`/`examples/` demo consuming a real sweep - explicitly the
  next follow-up after this plan (plan 016's maintenance notes already flag
  it), not part of this plan's Done criteria.
- Triggering a sweep *from* the Pi (vs. the physical `But1` press) - plan
  016 explicitly left this as a separate open question; this plan's
  `request_sweep()` only fetches results of a sweep however it started.

## Implementation notes (as built, 2026-08-24)

- `mode_curve_tracer.rs`: `SweepResult { points, count }` (`Copy`, no
  `aborted` flag - an aborted sweep is already distinguishable by `count <
  TRACER_SWEEP_POINTS`, so a dedicated flag was unnecessary). Stored in a
  `critical_section::Mutex<RefCell<Option<SweepResult>>>` (`LAST_SWEEP`) -
  a plain atomic doesn't fit an 80-byte struct, and this firmware's single
  cooperative executor (see `spi_slave_pio.rs`'s module doc comment) means
  the critical section only ever contends with itself. `run_sweep()`
  publishes to it right after the existing defmt dump; `take_last_sweep()`
  removes (not peeks) the value - consumed exactly once, per the plan.
- `spi_slave_pio.rs`: `BulkState { Idle, SendAck(SweepResult),
  DoBulk(SweepResult) }` drives both `this_frame_len` (`FRAME_LEN` for
  `Idle`/`SendAck`, `BULK_FRAME_LEN` only for `DoBulk`) and `tx_buf`
  (`build_tx_buf_for_state`) together, always read from the *same* state
  value at the top of the next loop iteration - this is what keeps the
  frame-shape decision and the data actually sent in sync (see that
  struct's doc comment for the full per-state reasoning). A frame timeout
  at any point unconditionally resets to `Idle`, reusing the existing
  `resync()` recovery path - a mismatched bulk-read length (Pi and
  firmware disagreeing) manifests as an ordinary short/torn frame to that
  same recovery code, no new failure mode to handle.
- `mpp_sdk/io/spi_mcu.py`: `_transact()` grew a `cmd` parameter and now
  returns a 5-tuple (adds `ack`); `write()`/`request_sweep()` share a new
  `_apply_telemetry()` helper so both update `read()`/`vout`/
  `temperature_c` identically. `request_sweep()` polls up to
  `poll_attempts` times (default 20, `poll_interval_s=0.05`) - each poll
  is still a real telemetry frame at the currently-commanded duty, so
  polling doesn't disturb `MppTracker`/`PowerSupply` control.

## Done criteria

- [x] Normal 12-byte telemetry frame provably unchanged (existing
      `tests/test_spi_mcu.py` telemetry tests still pass unmodified)
- [ ] `request_sweep()` returns the correct `(V, I)` list for a real
      on-target sweep, including a sweep that aborted early on the safety
      cutoff (fewer than `TRACER_SWEEP_POINTS` points) - **needs the board
      on the bench, not yet confirmed**
- [x] A corrupted bulk-read frame (wrong `MAGIC`, checksum mismatch, or a
      point-count mismatch between the ack and the bulk frame) is detected
      and reported (`RuntimeError`), not silently accepted as valid data -
      unit-tested (`tests/test_spi_mcu.py`)
- [x] `cargo build --release --locked` / `cargo clippy --release --locked
      -- -D warnings` / `cargo fmt --check` clean
- [x] `uv run pytest tests/ -q` all pass (18 tests in `test_spi_mcu.py`,
      7 new for the bulk-read path), `uv run ruff check .` clean
- [x] Firmware README documents the new transaction
- [x] `improve/2026-07-18/plans/README.md` row for 018 updated

## STOP conditions

- Plan 016 is not DONE (see prerequisite banner) - stop immediately, there
  is nothing to transport yet.
- On-target testing shows the loop's frame-length switch introduces the
  same class of failure the module doc comment warns about (RX wakeup stops
  firing, no timeout trips) - stop, this is exactly the risk flagged above;
  do not attempt a workaround without operator sign-off, given how
  non-obvious the previous instance of this failure was to diagnose.
- The Pi's bulk-read `xfer2()` call and the firmware's expected
  `BULK_FRAME_LEN` ever disagree in practice (e.g. `spidev` batches or
  splits the transfer unexpectedly) - stop and report the exact observed
  byte count rather than guessing a fix.
- A step's on-target verification fails twice after a reasonable fix
  attempt.

## Maintenance notes

- `BULK_FRAME_LEN` is already computed from `TRACER_SWEEP_POINTS` at
  compile time on the Rust side (`const` expression in `spi_slave_pio.rs`)
  and from the mirrored `_TRACER_SWEEP_POINTS` on the Python side
  (`spi_mcu.py`) - if `TRACER_SWEEP_POINTS` ever changes, update
  `spi_mcu.py`'s `_TRACER_SWEEP_POINTS` to match by hand (the two aren't
  otherwise linked - Python can't import a Rust `const`) and both frame
  lengths follow automatically.
- Triggering a sweep from the Pi (rather than only the physical button) is
  a natural next step once this transport exists, but was explicitly left
  open by plan 016 - a future plan, not implied by this one.
- `harness/`/`examples/` consuming a real sweep via `request_sweep()` is
  the natural demo to add once this plan is DONE and bench-validated -
  matches `AGENTS.md`'s "Definition of done for a new module" (demo script
  producing one plot) even though this API isn't a new module per se.
