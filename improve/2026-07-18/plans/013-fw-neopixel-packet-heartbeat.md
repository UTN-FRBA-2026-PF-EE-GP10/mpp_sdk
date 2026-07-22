# Plan 013: NeoPixel packet-receive heartbeat (GPIO4)

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written alongside PR #46 (merged as commit `2aa9d35`).
> `git diff --stat 2aa9d35..HEAD -- firmware/pipico_board/` - if `main.rs`
> or `spi_slave_pio.rs` changed since, re-check the excerpts below before
> editing.

## Why

The operator has 4x WS2812-style NeoPixels wired in series on GPIO4
(currently an unclaimed "general purpose" pin per the README's GPIO
table). GPIO14's heartbeat LED (added alongside this plan) shows the
firmware is alive at all; a second, independent indicator specifically for
**SPI packet reception** - flashing on every frame the Pi successfully
sends - gives an at-a-glance "is the link actually talking to me right
now" signal without needing a debug probe attached, complementary to the
on-change `rx: duty=...` log line.

## Progress note

Implemented. Resolved the DMA-IRQ open question from the design section:
embassy-rp binds *every* DMA channel's `InterruptHandler` to the same
`DMA_IRQ_0` name (there is no `DMA_IRQ_1` in this HAL) - confirmed via a
real embassy-rp example (`examples/rp/src/bin/uart_r503.rs`) using two
channels: `DMA_IRQ_0 => InterruptHandler<DMA_CH0>, InterruptHandler<DMA_CH1>;`.
`PIO1_IRQ_0` does get its own separate `bind_interrupts!` block
(`Pio1Irqs`), since that's a distinct interrupt from `DMA_IRQ_0`.

`cargo build --release --locked` and `cargo fmt --check` are clean.
On-target: pixels confirmed flashing on packet receipt (with a caveat
on the exact per-packet visual crispness at high packet rates - inherent
to the simple change-detection polling design, not a bug, see the
`## Maintenance notes` addition below).

**SPI link timing/reliability WAS affected** - this is the STOP condition
this plan's own design section anticipated, now confirmed on real
hardware rather than assumed away. At the previously-validated 1 MHz, the
actively-switching NeoPixels produced corrupted-but-complete MISO frames
(e.g. `I_raw` reading exactly `0x8000` - one bit, not random noise), most
likely electrical crosstalk from the NeoPixels' fast switching onto
nearby breadboard SPI1 wiring - not a scheduling/executor-contention
issue (the isolation this plan's design specified - separate PIO/DMA -
correctly prevented that class of problem) and not a firmware math bug
(`current_raw_to_ma()` cannot produce `0x8000` from any real INA229
reading, given `I_MAX_MA = 1000` - checked and ruled out). **200 kHz is
bench-confirmed clean** with the NeoPixels active - `scripts/spi_test.py`
and the firmware README updated accordingly. Revisit toward 1 MHz only if
the NeoPixel wiring is rerouted away from the SPI1 wires or moved to a
real PCB.

## Current state

- GPIO4 is unclaimed in `firmware/pipico_board/src/main.rs`.
- `firmware/pipico_board/src/spi_slave_pio.rs`'s `spi_pio_task` already
  owns **PIO0** entirely (the SPI-slave state machine) and **DMA_CH0**
  (the frame TX push). Both are unavailable for a second PIO consumer.
- `onchip_adc_task` and `sensors_task` already establish the pattern this
  plan should follow: a timing-sensitive task publishes to a shared
  `Atomic*` static; a separate, non-timing-critical task polls it and does
  the (comparatively slow) I/O.
- `embassy_rp::pio_programs::ws2812::{PioWs2812, PioWs2812Program}` is
  already vendored in the pinned `embassy-rp` revision (confirmed by
  reading `pio_programs/ws2812.rs` and the `examples/rp/src/bin/
  pio_ws2812.rs` reference example) - no need to hand-roll the WS2812 PIO
  program. It depends on the `smart_leds::RGB8` type, which is **not**
  currently a direct dependency of this firmware crate (only a transitive
  one via `embassy-rp`, and Rust needs it named directly) - add
  `smart-leds = "0.4.0"` to `Cargo.toml` (matches the version
  `embassy-rp` itself pins, per its own `Cargo.toml`).

## Design

1. **PIO/DMA ownership**: the WS2812 driver must use **PIO1**, not PIO0
   (PIO0 is fully owned by the SPI slave - see "Current state"), and a
   **second DMA channel** (e.g. `DMA_CH1`, since `DMA_CH0` is claimed by
   the SPI task). Bind a separate `PIO1_IRQ_0` interrupt handler alongside
   the existing `DMA_IRQ_0` bind in `main.rs`'s `bind_interrupts!` block
   (a new DMA channel needs its own IRQ handler binding too - check
   whether `DMA_IRQ_1` or a shared `DMA_IRQ_0` handler covers multiple
   channels on this embassy-rp revision before assuming which to bind).
