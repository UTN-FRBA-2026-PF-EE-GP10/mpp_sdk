//! PIO-based SPI slave for the RP2040.
//!
//! The PL022 in slave mode reliably emits only one byte per CS-low period on
//! the RP2040, which breaks multi-byte transactions from a normal SPI master.
//! This module replaces it with a PIO state machine that handles arbitrary
//! multi-byte frames with CS held continuously low.
//!
//! TX uses a DMA channel to feed the TX FIFO via hardware DREQ — no embassy
//! scheduler involvement mid-frame, so there is no FIFO underrun even at 8 MHz
//! with frames longer than the 4-word FIFO depth.
//!
//! Hardcoded wiring (must match the RPi → Pico cabling):
//!   GPIO10 = SCK   (input)
//!   GPIO11 = MISO  (output, slave drives)
//!   GPIO12 = MOSI  (input)
//!   GPIO13 = CS    (input, active low)
//!
//! Mode 0 (CPOL=0, CPHA=0), MSB-first, 8-bit frames.
//!
//! Frame recovery: a short/aborted frame (fewer than 96 SCK edges) can
//! leave the state machine's bit alignment out of sync with no built-in
//! way back. `spi_pio_task` bounds each frame with a timeout and, only on
//! that (rare) failure, forces the state machine back to a clean start via
//! `resync()`. This is deliberately NOT done after every successful frame;
//! see `spi_pio_task`'s doc comment for why routine CPU-side resyncing
//! turned out to corrupt the PIO's own IRQ-driven RX wakeup on target
//! hardware.

use embassy_futures::join::join;
use embassy_rp::dma;
use embassy_rp::peripherals::{PIN_10, PIN_11, PIN_12, PIN_13, PIO0};
use embassy_rp::pio::program::pio_asm;
use embassy_rp::pio::{Config, Direction, InterruptHandler, Pio, ShiftDirection, StateMachine};
use embassy_rp::{Peri, bind_interrupts};
use embassy_time::{Duration, with_timeout};
use portable_atomic::Ordering;

use crate::mode_curve_tracer::{self, SweepResult, TRACER_SWEEP_POINTS, TracerCommand};
use crate::{
    DUTY, FIRMWARE_MODE, FirmwareMode, MEAS_ADC_VOUT_MV, MEAS_I_MA, MEAS_V_MV, PACKET_COUNT,
};

bind_interrupts!(pub struct PioIrqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
});

pub const FRAME_LEN: usize = 12;

// Curve-tracer bulk-read protocol: a distinct, larger SPI transaction
// for fetching sweep results (mode_curve_tracer.rs), kept separate from
// the steady FRAME_LEN telemetry frame it rides alongside. See
// spi_pio_task's doc comment for the full three-step protocol.

/// MOSI command value (one of the 9 spare bytes, index 3) requesting a
/// bulk-dump; unlikely to appear from a zeroed/uninitialized buffer.
const CMD_REQUEST_BULK_DUMP: u8 = 0xB1;
/// Starts a curve-tracer sweep - forwarded to
/// `mode_curve_tracer::curve_tracer_task` via `TRACER_COMMAND`, same
/// checksum protection as `CMD_REQUEST_BULK_DUMP`.
const CMD_START_SWEEP: u8 = 0xB2;
/// Explicitly releases the curve-tracer relay - the relay no longer
/// auto-releases at the end of a sweep, see
/// `mode_curve_tracer::CurveTracer::release_relay`.
const CMD_RELEASE_RELAY: u8 = 0xB3;

/// Maps a MOSI command byte to the `TracerCommand` it should signal into
/// `curve_tracer_task`, if any - the one place that grows when a new
/// Pi-issued tracer command is added, instead of a new copy-pasted match
/// arm in `spi_pio_task`'s `Idle` handling each time.
fn tracer_command_for(cmd: u8) -> Option<TracerCommand> {
    match cmd {
        CMD_START_SWEEP => Some(TracerCommand::StartSweep),
        CMD_RELEASE_RELAY => Some(TracerCommand::ReleaseRelay),
        _ => None,
    }
}
/// First byte of a bulk-read response - lets the Pi tell a genuine
/// bulk-dump frame apart from a torn/mis-synced read before trusting
/// anything else in it.
const BULK_MAGIC: u8 = 0xC5;
/// `[ MAGIC | N_POINTS | (V,I) x TRACER_SWEEP_POINTS | CHECKSUM ]`.
const BULK_FRAME_LEN: usize = 2 + TRACER_SWEEP_POINTS * 4 + 1;
/// Larger of the two frame shapes - `rx`/`tx_buf` are sized to this so
/// `spi_pio_task` can switch between them without a second buffer.
const MAX_FRAME_LEN: usize = if BULK_FRAME_LEN > FRAME_LEN {
    BULK_FRAME_LEN
} else {
    FRAME_LEN
};

