# Plan 019: SPI-triggered curve-tracer sweeps + explicit relay release

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard prerequisite**: plan 018 (bulk-read SPI transport) must be merged -
> this plan's checksum-protected `cmd` byte relies on plan 018's fix
> (`duty_h ^ duty_l ^ cmd`, `spi_slave_pio.rs`'s `apply_duty_frame`). `grep -n
> "fn apply_duty_frame" firmware/pipico_board/src/spi_slave_pio.rs` returning
> a match that takes `rx`/`last_logged_duty`/`checksum_failures` and returns
> `Option<u8>` is the quick check.
>
> **Drift check (run first)**: `git diff --stat 8d3039d..HEAD --
> firmware/pipico_board/src/mode_curve_tracer.rs
> firmware/pipico_board/src/spi_slave_pio.rs firmware/pipico_board/src/main.rs
> mpp_sdk/io/spi_mcu.py scripts/curve_tracer_server.py
> scripts/curve_tracer_web/`. If any changed, re-read those files in full
> before trusting this plan's "Current state" excerpts.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH (touches `spi_pio_task`'s exchange loop again - the piece of
  this firmware with the most documented on-target fragility, see plan 018's
  "Why this is risky" - and changes `mode_curve_tracer.rs`'s task control
  flow and the curve-tracer relay's safety lifetime)
- **Depends on**: plan 018 (hard, see prerequisite above), plan 016 (hard,
  transitively)
- **Category**: direction / feature
- **Planned at**: commit `8d3039d`, 2026-08-26

## Why this matters

Plans 016/018 shipped a one-shot curve-tracer: a sweep starts only from the
physical `But1` press, and the relay that reroutes the panel onto the bleed
path is automatically released the instant that one sweep ends (breach or
not). The operator now wants to run several sweeps back-to-back without the
relay re-clicking between them (mechanical wear, speed, and simpler
electrical behavior while characterizing a panel), and wants the Raspberry
Pi - not just a person standing at the board - to be able to start a sweep
and to release the relay on its own schedule, so a browser-based GUI
(`scripts/curve_tracer_web/`, added this session) can drive the whole
workflow instead of only displaying results after someone presses a button.
This plan adds that: two new SPI commands, a relay lifetime that is explicit
rather than tied to one sweep, and the GUI/server wiring to use them.

## Current state

### `firmware/pipico_board/src/mode_curve_tracer.rs`

`CurveTracer` owns the relay/PWM hardware and `But1`; the task loop only
reacts to `But1`:

```rust
pub struct CurveTracer {
    tracer_en: Output<'static>,
    tracer_pwm: Pwm<'static>,
    tracer_pwm_cfg: PwmConfig,
    but1: Input<'static>,
    last_ina_sample_seen: Option<u32>,
}

impl CurveTracer {
    pub fn new(
        tracer_en: Output<'static>,
        tracer_pwm: Pwm<'static>,
        tracer_pwm_cfg: PwmConfig,
        but1: Input<'static>,
    ) -> Self { ... }

    fn set_pwm(&mut self, duty: u16) { ... }
    async fn wait_fresh_ina_sample(&mut self) -> Option<(u16, u16)> { ... }
    async fn average_point(&mut self) -> Option<(u16, u16)> { ... }
    fn breach(v_mv: u16, i_ma: u16) -> bool { ... }
    async fn settle_and_monitor(&self) -> bool { ... }

    async fn run_sweep(&mut self) {
        defmt::info!("curve_tracer: sweep starting");
        TRACER_ACTIVE.store(true, Ordering::Relaxed);
        self.tracer_en.set_high();

        let mut points = [(0u16, 0u16); TRACER_SWEEP_POINTS];
        let mut points_captured: usize = 0;
        let mut aborted = false;

        for (step, point) in points.iter_mut().enumerate() {
            // ... step PWM, settle_and_monitor(), average_point(),
            // breach() check, abort-and-break on any failure ...
        }

        // Always de-energize and hand the gate back, breach or not - this
        // must not depend on how the loop above exited.
        self.set_pwm(0);
        self.tracer_en.set_low();
        TRACER_ACTIVE.store(false, Ordering::Relaxed);

        // ... defmt dump, publish to LAST_SWEEP ...
    }
}

#[embassy_executor::task]
pub async fn curve_tracer_task(mut tracer: CurveTracer) {
    loop {
        tracer.but1.wait_for_falling_edge().await;
        Timer::after_millis(BUTTON_DEBOUNCE_MS).await;
        if tracer.but1.is_high() {
            continue;
        }
        tracer.run_sweep().await;
        tracer.but1.wait_for_high().await;
    }
}
```

`LAST_SWEEP`/`take_last_sweep()` (plan 018) already live in this file - the
new signal below follows the same "one static per cross-task concern"
pattern.

### `firmware/pipico_board/src/spi_slave_pio.rs`

The `Idle` branch of `spi_pio_task`'s state machine (plan 018) currently
only recognizes one command:

```rust
const CMD_REQUEST_BULK_DUMP: u8 = 0xB1;
...
BulkState::Idle => {
    let cmd = apply_duty_frame(&rx, &mut last_logged_duty, &mut checksum_failures);
    if cmd == Some(CMD_REQUEST_BULK_DUMP) {
        match mode_curve_tracer::take_last_sweep() {
            Some(sweep) => {
                defmt::info!(
                    "spi_pio_task: bulk-dump request acked, {} points",
                    sweep.count
                );
                BulkState::SendAck(sweep)
            }
            None => BulkState::Idle,
        }
    } else {
        BulkState::Idle
    }
}
```

`apply_duty_frame` (added by plan 018's review-fix) validates `cmd` against
the frame's checksum (`duty_h ^ duty_l ^ cmd`) before returning
`Some(cmd)` - a corrupted frame yields `None` and `cmd` is never acted on.
This plan's new commands ride the same protected byte.

### `mpp_sdk/io/spi_mcu.py`

`_transact(self, duty, cmd=0)` already accepts an arbitrary `cmd` byte and
returns `(v_raw, i_raw, vout_raw, temp_raw, ack)`; `request_sweep()` is the
only caller that passes a nonzero `cmd` today. No relevant code changes
needed to `_transact()` itself - only new thin wrapper methods.

### `scripts/curve_tracer_server.py`

Added this session, not yet reviewed against real hardware.

```python
def _poll_loop(cache: _SweepCache, bus, device, speed_hz, period_s) -> None:
    from mpp_sdk.io.spi_mcu import SpiMcuSource
    with SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz) as src:
        while True:
            try:
                result = src.request_sweep()
            except RuntimeError as exc:
                cache.set(None, f"error: {exc}")
            else:
                cache.set(result, "ok" if result is not None else "waiting for But1")
            time.sleep(period_s)
