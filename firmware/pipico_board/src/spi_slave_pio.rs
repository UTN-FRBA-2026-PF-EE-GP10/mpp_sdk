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

use embassy_futures::join::join;
use embassy_rp::dma;
use embassy_rp::peripherals::{PIN_10, PIN_11, PIN_12, PIN_13, PIO0};
use embassy_rp::pio::program::pio_asm;
use embassy_rp::pio::{
    Config, Direction, InterruptHandler, Pio, ShiftDirection, StateMachine,
};
use embassy_rp::{Peri, bind_interrupts};
use portable_atomic::Ordering;

use crate::{DUTY, MEAS_I_MA, MEAS_V_MV};

bind_interrupts!(pub struct PioIrqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
});

pub const FRAME_LEN: usize = 12;

pub fn init(
    pio: Peri<'static, PIO0>,
    pin_sck: Peri<'static, PIN_10>,
    pin_miso: Peri<'static, PIN_11>,
    pin_mosi: Peri<'static, PIN_12>,
    pin_cs: Peri<'static, PIN_13>,
) -> StateMachine<'static, PIO0, 0> {
    let Pio { mut common, mut sm0, .. } = Pio::new(pio, PioIrqs);

    let sck = common.make_pio_pin(pin_sck);
    let miso = common.make_pio_pin(pin_miso);
    let mosi = common.make_pio_pin(pin_mosi);
    let cs = common.make_pio_pin(pin_cs);

    // PIO program: SPI slave mode 0, 8-bit MSB-first.
    // - wait for CS to deassert then re-assert (resyncs byte alignment)
    // - per bit: drive MISO before SCK rising, sample MOSI on SCK rising
    // - exit bit loop when CS goes high (jmp pin = CS via set_jmp_pin)
    let prg = pio_asm!(
        ".wrap_target",
        "    wait 1 gpio 13",      // CS idle (deasserted)
        "    wait 0 gpio 13",      // CS asserted -> start of transaction
        "bit_loop:",
        "    out pins, 1",          // setup MISO bit (autopull from TX FIFO)
        "    wait 1 gpio 10",       // SCK rising edge
        "    in pins, 1",           // sample MOSI bit (autopush every 8 bits)
        "    jmp pin done",         // CS deasserted? exit (resync at top)
        "    wait 0 gpio 10",       // SCK falling edge — next bit setup
        "    jmp bit_loop",
        "done:",
        ".wrap",
    );

    let mut cfg = Config::default();
    cfg.use_program(&common.load_program(&prg.program), &[]);

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

    sm0
}

/// Build a TX frame (u32 words, byte in top 8 bits for shift_out = Left).
///
/// MISO layout: [ V_H | V_L | I_H | I_L | 0 … 0 ]  (12 bytes total)
fn build_tx_frame(v: u16, i: u16) -> [u32; FRAME_LEN] {
    [
        u32::from_be_bytes([(v >> 8) as u8, 0, 0, 0]),
        u32::from_be_bytes([v as u8,        0, 0, 0]),
        u32::from_be_bytes([(i >> 8) as u8, 0, 0, 0]),
        u32::from_be_bytes([i as u8,        0, 0, 0]),
        0, 0, 0, 0, 0, 0, 0, 0,
    ]
}

/// SPI exchange task — full-duplex DMA TX + async RX via `join`.
///
/// DMA feeds the PIO TX FIFO in hardware (DREQ-paced, ns latency), so the
/// 4-deep FIFO never underruns even at 8 MHz with a 12-byte frame.
///
/// `join` runs TX DMA and RX `wait_pull` concurrently using `sm.rx_tx()`
/// split borrows so both halves can be borrowed simultaneously.
///
/// MOSI (RPi→Pico): [ DUTY_H | DUTY_L | 0 … 0 ]  (12 bytes)
/// MISO (Pico→RPi): [ V_H   | V_L    | I_H | I_L | 0 … 0 ]
#[embassy_executor::task]
pub async fn spi_pio_task(
    mut sm: StateMachine<'static, PIO0, 0>,
    mut dma: dma::Channel<'static>,
) {
    defmt::info!("spi_pio_task: PIO SPI slave running (DMA TX, {} byte frame)", FRAME_LEN);

    let mut tx_buf = build_tx_frame(
        MEAS_V_MV.load(Ordering::Relaxed),
        MEAS_I_MA.load(Ordering::Relaxed),
    );

    loop {
        let mut rx = [0u32; FRAME_LEN];

        // TX (DMA) and RX (wait_pull) run concurrently via split borrows.
        {
            let (rx_half, tx_half) = sm.rx_tx();
            join(
                tx_half.dma_push(&mut dma, &tx_buf, false),
                async {
                    for slot in &mut rx {
                        *slot = rx_half.wait_pull().await;
                    }
                },
            )
            .await;
        }

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