/// Returns the configured state machine plus the PIO instruction-memory
/// address its program was loaded at (`resync()` needs this to jump back
/// to the top of the program - see its doc comment for why a hardcoded
/// address would be fragile).
pub fn init(
    pio: Peri<'static, PIO0>,
    pin_sck: Peri<'static, PIN_10>,
    pin_miso: Peri<'static, PIN_11>,
    pin_mosi: Peri<'static, PIN_12>,
    pin_cs: Peri<'static, PIN_13>,
) -> (StateMachine<'static, PIO0, 0>, u8) {
    let Pio {
        mut common,
        mut sm0,
        ..
    } = Pio::new(pio, PioIrqs);

    let sck = common.make_pio_pin(pin_sck);
    let miso = common.make_pio_pin(pin_miso);
    let mosi = common.make_pio_pin(pin_mosi);
    let cs = common.make_pio_pin(pin_cs);

    // PIO program: SPI slave mode 0, 8-bit MSB-first.
    // - preamble: wait for CS to deassert then re-assert (resyncs byte
    //   alignment on a clean frame boundary); the CPU-side resync() is a
    //   fallback for the rare case a frame is aborted mid-transfer, not
    //   the primary mechanism (see the module doc comment)
    // - per bit: drive MISO before SCK rising, sample MOSI on SCK rising
    // - exit bit loop when CS goes high (jmp pin = CS via set_jmp_pin)
    let prg = pio_asm!(
        ".wrap_target",
        "    wait 1 gpio 13", // CS idle (deasserted)
        "    wait 0 gpio 13", // CS asserted -> start of transaction
        "bit_loop:",
        "    out pins, 1",    // setup MISO bit (autopull from TX FIFO)
        "    wait 1 gpio 10", // SCK rising edge
        "    in pins, 1",     // sample MOSI bit (autopush every 8 bits)
        "    jmp pin done",   // CS deasserted? exit (best-effort only)
        "    wait 0 gpio 10", // SCK falling edge — next bit setup
        "    jmp bit_loop",
        "done:",
        ".wrap",
    );

    let loaded = common.load_program(&prg.program);
    let origin = loaded.origin;

    let mut cfg = Config::default();
    cfg.use_program(&loaded, &[]);

    cfg.set_out_pins(&[&miso]);
    cfg.set_in_pins(&[&mosi]);
    cfg.set_jmp_pin(&cs);

    // 8-bit MSB-first via shift-left + threshold 8.
    // TX: byte must sit in the top 8 bits of each u32 word.
    // RX: autopushed u32 has the received byte in bits 7-0.
    cfg.shift_out.direction = ShiftDirection::Left;
    cfg.shift_out.threshold = 8;
    cfg.shift_out.auto_fill = true;

    cfg.shift_in.direction = ShiftDirection::Left;
    cfg.shift_in.threshold = 8;
    cfg.shift_in.auto_fill = true;

    sm0.set_pin_dirs(Direction::Out, &[&miso]);
    sm0.set_pin_dirs(Direction::In, &[&sck, &mosi, &cs]);

    sm0.set_config(&cfg);
    sm0.set_enable(true);

    (sm0, origin)
}

/// Sentinel for "no valid temperature reading" - the MAX31865 driver is
/// implemented but disabled (incompatible probe on the bench, see
/// `main.rs`/README's "Panel temperature" section). An implausible real
/// centi-Celsius reading, so it's unambiguous on the Python side rather
/// than a real (if extreme) value. Swap for a live `MEAS_T_CC` read once
/// the sensor is re-enabled.
const TEMP_NOT_AVAILABLE_CC: i16 = i16::MIN;

/// XOR checksum over the given data bytes - catches single/few-bit
/// corruption cheaply on both a `no_std` target and in plain Python (see
/// plan 014). Shared by both frame directions so the formula only lives
/// in one place.
fn xor_checksum(bytes: &[u8]) -> u8 {
    bytes.iter().fold(0, |acc, b| acc ^ b)
}