```

`_make_handler(cache)` builds a `BaseHTTPRequestHandler` subclass with only
`do_GET` (serves `/data` and the static files) - **no `do_POST` exists yet**.
The single `SpiMcuSource` instance lives entirely inside `_poll_loop`'s
thread and is never touched from an HTTP handler thread.

### `scripts/curve_tracer_web/index.html` / `script.js`

The current page has no controls beyond Auto/Auto Power/A-mA scaling
buttons; the instructional paragraph reads "Press **But1** on the board to
start a sweep - this page polls for the latest result every few seconds."

## Design

### New MOSI commands

```rust
const CMD_REQUEST_BULK_DUMP: u8 = 0xB1; // existing
const CMD_START_SWEEP: u8 = 0xB2;       // new
const CMD_RELEASE_RELAY: u8 = 0xB3;     // new
```

All three ride `rx[3]` (MOSI's spare `CMD` byte) and are checksum-protected
by plan 018's `duty_h ^ duty_l ^ cmd` formula - no wire-format change beyond
adding two more recognized values.

### Firmware: a cross-task command signal

`spi_pio_task` must not touch `tracer_en`/`tracer_pwm` directly -
`mode_curve_tracer.rs` is this firmware's single owner of that hardware (the
same reason `TRACER_ACTIVE` exists as the one-way status flag out of
`mode_curve_tracer.rs`, rather than `main.rs` reaching into it). Route the
two new commands into `curve_tracer_task` via
`embassy_sync::signal::Signal` - a single-slot, "latest value wins"
primitive built for exactly this (already a dependency, see `Cargo.toml`'s
`embassy-sync` entry; not used anywhere in this codebase yet, so this is a
new pattern here, not an established one - read
`embassy_sync::signal::Signal`'s doc comment in
`~/.cargo/git/checkouts/embassy-*/*/embassy-sync/src/signal.rs` if anything
below is unclear).

In `mode_curve_tracer.rs`, alongside `LAST_SWEEP`:

```rust
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;

#[derive(Clone, Copy)]
pub enum TracerCommand {
    StartSweep,
    ReleaseRelay,
}

/// Cross-task command channel from `spi_pio_task` (spi_slave_pio.rs) into
/// `curve_tracer_task`. "Latest value wins": if the Pi sends a second
/// command before the task consumes the first, the first is silently
/// dropped - acceptable since sweeps are Pi-paced and one at a time, but
/// see this plan's STOP conditions if that assumption turns out to be
/// wrong on target.
pub static TRACER_COMMAND: Signal<CriticalSectionRawMutex, TracerCommand> = Signal::new();
```

### Firmware: `spi_slave_pio.rs`'s `Idle` branch

```rust
BulkState::Idle => {
    let cmd = apply_duty_frame(&rx, &mut last_logged_duty, &mut checksum_failures);
    match cmd {
        Some(CMD_REQUEST_BULK_DUMP) => match mode_curve_tracer::take_last_sweep() {
            Some(sweep) => {
                defmt::info!(
                    "spi_pio_task: bulk-dump request acked, {} points",
                    sweep.count
                );
                BulkState::SendAck(sweep)
            }
            None => BulkState::Idle,
        },
        Some(CMD_START_SWEEP) => {
            mode_curve_tracer::TRACER_COMMAND.signal(mode_curve_tracer::TracerCommand::StartSweep);
            BulkState::Idle
        }
        Some(CMD_RELEASE_RELAY) => {
            mode_curve_tracer::TRACER_COMMAND
                .signal(mode_curve_tracer::TracerCommand::ReleaseRelay);
            BulkState::Idle
        }
        _ => BulkState::Idle,
    }
}
```

Add the two new `const` bytes next to `CMD_REQUEST_BULK_DUMP`'s existing
declaration, and import `mode_curve_tracer::TracerCommand` alongside the
existing `mode_curve_tracer::{self, SweepResult, TRACER_SWEEP_POINTS}` use.

### Firmware: `curve_tracer_task`'s select loop

```rust
use embassy_futures::select::{Either, select};

#[embassy_executor::task]
pub async fn curve_tracer_task(mut tracer: CurveTracer) {
    loop {
        match select(tracer.but1.wait_for_falling_edge(), TRACER_COMMAND.wait()).await {
            Either::First(()) => {
                Timer::after_millis(BUTTON_DEBOUNCE_MS).await;
                if tracer.but1.is_high() {
                    continue;
                }
                tracer.run_sweep().await;
                tracer.but1.wait_for_high().await;
            }
            Either::Second(TracerCommand::StartSweep) => {
                tracer.run_sweep().await;
            }
            Either::Second(TracerCommand::ReleaseRelay) => {
                tracer.release_relay();
            }
        }
    }
}
```

`But1`'s own behavior (debounce, `run_sweep()`, wait-for-release) is
unchanged - it still works exactly as plan 016 validated, just as one of two
ways into the same `run_sweep()` call.

### Firmware: relay persists across sweeps

`run_sweep()` currently energizes the relay unconditionally at the start
(`set_high()` - harmless to call again if already high, so this stays) and
**always** releases it in its cleanup, breach or not. Remove the release
from that cleanup - only `set_pwm(0)` (stop driving the bleed load) and
`TRACER_ACTIVE.store(false, ...)` (hand the SEPIC gate back) remain
unconditional there. Add a separate method:

```rust
/// Explicitly disconnects the panel from the tracer path and hands it
/// back to the SEPIC - the operator controls this independently of any
/// single sweep now (plan 019): multiple sweeps can run back-to-back with
/// the relay staying engaged the whole time. Safe to call whether or not
/// a sweep is in progress or the relay is already released.
pub fn release_relay(&mut self) {
    self.set_pwm(0);
    self.tracer_en.set_low();
}
```

**Safety behavior change worth flagging explicitly**: a safety-cutoff abort
inside `run_sweep()` (overcurrent/overpower during `settle_and_monitor()` or
after `average_point()`) now leaves the relay **engaged** - previously it
also released. `tracer_pwm` still drops to 0 on any abort path (the bleed
load stops being driven either way), but the panel stays routed off the
SEPIC path until something explicitly calls `release_relay()`. This is
deliberate per the operator's "explicit disconnect only" instruction, and
arguably leaves the hardware in a safer state (bleed path at 0 duty, rather
than snapping straight back to SEPIC control mid-fault) - but it is a real
change to this firmware's fault-recovery behavior and should be confirmed
on-target, not just assumed correct by this plan. See STOP conditions.

### Python: `SpiMcuSource`

Add alongside `request_sweep()` in `mpp_sdk/io/spi_mcu.py`:

```python
_CMD_START_SWEEP = 0xB2
_CMD_RELEASE_RELAY = 0xB3

def start_sweep(self) -> None:
    """Ask the firmware to start a curve-tracer sweep (plan 019).

    Fire-and-forget - no ack, unlike ``request_sweep()``'s bulk-dump
    handshake. The relay may already be engaged from a previous sweep
    (multiple sweeps can run without releasing between them, see
    ``release_relay()``). Poll ``request_sweep()`` afterward to fetch the
    result once the sweep completes.
    """
    v_raw, i_raw, vout_raw, temp_raw, _ack = self._transact(self._duty, cmd=_CMD_START_SWEEP)
    self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)

def release_relay(self) -> None:
    """Ask the firmware to disconnect the panel from the tracer's bleed
    path and hand it back to the SEPIC (plan 019).

    The relay otherwise stays engaged across any number of sweeps started
    via ``start_sweep()`` or the physical ``But1`` press - it is no longer
    released automatically when a sweep ends.
    """
    v_raw, i_raw, vout_raw, temp_raw, _ack = self._transact(self._duty, cmd=_CMD_RELEASE_RELAY)
    self._apply_telemetry(v_raw, i_raw, vout_raw, temp_raw)
```

### Python: `curve_tracer_server.py` - single-writer SPI access

`SpiMcuSource`/`spidev.xfer2()` is not documented thread-safe, and the poll
thread already owns the sole instance for its entire lifetime. HTTP handler
threads (`ThreadingHTTPServer` spawns one per request) must not call SPI
methods directly - route new commands through a `queue.Queue` the poll loop
drains once per iteration, before its own `request_sweep()` poll:

```python
import queue

def _poll_loop(
    cache: _SweepCache,
    commands: "queue.Queue[str]",
    bus: int,
    device: int,
    speed_hz: int,
    period_s: float,
) -> None:
    from mpp_sdk.io.spi_mcu import SpiMcuSource

    with SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz) as src:
        while True:
            while not commands.empty():
                cmd = commands.get_nowait()
                if cmd == "start_sweep":
                    src.start_sweep()
                elif cmd == "release_relay":
                    src.release_relay()
            try:
                result = src.request_sweep()
            except RuntimeError as exc:
                cache.set(None, f"error: {exc}")
            else:
                cache.set(result, "ok" if result is not None else "waiting for sweep")
            time.sleep(period_s)
```

`_make_handler` gains a `commands` parameter (same closure pattern already
used for `cache`) and a `do_POST`:

```python
def do_POST(self) -> None:  # noqa: N802
    if self.path == "/start-sweep":
        commands.put_nowait("start_sweep")
    elif self.path == "/release-relay":
        commands.put_nowait("release_relay")
    else:
        self.send_error(404)
        return
    self.send_response(204)
    self.end_headers()
```

`main()` constructs `commands = queue.Queue()` once and passes it to both
`_poll_loop`'s thread args and `_make_handler`.

### GUI: `scripts/curve_tracer_web/`

`index.html`: add a toolbar row with two buttons, e.g.
`<button id="startSweepBtn" class="btn">Start Sweep</button>` and
`<button id="releaseRelayBtn" class="btn tertiary">Release Relay</button>`
(reuse the existing `.btn`/`.btn.tertiary` styles already defined in this
file's `<style>` block). Update the instructional paragraph - it currently
claims `But1` is the only way to start a sweep; that stops being true.

`script.js`: wire both buttons to a plain empty-body `POST`:

```javascript
async function postCommand(path, btn) {
  btn.disabled = true;
  try {
    const r = await fetch(path, { method: "POST" });
    if (!r.ok) throw new Error("HTTP " + r.status);
  } catch (e) {
    console.error(path + " failed", e);
  } finally {
    btn.disabled = false;
  }
}
document.getElementById("startSweepBtn").addEventListener("click", (e) =>
  postCommand("/start-sweep", e.target)
);
document.getElementById("releaseRelayBtn").addEventListener("click", (e) =>
  postCommand("/release-relay", e.target)
);
```

No response body to parse (server replies `204 No Content`) - the existing
`tick()` polling loop already picks up new sweep results once they land, so
nothing else needs to change in `script.js`.

## Commands you will need

| Purpose             | Command                                                                          | Expected on success        |
|----------------------|-----------------------------------------------------------------------------------|-----------------------------|
| Firmware build        | `cd firmware/pipico_board && cargo build --release --locked`                     | exit 0                     |
| Firmware lint          | `cd firmware/pipico_board && cargo clippy --release --locked -- -D warnings`      | exit 0, no warnings         |
| Firmware format        | `cd firmware/pipico_board && cargo fmt --check`                                  | exit 0, no diff             |
| Python tests            | `uv run pytest tests/ -q`                                                        | all pass                   |
| Python lint              | `uv run ruff check .`                                                            | all checks passed           |
| Python format             | `uv run ruff format --check .`                                                  | already formatted           |

(Same commands used throughout plans 016/018 in this repo - verified, not
guessed.)

## Scope

**In scope**:

- `firmware/pipico_board/src/mode_curve_tracer.rs`
- `firmware/pipico_board/src/spi_slave_pio.rs`
- `firmware/pipico_board/README.md`
- `mpp_sdk/io/spi_mcu.py`
- `tests/test_spi_mcu.py`
- `scripts/curve_tracer_server.py`
- `scripts/curve_tracer_web/index.html`
- `scripts/curve_tracer_web/script.js`
- `improve/2026-07-18/plans/README.md` (status row only)

**Out of scope** (do NOT touch, even though related):

- `firmware/pipico_board/src/main.rs`'s `TRACER_ACTIVE` handling - unchanged
  by this plan, already fixed by plan 018's review pass.
- `mode_power_supply.rs` - unrelated to this plan's trigger/relay changes.
- Adding an ack/confirmation byte for `CMD_START_SWEEP`/`CMD_RELEASE_RELAY`
  (see Maintenance notes) - explicitly deferred.
- Any change to the bulk-read (`CMD_REQUEST_BULK_DUMP`) handshake itself.

## Git workflow

- This repo uses `gh-stack` for dependent plans - add this branch on top of
  plan 018's (`gh stack add plan/019-curve-tracer-spi-trigger` from plan
  018's branch, or `gh stack init` fresh if 018 has already merged to
  `main` by the time this runs).
- Commit per logical step (e.g. one commit for the firmware signal/relay
  change, one for the Python/server/GUI change), conventional-commit style
  matching this repo's `git log` (`feat(firmware+sdk): ...`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: firmware - `TracerCommand` + `TRACER_COMMAND` signal + `release_relay()`

In `mode_curve_tracer.rs`, add the imports, enum, and static shown in
"Design" above, add the `release_relay()` method, and remove
`self.tracer_en.set_low();` from `run_sweep()`'s cleanup (keep
`self.set_pwm(0);` and the `TRACER_ACTIVE.store(false, ...)` line).

**Verify**: `cd firmware/pipico_board && cargo build --release --locked` →
exit 0 (expect an "unused" warning for `TracerCommand`/`TRACER_COMMAND` at
this point - they're not consumed until Step 2 - that's fine, it isn't `-D
warnings` yet).

### Step 2: firmware - `curve_tracer_task`'s select loop

Replace `curve_tracer_task`'s body with the `select`-based version shown
above. Add the `embassy_futures::select::{Either, select}` import.

**Verify**: `cargo build --release --locked && cargo clippy --release
--locked -- -D warnings` → both exit 0, no warnings (this should resolve
the unused-item warning from Step 1).

### Step 3: firmware - `spi_slave_pio.rs`'s new commands

Add `CMD_START_SWEEP`/`CMD_RELEASE_RELAY` consts and rewrite the `Idle`
match arm as shown above. Import `mode_curve_tracer::TracerCommand`.

**Verify**: `cargo build --release --locked && cargo clippy --release
--locked -- -D warnings && cargo fmt --check` → all exit 0.

### Step 4: Python - `SpiMcuSource.start_sweep()`/`release_relay()`

Add the two module constants and methods shown above.

**Verify**: `uv run pytest tests/test_spi_mcu.py -q` → all existing tests
still pass (pure additions, nothing existing should break).

### Step 5: Python - tests for the two new methods

Add two tests to `tests/test_spi_mcu.py`, modeled directly on
`test_request_sweep_sends_cmd_byte`:

```python
def test_start_sweep_sends_cmd_byte(spi_mcu_source):
    src = spi_mcu_source()
    src.start_sweep()
    assert src._spi.sent[-1][:4] == [0x00, 0x00, 0xB2, 0xB2]


def test_release_relay_sends_cmd_byte(spi_mcu_source):
    src = spi_mcu_source()
    src.release_relay()
    assert src._spi.sent[-1][:4] == [0x00, 0x00, 0xB3, 0xB3]
```

(Checksum = `duty_h ^ duty_l ^ cmd` = `0 ^ 0 ^ cmd` = `cmd` at the default
duty of 0.0, same reasoning as the existing bulk-dump test.)

**Verify**: `uv run pytest tests/test_spi_mcu.py -q` → all pass, including
the 2 new tests.

### Step 6: Python - `curve_tracer_server.py`'s command queue + `do_POST`

Apply the `queue.Queue`-based changes shown in "Design" above: `_poll_loop`
gains a `commands` parameter and drains it each iteration; `_make_handler`
gains `do_POST`; `main()` constructs the queue once and threads it through.

**Verify**: a manual smoke test without hardware (mirrors the one already
used to validate plan 018's server initially):

```bash
uv run python -c "
import queue, threading, time, urllib.request
from scripts.curve_tracer_server import _SweepCache, _make_handler
from http.server import ThreadingHTTPServer

cache = _SweepCache()
commands = queue.Queue()
server = ThreadingHTTPServer(('127.0.0.1', 8098), _make_handler(cache, commands))
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
time.sleep(0.2)
req = urllib.request.Request('http://127.0.0.1:8098/start-sweep', method='POST')
r = urllib.request.urlopen(req)
print('START', r.status, commands.get_nowait())
req = urllib.request.Request('http://127.0.0.1:8098/release-relay', method='POST')
r = urllib.request.urlopen(req)
print('RELEASE', r.status, commands.get_nowait())
server.shutdown()
"
```

Expected output: `START 204 start_sweep` then `RELEASE 204 release_relay`
(adjust `_make_handler`'s signature in this snippet if Step 6's actual
parameter order differs from this sketch - the point is confirming both
endpoints enqueue the right string and return `204`).

### Step 7: GUI - buttons in `index.html` + wiring in `script.js`

Add the two buttons and event listeners shown in "Design" above.

**Verify**: re-run Step 6's smoke test but serve the real static files (add
a `GET /` fetch and grep the response for `id="startSweepBtn"` and
`id="releaseRelayBtn"`), or open the running server in a browser and click
both buttons while watching the server's stdout / `commands` queue.

### Step 8: docs

Update `firmware/pipico_board/README.md`'s "Frame protocol" section (list
the two new `CMD` values next to `CMD_REQUEST_BULK_DUMP`) and "Curve
tracer" section (trigger is no longer `But1`-only; relay lifetime is now
explicit - stays engaged across sweeps until `CMD_RELEASE_RELAY`).

**Verify**: `markdownlint-cli2 firmware/pipico_board/README.md` (already
runs as a pre-commit hook in this repo - confirm it passes before
committing, or let the hook catch it).

### Step 9: plan index

Update this plan's row in `improve/2026-07-18/plans/README.md`.

## Test plan

- `tests/test_spi_mcu.py`: `test_start_sweep_sends_cmd_byte`,
  `test_release_relay_sends_cmd_byte` (Step 5) - unit tests, no hardware.
- `uv run pytest tests/ -q` → all pass, including the 2 new tests (21 total
  in `test_spi_mcu.py` after this plan, up from 19 after plan 018).
- On-target (needs the board, not part of this plan's own Done criteria -
  see below):
  1. Press `But1` twice in a row with no Pi command in between. Confirm via
     defmt/RTT the relay does **not** click a second time (stays engaged),
     and the second sweep still completes and produces a full point set.
  2. Send `CMD_RELEASE_RELAY` (via `SpiMcuSource.release_relay()` or the new
     GUI button) and confirm the relay audibly releases.
  3. Trigger a sweep purely via `SpiMcuSource.start_sweep()` (or the GUI's
     Start Sweep button) with `But1` never touched, and confirm it behaves
     identically to a `But1`-triggered sweep (same defmt output shape, same
     `request_sweep()`-fetchable result).
  4. Deliberately force a safety-cutoff abort (per plan 016's on-target test
     procedure) and confirm the relay stays engaged afterward (new
     behavior - see the flagged safety change above) rather than releasing.

## Done criteria

- [ ] `cargo build --release --locked` / `cargo clippy --release --locked --
      -D warnings` / `cargo fmt --check` clean
- [ ] `uv run pytest tests/ -q` all pass (21 tests in `test_spi_mcu.py`, 2
      new for this plan), `uv run ruff check .` / `uv run ruff format
      --check .` clean
- [ ] Step 6's queue smoke test passes without hardware
- [ ] README documents the two new commands and the relay's new explicit
      lifetime
- [ ] `improve/2026-07-18/plans/README.md` row updated
- [ ] On-target: two consecutive sweeps (But1 or Pi-triggered) run without
      the relay re-clicking between them - **not yet confirmed, needs the
      board**
- [ ] On-target: `CMD_RELEASE_RELAY` visibly releases the relay - **not yet
      confirmed**
- [ ] On-target: GUI's Start Sweep / Release Relay buttons work end-to-end
      against real hardware - **not yet confirmed**

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts
  above (drift since this plan was written - see the drift-check command).
- A safety-cutoff abort mid-sweep, with the relay now staying engaged
  afterward, produces any on-target symptom the operator doesn't expect
  (heating, unexpected voltage/current, anything electrically surprising) -
  this is the flagged open safety question above; it needs an operator
  call, not a code fix, if it happens.
- `Signal::signal()`'s "latest value wins" behavior turns out to drop a
  command the operator actually needed (e.g. a rapid double-click on the
  GUI silently loses the first click) - stop and ask whether a queued
  (not overwrite-on-pending) channel is needed instead
  (`embassy_sync::channel::Channel`), rather than silently switching to one.
- Two threads in `curve_tracer_server.py` end up able to call into the same
  `SpiMcuSource` concurrently despite the queue (a bug in the routing, not
  a design gap) - stop, this is a real SPI wire-corruption risk, not just a
  logic bug.
- A step's on-target verification fails twice after a reasonable fix
  attempt.

## Maintenance notes

- If a third Pi-triggerable tracer action is ever needed, extend
  `TracerCommand` rather than adding a fourth raw `CMD_*` byte parallel to
  it - keep the enum as the single source of truth both `spi_pio_task` and
  `curve_tracer_task` key off, rather than duplicating byte-matching logic.
- The `_TRACER_SWEEP_POINTS`-style triple-duplication risk flagged in plan
  018's maintenance notes now also applies to `CMD_START_SWEEP`/
  `CMD_RELEASE_RELAY`'s values - keep `spi_mcu.py`'s copies byte-for-byte in
  sync with `spi_slave_pio.rs`'s.
- This plan deliberately does not add any ack/confirmation that a
  `start_sweep`/`release_relay` command was actually received (unlike the
  bulk-dump handshake's `SendAck` step) - a checksum-failed command is
  simply dropped with no Pi-visible symptom beyond the expected effect not
  happening. If that turns out to matter in practice, a future plan should
  add one, mirroring the ack byte's bit-flag pattern from plan 018.
- The relay's new "stays engaged until explicitly released" lifetime means
  a Pi-side crash or `SpiMcuSource` teardown mid-session no longer
  guarantees the relay releases on its own (previously, the end of any
  single sweep always released it). `SpiMcuSource.__exit__` already calls
  `soft_stop()` (drives duty to 0) but does **not** call `release_relay()` -
  worth deciding in a follow-up whether it should, or whether leaving that
  to the operator/GUI is the right call for this workflow.
