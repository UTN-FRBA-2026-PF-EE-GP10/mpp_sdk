# Plan 020: Stream sweep points as they are captured

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat f837fc2..HEAD --
> firmware/pipico_board/src/mode_curve_tracer.rs
> firmware/pipico_board/src/spi_slave_pio.rs mpp_sdk/io/spi_mcu.py`. If any
> changed, re-read them in full before trusting this plan's excerpts.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED-HIGH (touches `spi_pio_task`'s exchange loop and the
  `LAST_SWEEP` handoff - the two pieces this project has already had to
  debug on-target repeatedly; see "Why this is risky")
- **Depends on**: none hard (016/018/019 DONE). Plan 023 wants this, but
  neither blocks the other.
- **Category**: direction / feature
- **Planned at**: commit `f837fc2`, 2026-08-26

## Why this matters

A sweep takes ~6 seconds (20 points x 250 ms settle, plus ~1 s of
auto-ranging), and today the Pi sees nothing at all until it finishes:
points are accumulated in firmware RAM and published to `LAST_SWEEP` only
at the end, then fetched in one 83-byte bulk read. From the operator's
side that is six seconds of a blank chart followed by a curve appearing at
once.

Streaming each point as it is measured turns the sweep into something you
can watch - the curve draws itself from Voc down through the knee. Beyond
being nicer to look at, it makes a stalled or aborting sweep obvious
immediately (you see where it stopped) rather than after a timeout with
nothing to show. It also removes the largest single transfer from the
protocol, which is the one that needed its own timeout and arm-delay
handling to work at all.

## Current state

### `mode_curve_tracer.rs` - points are published only at the end

```rust
for (step, point) in points.iter_mut().enumerate() {
    // ... set_pwm, settle_and_monitor, average_point, breach checks ...
    *point = (v_mv, i_ma);
    points_captured = step + 1;
}
// ... cleanup, defmt dump ...
critical_section::with(|cs| {
    *LAST_SWEEP.borrow(cs).borrow_mut() = Some(SweepResult {
        points,
        count: points_captured,
    });
});
```

`SweepResult` is `Copy` (`[(u16,u16); TRACER_SWEEP_POINTS]` + `count`), and
`take_last_sweep()` removes it; `restore_last_sweep()` puts it back if a
frame tears mid-handshake.

### `spi_slave_pio.rs` - the bulk-read handshake

`BulkState { Idle, SendAck(SweepResult), DoBulk(SweepResult) }` drives both
the frame length and the TX buffer. `CMD_REQUEST_BULK_DUMP` (0xB1) arms it,
the ack byte carries `0x80 | count`, and `DoBulk` is the one
`BULK_FRAME_LEN` (83-byte) exchange, with its own `BULK_FRAME_TIMEOUT`.

The steady frame is 12 bytes with three spare MOSI bytes after `CMD` and
two spare MISO bytes after `ACK`.

### Why this is risky

Read this before touching the exchange loop. Its doc comments record two
on-target lessons, and this session added a third:

1. Calling `resync()` after *every* frame (not just on timeout) corrupted
   the PIO's IRQ-driven RX wakeup after a couple of frames, with no
   timeout firing.
2. The frame-timeout/link-lost recovery path needed its own dedicated plan
   (004) because the original implementation had none.
3. This session: the handshake dropped its held `SweepResult` on any
   mid-exchange timeout, and the Pi polled slower than `FRAME_TIMEOUT`, so
   the handshake reset on *every* attempt - it could never complete. The
   fix needed `restore_last_sweep()` plus a poll-interval bound.

Every one of those was invisible to code reading and only showed up on
hardware. Treat this plan's on-target verification as load-bearing.

## Design

### Keep the bulk read; add streaming alongside it

Do **not** replace `CMD_REQUEST_BULK_DUMP`. It is working, on-target
confirmed, and is the right way to fetch a *completed* sweep (including
one that finished while nobody was watching). Streaming is an additional,
optional view of a sweep *in progress*. Two consequences:

- A Pi that never sends the new command sees exactly today's behaviour.
- If streaming drops a point, the end-of-sweep bulk read is still
  authoritative - the UI can reconcile against it. This is the main reason
  streaming may be lossy without being a correctness problem.

### Progress in the steady frame's spare MISO bytes

Rather than a new transaction shape, publish the *most recent* point in
the two spare MISO bytes plus a small amount of repurposing. The steady
frame is `[V_H V_L I_H I_L VOUT_H VOUT_L TEMP_H TEMP_L CHECKSUM ACK _ _]`,
leaving two free bytes - not enough for `(u16, u16)` plus an index.

Therefore: introduce a **progress frame variant**, selected by a new MOSI
command `CMD_STREAM_POLL` (0xB4). When the firmware sees it, the *next*
frame's MISO payload carries, instead of telemetry:

```text
[ IDX | V_H | V_L | I_H | I_L | FLAGS | 0 | 0 | CHECKSUM | ACK | 0 | 0 ]
```

- `IDX` - index of the point being reported, `0..TRACER_SWEEP_POINTS`.
  `0xFF` means "no sweep running / nothing new".
- `FLAGS` - bit 0: sweep active; bit 1: this is the final point.
- `CHECKSUM` - XOR over the 8 payload bytes, same position and formula
  shape as the telemetry frame, so `apply_duty_frame`'s validation is
  unchanged in structure.
- `ACK` keeps its meaning and stays inside the checksum (this session
  moved it in for exactly this class of bug).

Frame length is unchanged at 12 bytes, so `this_frame_len` gains no new
case and the DMA arm sizing is untouched. **This is deliberate**: the
83-byte `DoBulk` exchange is the only length exception, and keeping it
that way avoids re-opening the arm-race that needed `_BULK_READ_ARM_DELAY_S`.

A `BulkState::SendProgress` variant carries the snapshot to send, mirroring
`SendAck`, so the frame-shape decision and the data sent are still read
from the same value in the same iteration.

### Firmware-side progress slot

Alongside `LAST_SWEEP`, add:

```rust
#[derive(Clone, Copy)]
pub struct SweepProgress {
    pub index: u8,
    pub v_mv: u16,
    pub i_ma: u16,
    pub active: bool,
    pub final_point: bool,
}
static PROGRESS: Mutex<RefCell<Option<SweepProgress>>> = ...;
pub fn publish_progress(p: SweepProgress);   // called per captured point
pub fn peek_progress() -> Option<SweepProgress>;  // PEEK, not take
```

`peek_progress`, unlike `take_last_sweep`, does **not** consume: a dropped
progress frame is not a lost measurement (the bulk read still has it), and
consuming would make a torn frame silently skip a point. `run_sweep` calls
`publish_progress` immediately after storing each `*point`, and once more
at the end with `active: false`.

### Pi side

```python
def poll_sweep_progress(self) -> SweepProgress | None: ...
```

Returns a small dataclass (`index`, `voltage`, `current`, `active`,
`final_point`) or `None` when nothing is running. Scaled to volts/amps
like `read()`. The server's poll loop calls this on its existing cadence
and pushes updates into `_SweepCache` as a partial curve; `/data` grows a
`"partial"` array and an `"active"` flag alongside the existing complete
`"points"`.

The web UI draws `partial` while `active`, then switches to `points` when
the sweep completes and the bulk read lands - so the authoritative curve
always wins.

## Scope

**In scope**:

- `firmware/pipico_board/src/mode_curve_tracer.rs`
- `firmware/pipico_board/src/spi_slave_pio.rs`
- `firmware/pipico_board/README.md`
- `mpp_sdk/io/spi_mcu.py`
- `tests/test_spi_mcu.py`
- `scripts/curve_tracer_server.py`, `scripts/curve_tracer_web/script.js`
- `improve/2026-07-18/plans/README.md` (status row only)

**Out of scope**:

- Removing or altering `CMD_REQUEST_BULK_DUMP` - it stays authoritative.
- Changing `FRAME_LEN`, `BULK_FRAME_LEN`, or the frame-timeout constants.
- The React rewrite (plan 023) - wire streaming into the existing page.
- Storing per-point timestamps (plan 021's schema has no field for them;
  adding one is a schema bump, not a side effect of this plan).

## Steps

### Step 1: firmware progress slot

Add `SweepProgress`, `PROGRESS`, `publish_progress`, `peek_progress` to
`mode_curve_tracer.rs`, and call `publish_progress` from `run_sweep` after
each captured point and once at completion/abort with `active: false`.

**Verify**: `cargo build --release --locked` → exit 0. Expect an unused
warning for `peek_progress` until Step 2.

### Step 2: firmware frame variant

Add `CMD_STREAM_POLL` (0xB4) to `tracer_command_for`'s neighbours (it is
*not* a `TracerCommand` - it does not go to the tracer task), a
`BulkState::SendProgress(SweepProgress)` variant, a
`build_progress_tx_frame`, and the `Idle`-branch handling that transitions
into it. Update `build_tx_buf_for_state` to match.

**Verify**: `cargo build --release --locked && cargo clippy --release
--locked -- -D warnings && cargo fmt --check` → all exit 0.

### Step 3: Pi side

Add `_CMD_STREAM_POLL`, a `SweepProgress` dataclass, and
`poll_sweep_progress()` to `spi_mcu.py`. Parse per the frame layout above,
rejecting on checksum mismatch exactly as `_transact` does.

**Verify**: `uv run pytest tests/test_spi_mcu.py -q` → existing tests pass
unchanged (the steady frame is untouched).

### Step 4: Pi-side tests

Add to `tests/test_spi_mcu.py`: a `_progress_frame()` helper mirroring
`_miso_frame`, then tests for a mid-sweep point, `IDX=0xFF` → `None`, a
corrupted progress frame → `None` (not garbage), and the final-point flag.

**Verify**: `uv run pytest tests/ -q` → all pass.

### Step 5: server + UI

`_SweepCache` gains `partial` + `active`; `/data` exposes both; the poll
loop calls `poll_sweep_progress()` each iteration. `script.js` draws
`partial` while `active` and switches to `points` on completion.

**Verify**: the no-hardware smoke-test pattern already used in this repo
(construct `_SweepCache`, drive it directly, assert `/data` shape).

### Step 6: docs + index

Update the firmware README's frame-protocol and curve-tracer sections with
the new command and frame variant. Update the plan index row.

**Verify**: `npx --yes markdownlint-cli2 firmware/pipico_board/README.md`
→ 0 issues.

### Step 7: on-target

Flash, run a sweep from the web UI, and confirm: points appear one at a
time as they are measured; the completed curve matches what the bulk read
returns; and an aborted sweep (block the light mid-sweep, or lower the
cutoffs) stops drawing where it aborted. Watch defmt for any regression in
`frame timeout` / `link lost` rates versus before.

## Test plan

- Unit: Step 4's frame-parsing tests, no hardware.
- Regression: the full existing `tests/test_spi_mcu.py` must pass
  unmodified except for additions - the steady frame is unchanged.
- On-target: Step 7. **This is the real test**; the unit tests only prove
  the parser, not the exchange loop.

## Done criteria

- [ ] `cargo build --release --locked` / `clippy -D warnings` / `fmt
      --check` clean
- [ ] `uv run pytest tests/ -q` passes; `ruff check` / `format --check` clean
- [ ] Existing telemetry and bulk-read paths behave identically when the
      Pi never sends `CMD_STREAM_POLL`
- [ ] On-target: a sweep draws point-by-point in the UI - **needs the board**
- [ ] On-target: the streamed curve agrees with the bulk-read curve
- [ ] On-target: no increase in frame-timeout / link-lost rate

## STOP conditions

Stop and report if:

- Streaming measurably degrades the steady link (more timeouts, more
  checksum failures) - the bulk read already works, and a prettier chart
  is not worth a less reliable link.
- The two spare MISO bytes turn out to be needed for something else
  first - the layout above repurposes the whole payload for one frame,
  so a conflicting claim on those bytes needs an operator decision.
- A streamed point ever disagrees with the same point in the bulk read.
  That means the progress slot and `LAST_SWEEP` can diverge, which is a
  design error, not a tuning issue.
- Any change appears to require touching `FRAME_LEN` or the timeout
  constants (see Out of scope).

## Maintenance notes

- `peek_progress` deliberately does not consume. If a future consumer
  needs exactly-once delivery, add a sequence number rather than
  switching it to a take - a dropped progress frame must stay harmless.
- The bulk read remains authoritative. Any future "just use streaming and
  drop the bulk read" simplification loses the ability to fetch a sweep
  that completed while nothing was polling.
- If `TRACER_SWEEP_POINTS` ever exceeds 254, `IDX`'s `0xFF` sentinel and
  its `u8` type both need revisiting.