/// Build a TX frame (u32 words, byte in top 8 bits for shift_out = Left).
///
/// MISO layout: [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L | TEMP_H
///   | TEMP_L | CHECKSUM | ACK | 0 x 2 ]  (12 bytes total). `CHECKSUM` is
/// the XOR of the 8 preceding data bytes only - must match `spi_mcu.py`/
/// `spi_test.py` exactly, and the `ack` byte does NOT participate in it
/// (the steady frame's checksum contract is unchanged). `ack` is the
/// curve-tracer bulk-read handshake byte: `0x00` in normal operation,
/// `0x80 | point_count` on the one frame that acks a bulk-dump request -
/// see `spi_pio_task`'s doc comment.
fn build_tx_frame(v: u16, i: u16, vout: u16, temp_cc: i16, ack: u8) -> [u32; FRAME_LEN] {
    let data = [
        v.to_be_bytes(),
        i.to_be_bytes(),
        vout.to_be_bytes(),
        (temp_cc as u16).to_be_bytes(),
    ];
    let bytes: [u8; 8] = core::array::from_fn(|idx| data[idx / 2][idx % 2]);
    let checksum = xor_checksum(&bytes);

    let mut words = [0u32; FRAME_LEN];
    let all = bytes
        .iter()
        .chain(core::iter::once(&checksum))
        .chain(core::iter::once(&ack));
    for (word, byte) in words.iter_mut().zip(all) {
        *word = (*byte as u32) << 24;
    }
    words
}

/// Build a bulk-read TX frame: `[ MAGIC | N_POINTS | (V_H|V_L|I_H|I_L) x
/// TRACER_SWEEP_POINTS | CHECKSUM ]`. `CHECKSUM` is the XOR of every
/// preceding byte (magic, count, and all point bytes) - reuses
/// `xor_checksum` like the steady frame, just over a different byte range.
/// `sweep.points` beyond `sweep.count` are the zeroed unfilled tail from an
/// aborted sweep (`mode_curve_tracer::SweepResult`) - sent as-is; the Pi
/// only trusts the first `sweep.count` points.
fn build_bulk_tx_frame(sweep: &SweepResult) -> [u32; BULK_FRAME_LEN] {
    let mut bytes = [0u8; BULK_FRAME_LEN - 1];
    bytes[0] = BULK_MAGIC;
    bytes[1] = sweep.count as u8;
    for (idx, (v, i)) in sweep.points.iter().enumerate() {
        let base = 2 + idx * 4;
        bytes[base..base + 2].copy_from_slice(&v.to_be_bytes());
        bytes[base + 2..base + 4].copy_from_slice(&i.to_be_bytes());
    }
    let checksum = xor_checksum(&bytes);

    let mut words = [0u32; BULK_FRAME_LEN];
    let all = bytes.iter().chain(core::iter::once(&checksum));
    for (word, byte) in words.iter_mut().zip(all) {
        *word = (*byte as u32) << 24;
    }
    words
}

/// Time budget for one 12-byte frame's RX side. At the Pi's control period
/// (1 kHz nominal) a normal frame completes in microseconds even at a
/// conservative SPI clock; 100 ms is generous headroom that only trips on a
/// genuinely stalled/aborted transfer, not jitter.
const FRAME_TIMEOUT: Duration = Duration::from_millis(100);

/// Consecutive frame timeouts (~100 ms each) after which the SPI master is
/// considered gone, not just briefly glitching: `spi_pio_task` forces
/// `DUTY` to 0 so the gate stops switching instead of free-running the
/// last commanded duty with no host watching. Resets on the next valid
/// frame.
const LINK_LOST_TIMEOUTS: u32 = 5; // ~500 ms of total silence

/// Force the state machine back to a known-clean state: halted, FIFOs
/// flushed, program counter at instruction `origin` (the top of
/// `.wrap_target`, i.e. the `wait 1 gpio 13` CS-idle check), then resumed.
///
/// Called only from the timeout-recovery path in `spi_pio_task` - see its
/// doc comment for why this must NOT run after every successful frame.
///
/// Jumps to `origin` (the program's actual load address in the PIO's
/// shared instruction memory, captured once at `init()` time via
/// `exec_jmp` - embassy-rp's own helper for this, instead of a hand-rolled
/// raw instruction word). `restart()` additionally clears the ISR/OSR and
/// shift counters (`clear_fifos()` covers the FIFO contents; `restart()`
/// does not touch the program counter, which is why the explicit jump
/// above is still required).
fn resync(sm: &mut StateMachine<'static, PIO0, 0>, origin: u8) {
    sm.set_enable(false);
    sm.clear_fifos();
    unsafe {
        sm.exec_jmp(origin);
    }
    sm.restart();
    sm.set_enable(true);
}

