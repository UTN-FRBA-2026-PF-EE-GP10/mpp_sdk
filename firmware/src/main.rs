#![no_std]
#![no_main]

mod spi_slave_pio;

use embassy_executor::Spawner;
use embassy_rp::bind_interrupts;
use embassy_rp::dma;
use embassy_rp::peripherals::DMA_CH0;
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_time::Timer;
use portable_atomic::{AtomicU16, Ordering};
use {defmt_rtt as _, panic_probe as _};

bind_interrupts!(struct DmaIrqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>;
});

// Shared state (written by SPI/ADC tasks, read by main).
pub static DUTY: AtomicU16 = AtomicU16::new(0x8000); // 50 % initial
pub static SIM_V: AtomicU16 = AtomicU16::new(2048);
pub static SIM_I: AtomicU16 = AtomicU16::new(512);

fn lcg(s: &mut u32) -> u16 {
    *s = s.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    ((*s >> 20) & 0xFFF) as u16
}

#[embassy_executor::task]
async fn adc_task() {
    let mut rng: u32 = 0xDEAD_BEEF;
    loop {
        SIM_V.store(2000 + (lcg(&mut rng) & 0xFF), Ordering::Relaxed);
        SIM_I.store(500 + (lcg(&mut rng) & 0x7F), Ordering::Relaxed);
        Timer::after_millis(10).await;
    }
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    defmt::info!("mpp-firmware booted (PIO SPI slave)");

    let mut pwm_cfg = PwmConfig::default();
    pwm_cfg.top = 0xFFFF;
    pwm_cfg.compare_b = 0x8000;
    let mut pwm = Pwm::new_output_b(p.PWM_SLICE4, p.PIN_25, pwm_cfg.clone());

    let sm = spi_slave_pio::init(p.PIO0, p.PIN_10, p.PIN_11, p.PIN_12, p.PIN_13);
    let dma_ch = dma::Channel::new(p.DMA_CH0, DmaIrqs);

    spawner.spawn(adc_task().unwrap());
    spawner.spawn(spi_slave_pio::spi_pio_task(sm, dma_ch).unwrap());

    loop {
        let duty = DUTY.load(Ordering::Relaxed);
        pwm_cfg.compare_b = duty;
        pwm.set_config(&pwm_cfg);
        Timer::after_millis(100).await;
    }
}
