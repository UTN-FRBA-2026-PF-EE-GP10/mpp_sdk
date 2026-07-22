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
//! `resync()`. This is deliberately NOT done after every successful frame
//! - see `spi_pio_task`'s doc comment for why routine CPU-side resyncing
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

use crate::{DUTY, MEAS_I_MA, MEAS_V_MV};

bind_interrupts!(pub struct PioIrqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
});

pub const FRAME_LEN: usize = 12;

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

/// Build a TX frame (u32 words, byte in top 8 bits for shift_out = Left).
///
/// MISO layout: [ V_H | V_L | I_H | I_L | 0 … 0 ]  (12 bytes total)
fn build_tx_frame(v: u16, i: u16) -> [u32; FRAME_LEN] {
    [
        u32::from_be_bytes([(v >> 8) as u8, 0, 0, 0]),
        u32::from_be_bytes([v as u8, 0, 0, 0]),
        u32::from_be_bytes([(i >> 8) as u8, 0, 0, 0]),
        u32::from_be_bytes([i as u8, 0, 0, 0]),
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
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
/// MOSI (RPi→Pico): [ DUTY_H | DUTY_L | 0 … 0 ]  (12 bytes)
/// MISO (Pico→RPi): [ V_H   | V_L    | I_H | I_L | 0 … 0 ]
#[embassy_executor::task]
pub async fn spi_pio_task(
    mut sm: StateMachine<'static, PIO0, 0>,
    origin: u8,
    mut dma: dma::Channel<'static>,
) {
    defmt::info!(
        "spi_pio_task: PIO SPI slave running (DMA TX, {} byte frame)",
        FRAME_LEN
    );

    let mut tx_buf = build_tx_frame(
        MEAS_V_MV.load(Ordering::Relaxed),
        MEAS_I_MA.load(Ordering::Relaxed),
    );
    let mut consecutive_timeouts: u32 = 0;

    loop {
        let mut rx = [0u32; FRAME_LEN];

        // TX (DMA) and RX (wait_pull) run concurrently via split borrows.
        let exchange = {
            let (rx_half, tx_half) = sm.rx_tx();
            join(tx_half.dma_push(&mut dma, &tx_buf, false), async {
                for slot in &mut rx {
                    *slot = rx_half.wait_pull().await;
                }
            })
        };

        if with_timeout(FRAME_TIMEOUT, exchange).await.is_err() {
            // Dropping `exchange` here cancels the DMA push (its Drop impl
            // aborts the channel) and the pending `wait_pull`s.
            defmt::warn!("spi_pio_task: frame timeout, resyncing (duty unchanged)");
            resync(&mut sm, origin);
            // Re-arm TX with the last-known-good V/I for the next attempt;
            // DUTY is left untouched by a single torn frame (see doc
            // comment above) but forced to 0 if the master appears gone.
            consecutive_timeouts += 1;
            if consecutive_timeouts == LINK_LOST_TIMEOUTS {
                defmt::warn!("spi_pio_task: link lost, forcing duty to 0");
            }
            if consecutive_timeouts >= LINK_LOST_TIMEOUTS {
                DUTY.store(0, Ordering::Relaxed);
            }
            continue;
        }
        consecutive_timeouts = 0;

        // RX autopush puts byte in bits 7-0 (shift_in = Left).
        let duty = ((rx[0] as u8 as u16) << 8) | rx[1] as u8 as u16;
        DUTY.store(duty, Ordering::Relaxed);

        let v = MEAS_V_MV.load(Ordering::Relaxed);
        let i = MEAS_I_MA.load(Ordering::Relaxed);
        defmt::info!(
            "rx: duty={}% | tx: V={} mV I={} mA",
            duty as u32 * 100 / 65535,
            v,
            i
        );

        tx_buf = build_tx_frame(v, i);
    }
}