/// Curve-tracer bulk-read handshake - drives which frame shape
/// `spi_pio_task`'s next exchange uses. All three states use `FRAME_LEN`
/// except `DoBulk`, the one exchange that uses `BULK_FRAME_LEN`:
///
/// 1. `Idle`: steady `FRAME_LEN` telemetry frames. If the Pi's MOSI spare
///    byte carries `CMD_REQUEST_BULK_DUMP` and a sweep result is available
///    (`mode_curve_tracer::take_last_sweep()`), advance to `SendAck`.
/// 2. `SendAck(sweep)`: still a `FRAME_LEN` exchange - its TX carries the
///    ack (`0x80 | point_count`) in the frame's first spare MISO byte.
///    Once the Pi reads that ack (from this exchange's RX, on its side),
///    it issues the bulk-sized transaction next - so regardless of this
///    exchange's own RX content, always advance to `DoBulk`.
/// 3. `DoBulk(sweep)`: this exchange itself is the `BULK_FRAME_LEN`
///    transaction (`build_bulk_tx_frame`); its RX is dummy bytes, not
///    parsed. Always returns to `Idle` afterward - a sweep result is
///    fetched at most once.
///
/// A frame timeout at any point (Pi didn't follow through, or a torn
/// frame) resets straight to `Idle` rather than trying to resume mid
/// handshake - see the timeout branch in `spi_pio_task`.
enum BulkState {
    Idle,
    SendAck(SweepResult),
    DoBulk(SweepResult),
}

/// Applies one `FRAME_LEN` exchange's RX as a normal duty-update frame -
/// shared by the `Idle` and `SendAck` cases (both are steady-shaped
/// frames from the Pi's own duty-control perspective; only `DoBulk`'s RX
/// is dummy/unparsed). See `spi_pio_task`'s doc comment for the checksum
/// contract. Returns the validated `cmd` byte (`rx[3]`) if the checksum
/// passed, `None` otherwise - `cmd` participates in `CHECKSUM`
/// (`duty_h ^ duty_l ^ cmd`) precisely so a corrupted frame can't spoof
/// `CMD_REQUEST_BULK_DUMP` by chance: a bit flip landing on `cmd` alone
/// now also mismatches the checksum, same as a flip on `duty_h`/`duty_l`
/// already did. `cmd` is `0` on every normal poll frame, and XOR with `0`
/// is a no-op, so this doesn't change the checksum's value for the
/// steady-state case - only `spi_mcu.py`'s `request_sweep()`, which sends
/// a nonzero `cmd` deliberately, needed a matching update.
fn apply_duty_frame(
    rx: &[u32],
    last_logged_duty: &mut Option<u16>,
    checksum_failures: &mut u32,
) -> Option<u8> {
    // RX autopush puts byte in bits 7-0 (shift_in = Left).
    let duty_h = rx[0] as u8;
    let duty_l = rx[1] as u8;
    let received_checksum = rx[2] as u8;
    let cmd = rx[3] as u8;

    if xor_checksum(&[duty_h, duty_l, cmd]) == received_checksum {
        let duty = ((duty_h as u16) << 8) | duty_l as u16;
        DUTY.store(duty, Ordering::Relaxed);
        PACKET_COUNT.fetch_add(1, Ordering::Relaxed);

        // Log only on change - at the Pi's control period this would
        // otherwise flood RTT every frame; V/I are already logged
        // periodically by sensors_task.
        if *last_logged_duty != Some(duty) {
            defmt::info!("rx: duty={}%", duty as u32 * 100 / 65535);
            *last_logged_duty = Some(duty);
        }
        Some(cmd)
    } else {
        // Corrupted-but-complete frame (plan 014): keep the last-good
        // DUTY rather than apply garbage, and don't act on `cmd` either -
        // a corrupted frame's command byte is not trustworthy. Rate
        // limited - a jammed link could otherwise flood RTT every frame.
        *checksum_failures += 1;
        if *checksum_failures == 1 || checksum_failures.is_multiple_of(100) {
            defmt::warn!(
                "spi_pio_task: MOSI checksum mismatch, keeping last duty ({} total)",
                checksum_failures
            );
        }
        None
    }
}