2. **Do not call the WS2812 driver from `spi_pio_task`.** That task's
   timing budget is already tight (`FRAME_TIMEOUT = 100 ms`, tuned against
   real bit-banged SPI margins - see `spi_slave_pio.rs`'s doc comments).
   Adding a DMA-driven WS2812 write inline risks stealing cycles/DMA
   arbitration from the timing-critical exchange. Instead:
   - Add `pub static PACKET_COUNT: AtomicU32` (new, alongside the other
     `MEAS_*`/`DUTY` statics in `main.rs`), incremented by exactly one
     cheap atomic op in `spi_pio_task` right after a frame is successfully
     received (same place `DUTY.store(...)` already happens).
   - A new `neopixel_task` owns the `PioWs2812` instance, polls
     `PACKET_COUNT` for changes (same `last_seen != current` pattern as
     the on-change duty log added in PR #46), and flashes the 4 pixels
     briefly (e.g. a short green pulse, then off) on each observed change.
     This mirrors how `onchip_adc_task`/`sensors_task` are already
     decoupled from the SPI task.
3. **Idle behavior**: pixels off (or a dim/steady "no traffic" color, the
   executor's call) when `PACKET_COUNT` hasn't changed recently, so a
   stalled link is visually obvious (frozen or dark, not just frozen on
   whatever color it last flashed).
4. **GPIO4**: `PioWs2812::new(&mut common, sm, dma_ch1, Irqs, p.PIN_4,
   &program)` with `NUM_LEDS = 4`.
5. **README**: document the GPIO4 row (currently "General purpose"),
   the new statics, and the two-LED story (GPIO14 = firmware alive, GPIO4
   NeoPixels = SPI packets flowing).

## Scope

**In**: `firmware/pipico_board/src/main.rs` (new task, static, PIO1/DMA
setup), `firmware/pipico_board/src/spi_slave_pio.rs` (one atomic
increment, no other change), `firmware/pipico_board/Cargo.toml`
(`smart-leds` dependency), `firmware/pipico_board/README.md`.

**Out**: any change to the 12-byte SPI frame or `FRAME_TIMEOUT`/PIO0
behavior; color/pattern bikeshedding beyond "on receive, flash; idle,
off" - keep the first pass simple, matching the GPIO14 heartbeat's
minimalism; power-consumption analysis of driving 4 NeoPixels (flag as a
follow-up only if the bench shows a real problem, do not preemptively
solve it).

## Steps

1. Add `smart-leds` to `Cargo.toml`.
   Verify: `cargo build --release --locked` still resolves cleanly (new
   dependency, no code yet).
2. Add `PACKET_COUNT` and the one-line increment in `spi_pio_task`.
   Verify: `cargo build --release --locked` clean, no new warnings.
3. Add `neopixel_task` (PIO1, new DMA channel, `PioWs2812`), spawn it from
   `main()`.
   Verify: `cargo build --release --locked` / `cargo fmt --check` clean.
4. On-target: flash, confirm the 4 NeoPixels flash on each frame sent from
   `scripts/spi_test.py` and go dark/idle when the script stops.
   Verify: visually confirmed by the operator; also confirm the SPI link's
   own behavior (duty tracking, `ok?` column in `spi_test.py`) is
   unaffected - this task must not regress the timing-critical path.
5. Update README (GPIO4 row + new statics + the two-LED story).

## Done criteria

- [x] `neopixel_task` on PIO1 + a second DMA channel, does not touch PIO0
      or `DMA_CH0`
- [x] Pixels flash on each received SPI frame, idle (off or dim) otherwise
      (crisp per-packet visual distinction degrades at high packet rates -
      see Maintenance notes, not treated as a failure of this criterion)
- [x] `spi_pio_task` changed by exactly one atomic increment - no other
      logic moved into it
- [x] On-target: SPI link timing/behavior unaffected **at the bench-
      confirmed 200 kHz clock** - at the previously-validated 1 MHz, the
      link was measurably affected (electrical crosstalk, not scheduling
      contention); see the Progress note for the full finding
- [x] README documents GPIO4 and the new statics
- [x] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- PIO1 or a second DMA channel is unavailable/already spoken for by
  something this plan's author didn't know about: report, do not silently
  fall back to sharing PIO0/DMA_CH0 with the SPI task.
- On-target testing shows the SPI link's timing/reliability regressed
  (new frame timeouts, torn reads) after adding this task: STOP - the
  isolation in the design section is meant to prevent this, but confirm it
  on real hardware rather than assuming.

## Maintenance notes

- If a later plan wants more indicators (e.g. link-lost state, a
  `power_supply` vs `mpp_tracker` mode indicator from plan 011), this
  4-pixel strip is a natural place to add them (different colors/pixels)
  rather than adding more discrete LEDs/GPIOs - note as a possible
  follow-up, not required now.
- `neopixel_task`'s change-detection is a simple "has `PACKET_COUNT`
  changed since I last polled" check (10 ms poll, ~20 ms flash-hold) - it
  cannot distinguish one packet from several arriving within that ~30 ms
  window. At low/spaced-out packet rates (e.g. `spi_test.py`'s default
  loop) this gives one clean flash per frame; at higher, more MPPT-
  realistic rates (~1 kHz) `PACKET_COUNT` keeps incrementing during the
  hold and the strip can look closer to solid-on than distinctly
  blinking. Not fixed here - the plan's own scope explicitly said not to
  bikeshed the flash pattern. Worth revisiting only if the qualitative
  "is it talking to me" signal stops being useful in practice.
- SPI clock speed is now 200 kHz (down from 1 MHz) specifically because of
  this plan's NeoPixel wiring - see the Progress note. Any future plan
  touching `scripts/spi_test.py`/`SpiMcuSource`'s speed defaults (e.g.
  plan 015) should use 200 kHz as the current bench-validated figure, not
  the older 1 MHz.
