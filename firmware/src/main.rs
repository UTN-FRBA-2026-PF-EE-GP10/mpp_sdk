#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_rp::pac;
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_time::Timer;
use portable_atomic::{AtomicU16, Ordering};
use {defmt_rtt as _, panic_probe as _};

// ── Shared state (written by SPI/ADC tasks, read by main) ────────────────────
static DUTY: AtomicU16 = AtomicU16::new(0x8000); // 50 % initial
static SIM_V: AtomicU16 = AtomicU16::new(2048);
static SIM_I: AtomicU16 = AtomicU16::new(512);

// ── Pseudo-random (LCG) for simulated ADC readings ───────────────────────────
fn lcg(s: &mut u32) -> u16 {
    *s = s.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    ((*s >> 20) & 0xFFF) as u16
}

// ── SPI1 slave — hardware setup ───────────────────────────────────────────────
//
// Protocol (6-byte frame, full-duplex):
//   MOSI (RPi → Pico):  [ DUTY_H | DUTY_L | 0x00 | 0x00 | 0x00 | 0x00 ]
//   MISO (Pico → RPi):  [ 0x00   | 0x00   | V_H  | V_L  | I_H  | I_L  ]
//
// Pins: GPIO10 SCK | GPIO11 TX/MISO | GPIO12 RX/MOSI | GPIO13 CSn
fn spi1_init_slave() {
    // Bring SPI1 out of reset
    pac::RESETS.reset().modify(|w| w.set_spi1(true));
    pac::RESETS.reset().modify(|w| w.set_spi1(false));
    while !pac::RESETS.reset_done().read().spi1() {}

    // 8-bit Motorola SPI mode 0 (CPOL=0, CPHA=0)
    pac::SPI1.cr0().write(|w| {
        w.set_dss(7); // 8-bit
        w.set_frf(0); // Motorola frame format
        w.set_spo(false);
        w.set_sph(false);
        w.set_scr(0);
    });

    // Enable in slave mode
    pac::SPI1.cr1().write(|w| {
        w.set_ms(true); // slave
        w.set_sse(true);
    });

    // Flush stale RX bytes
    while pac::SPI1.sr().read().rne() {
        let _ = pac::SPI1.dr().read().data();
    }

    // Assign SPI1 function (funcsel=1) to GPIO10-13
    for gpio in [10usize, 11, 12, 13] {
        pac::IO_BANK0.gpio(gpio).ctrl().write(|w| w.set_funcsel(1));
    }
}

// Pre-load the TX FIFO with the response for the next master transaction.
// Must be called before the master asserts CS.
fn spi1_preload_tx(v: u16, i: u16) {
    let frame = [0u8, 0, (v >> 8) as u8, v as u8, (i >> 8) as u8, i as u8];
    for &b in &frame {
        while !pac::SPI1.sr().read().tnf() {} // wait: TX not full
        pac::SPI1.dr().write(|w| w.set_data(b as u16));
    }
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

/// Simulates ADC sampling every 10 ms.
/// Replace body with real `embassy_rp::adc` reads when board is connected.
#[embassy_executor::task]
async fn adc_task() {
    let mut rng: u32 = 0xDEAD_BEEF;
    loop {
        SIM_V.store(2000 + (lcg(&mut rng) & 0xFF), Ordering::Relaxed);
        SIM_I.store(500 + (lcg(&mut rng) & 0x7F), Ordering::Relaxed);
        Timer::after_millis(10).await;
    }
}

/// SPI1 slave — waits for full 6-byte frame, applies received duty cycle,
/// pre-loads next response.
#[embassy_executor::task]
async fn spi_slave_task() {
    spi1_init_slave();
    spi1_preload_tx(SIM_V.load(Ordering::Relaxed), SIM_I.load(Ordering::Relaxed));

    let mut rx = [0u8; 6];
    loop {
        // Receive 6 bytes; yield between polls so other tasks keep running
        for slot in &mut rx {
            loop {
                if pac::SPI1.sr().read().rne() {
                    break;
                }
                embassy_futures::yield_now().await;
            }
            *slot = pac::SPI1.dr().read().data() as u8;
        }

        let duty = ((rx[0] as u16) << 8) | rx[1] as u16;
        DUTY.store(duty, Ordering::Relaxed);

        defmt::info!("SPI rx: duty=0x{:04x}", duty);

        // Pre-load response for the next transaction
        spi1_preload_tx(SIM_V.load(Ordering::Relaxed), SIM_I.load(Ordering::Relaxed));
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    defmt::info!("mpp-firmware booted");

    // PWM on GPIO25 (onboard LED). Switch to PIN_15 / PWM_SLICE7B when board is ready.
    let mut pwm_cfg = PwmConfig::default();
    pwm_cfg.top = 0xFFFF;
    pwm_cfg.compare_b = 0x8000;
    let mut pwm = Pwm::new_output_b(p.PWM_SLICE4, p.PIN_25, pwm_cfg.clone());

    spawner.spawn(adc_task().unwrap());
    spawner.spawn(spi_slave_task().unwrap());

    loop {
        let duty = DUTY.load(Ordering::Relaxed);
        pwm_cfg.compare_b = duty;
        pwm.set_config(&pwm_cfg);

        defmt::info!(
            "duty=0x{:04x}  V_sim={}  I_sim={}",
            duty,
            SIM_V.load(Ordering::Relaxed),
            SIM_I.load(Ordering::Relaxed),
        );

        Timer::after_millis(100).await;
    }
}