/// Builds the TX buffer for `state`'s exchange - always reads live
/// `MEAS_*` atomics (builds the next telemetry frame fresh each time,
/// same as before the bulk-read handshake existed), padded to
/// `MAX_FRAME_LEN`; only the first `FRAME_LEN`/`BULK_FRAME_LEN` words are
/// ever pushed to DMA (the caller slices by the same `state` match).
fn build_tx_buf_for_state(state: &BulkState) -> [u32; MAX_FRAME_LEN] {
    let mut buf = [0u32; MAX_FRAME_LEN];
    match state {
        BulkState::DoBulk(sweep) => {
            buf[..BULK_FRAME_LEN].copy_from_slice(&build_bulk_tx_frame(sweep));
        }
        BulkState::SendAck(sweep) => {
            let v = MEAS_V_MV.load(Ordering::Relaxed);
            let i = MEAS_I_MA.load(Ordering::Relaxed);
            let vout = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
            let ack = 0x80 | (sweep.count as u8);
            buf[..FRAME_LEN].copy_from_slice(&build_tx_frame(
                v,
                i,
                vout,
                TEMP_NOT_AVAILABLE_CC,
                ack,
            ));
        }
        BulkState::Idle => {
            let v = MEAS_V_MV.load(Ordering::Relaxed);
            let i = MEAS_I_MA.load(Ordering::Relaxed);
            let vout = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
            buf[..FRAME_LEN].copy_from_slice(&build_tx_frame(v, i, vout, TEMP_NOT_AVAILABLE_CC, 0));
        }
    }
    buf
}

/// SPI exchange task — full-duplex DMA TX + async RX via `join`.
///
/// DMA feeds the PIO TX FIFO in hardware (DREQ-paced, ns latency), so the
/// 4-deep FIFO never underruns even at 8 MHz with a 12-byte frame.
///
/// `join` runs TX DMA and RX `wait_pull` concurrently using `sm.rx_tx()`
/// split borrows so both halves can be borrowed simultaneously. The whole
/// exchange is wrapped in a timeout so a short/aborted frame (fewer than 96
/// SCK edges) cannot leave the DMA transfer and the RX pull stuck forever;
/// on timeout the frame is dropped (a single torn read must not overwrite
/// `DUTY` with garbage) and the state machine is forced back to a clean
/// starting point via `resync()`. After `LINK_LOST_TIMEOUTS` consecutive
/// timeouts the master is considered gone, not just glitching, and `DUTY`
/// is forced to 0 - see that const's doc comment.
///
/// `resync()` runs ONLY on that (rare, exceptional) timeout path, not after
/// every successful frame. An earlier version of this fix called it every
/// frame on the theory that the PIO program's own CS-edge resync is
/// unreachable in steady state - on-target testing showed that routinely
/// disabling/flushing/restarting the state machine every frame corrupts
/// its IRQ-driven RX wakeup (`wait_pull()` never resolves again after a
/// couple of frames, with no timeout firing either - consistent with the
/// PIO's interrupt latch ending up in a state embassy's driver never sees
/// a fresh edge on). Confining `resync()` to genuine failures keeps the
/// steady-state path untouched and only exercises the recovery code when
/// there is actually something to recover from.
///
/// MOSI (RPi→Pico): [ DUTY_H | DUTY_L | CHECKSUM | CMD | 0 x 8 ]
/// MISO (Pico→RPi): [ V_H | V_L | I_H | I_L | VOUT_H | VOUT_L | TEMP_H
///   | TEMP_L | CHECKSUM | ACK | 0 x 2 ]
///
/// `CHECKSUM` (plan 014) is an XOR over the preceding data bytes in each
/// direction (`xor_checksum`) - it does not grow the frame, both
/// directions still 12 bytes. A MOSI checksum mismatch is treated like a
/// torn frame: `DUTY` is left at its last-good value (never zeroed by a
/// single mismatch) and does NOT count toward `consecutive_timeouts` -
/// the master is clearly still talking, just corrupted, a different
/// failure mode than sustained silence.
///
/// `CMD`/`ACK` are the curve-tracer bulk-read handshake bytes - see
/// `BulkState`'s doc comment for the full three-step protocol. They
/// ride in the steady frame's spare bytes. `CMD` (MOSI) participates in
/// `CHECKSUM` (`duty_h ^ duty_l ^ cmd` - see `apply_duty_frame`'s doc
/// comment for why); `ACK` (MISO) does not (see `build_tx_frame`'s doc
/// comment). The handshake's own third step is a **separate**, larger
/// (`BULK_FRAME_LEN`-byte) transaction, not part of this steady frame at
/// all - `this_frame_len` below switches to it only for that one exchange.
#[embassy_executor::task]
pub async fn spi_pio_task(
    mut sm: StateMachine<'static, PIO0, 0>,
    origin: u8,
    mut dma: dma::Channel<'static>,
) {
    defmt::info!(
        "spi_pio_task: PIO SPI slave running (DMA TX, {} byte frame, {} byte bulk-read frame)",
        FRAME_LEN,
        BULK_FRAME_LEN
    );

    let mut bulk_state = BulkState::Idle;
    let mut tx_buf = build_tx_buf_for_state(&bulk_state);
    let mut consecutive_timeouts: u32 = 0;
    let mut last_logged_duty: Option<u16> = None;
    let mut checksum_failures: u32 = 0;

    loop {
        let this_frame_len = match &bulk_state {
            BulkState::DoBulk(_) => BULK_FRAME_LEN,
            BulkState::Idle | BulkState::SendAck(_) => FRAME_LEN,
        };

        let mut rx = [0u32; MAX_FRAME_LEN];

        // TX (DMA) and RX (wait_pull) run concurrently via split borrows.
        let exchange = {
            let (rx_half, tx_half) = sm.rx_tx();
            join(
                tx_half.dma_push(&mut dma, &tx_buf[..this_frame_len], false),
                async {
                    for slot in &mut rx[..this_frame_len] {
                        *slot = rx_half.wait_pull().await;
                    }
                },
            )
        };

        if with_timeout(FRAME_TIMEOUT, exchange).await.is_err() {
            // No Pi attached is expected/normal in PowerSupply mode
            // (mode_power_supply.rs) - suppress the WARN spam there.
            let log_link_state = FIRMWARE_MODE != FirmwareMode::PowerSupply;

            // Dropping `exchange` here cancels the DMA push (its Drop impl
            // aborts the channel) and the pending `wait_pull`s.
            // Re-arm TX with the last-known-good V/I for the next attempt;
            // DUTY is left untouched by a single torn frame (see doc
            // comment above) but forced to 0 if the master appears gone.
            consecutive_timeouts += 1;
            // Rate-limited like checksum_failures below - a sustained
            // outage would otherwise flood RTT every 100 ms.
            if log_link_state
                && (consecutive_timeouts == 1 || consecutive_timeouts.is_multiple_of(100))
            {
                defmt::warn!(
                    "spi_pio_task: frame timeout, resyncing (duty unchanged) ({} consecutive)",
                    consecutive_timeouts
                );
            }
            resync(&mut sm, origin);
            if consecutive_timeouts == LINK_LOST_TIMEOUTS && log_link_state {
                defmt::error!("spi_pio_task: link lost, forcing duty to 0");
            }
            if consecutive_timeouts >= LINK_LOST_TIMEOUTS {
                DUTY.store(0, Ordering::Relaxed);
            }
            // A torn/aborted frame mid bulk-read handshake must not leave
            // this task expecting a frame shape the Pi has moved on from -
            // always fall back to Idle, same reasoning as DUTY being safe
            // to leave unresolved on a single miss (see BulkState's doc
            // comment).
            bulk_state = BulkState::Idle;
            tx_buf = build_tx_buf_for_state(&bulk_state);
            continue;
        }
        consecutive_timeouts = 0;

        bulk_state = match bulk_state {
            BulkState::DoBulk(_) => {
                defmt::info!("spi_pio_task: bulk-dump transaction complete");
                BulkState::Idle
            }
            BulkState::SendAck(sweep) => {
                apply_duty_frame(&rx, &mut last_logged_duty, &mut checksum_failures);
                BulkState::DoBulk(sweep)
            }
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
                    Some(cmd) => {
                        if let Some(tracer_cmd) = tracer_command_for(cmd) {
                            mode_curve_tracer::TRACER_COMMAND.signal(tracer_cmd);
                        }
                        BulkState::Idle
                    }
                    None => BulkState::Idle,
                }
            }
        };

        tx_buf = build_tx_buf_for_state(&bulk_state);
    }
}
