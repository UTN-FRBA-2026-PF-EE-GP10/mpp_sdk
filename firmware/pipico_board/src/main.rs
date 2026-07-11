#![no_std]
#![no_main]

#[cfg(not(feature = "sim-adc"))]
mod ina229;
mod spi_slave_pio;

use embassy_executor::Spawner;
use embassy_rp::bind_interrupts;
use embassy_rp::dma;
#[cfg(not(feature = "sim-adc"))]
use embassy_rp::gpio::{Level, Output};
use embassy_rp::peripherals::DMA_CH0;
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
#[cfg(not(feature = "sim-adc"))]
use embassy_rp::spi::{Config as SpiConfig, Phase, Polarity, Spi};
use embassy_time::Timer;
#[cfg(not(feature = "sim-adc"))]
use ina229::Ina229;
use portable_atomic::{AtomicU16, Ordering};
use {defmt_rtt as _, panic_probe as _};

bind_interrupts!(struct DmaIrqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>;
});

// Shared state (written by SPI/ADC tasks, read by main).
pub static DUTY: AtomicU16 = AtomicU16::new(0x8000); // 50 % initial
pub static MEAS_V_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_I_MA: AtomicU16 = AtomicU16::new(0);

#[cfg(feature = "sim-adc")]
fn lcg(s: &mut u32) -> u16 {
    *s = s.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    ((*s >> 20) & 0xFFF) as u16
}

/// Bench-less development path: fabricate plausible mV/mA readings instead
/// of talking to the INA229. `cargo build --features sim-adc`.
#[cfg(feature = "sim-adc")]
#[embassy_executor::task]
async fn adc_task() {
    let mut rng: u32 = 0xDEAD_BEEF;
    loop {
        MEAS_V_MV.store(2000 + (lcg(&mut rng) & 0xFF), Ordering::Relaxed);
        MEAS_I_MA.store(500 + (lcg(&mut rng) & 0x7F), Ordering::Relaxed);
        Timer::after_millis(10).await;
    }
}

/// Real sensing path: poll the INA229 over SPI0 at the SDK's control period
/// (`CONTROL_PERIOD_MS = 1.0`) and publish `(V, I)` for the SPI-slave link.
#[cfg(not(feature = "sim-adc"))]
#[embassy_executor::task]
async fn ina_task(
    mut spi: Spi<'static, embassy_rp::peripherals::SPI0, embassy_rp::spi::Blocking>,
    mut cs_ina: Output<'static>,
) {
    let mut ina = Ina229::new();

    // Retry with backoff instead of panicking: a wiring/power fault on the
    // sensing board must not take down the Pi SPI link, which should keep
    // running and report zeros until the sensor comes up.
    let mut backoff_ms = 100u64;
    loop {
        match ina.init(&mut spi, &mut cs_ina) {
            Ok(()) => break,
            Err(e) => {
                defmt::error!("INA229 init failed: {}, retrying in {} ms", e, backoff_ms);
                Timer::after_millis(backoff_ms).await;
                backoff_ms = (backoff_ms * 2).min(2000);
            }
        }
    }
    defmt::info!("INA229 ready");

    let mut log_tick: u32 = 0;
    loop {
        match (
            ina.read_vbus_mv(&mut spi, &mut cs_ina),
            ina.read_current_ma(&mut spi, &mut cs_ina),
        ) {
            (Ok(v), Ok(i)) => {
                MEAS_V_MV.store(v, Ordering::Relaxed);
                MEAS_I_MA.store(i, Ordering::Relaxed);
                log_tick += 1;
                if log_tick >= 1000 {
                    // ~1 Hz at the 1 ms poll period - RTT flooding at 1 kHz
                    // stalls the target.
                    log_tick = 0;
                    defmt::info!("V={} mV I={} mA", v, i);
                }
            }
            _ => defmt::error!("INA229 read failed"),
        }
        Timer::after_millis(1).await;
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

    #[cfg(feature = "sim-adc")]
    spawner.spawn(adc_task().unwrap());

    // SPI0 bus: SCK GPIO18, MOSI GPIO19, MISO GPIO16 (firmware/README.md GPIO
    // table). Chip selects are manual GPIO outputs, not the SPI peripheral's
    // hardware CS - the bus is shared with the MAX31865 (future work), so
    // each device's CS is driven independently. Declared at `main`'s top
    // level (not inside a sub-block) so they are never dropped: `Output`
    // resets the pin's funcsel on drop, which would let the MAX31865 CS
    // float onto the shared bus.
    #[cfg(not(feature = "sim-adc"))]
    let mut spi_cfg = SpiConfig::default();
    #[cfg(not(feature = "sim-adc"))]
    {
        spi_cfg.frequency = 1_000_000;
        // INA229 samples MOSI on SCLK falling edge, shifts MISO out on the
        // rising edge (datasheet Section 7.5.1): CPOL = 0, CPHA = 1 - SPI
        // mode 1, not the more commonly assumed mode 0.
        spi_cfg.polarity = Polarity::IdleLow;
        spi_cfg.phase = Phase::CaptureOnSecondTransition;
    }
    #[cfg(not(feature = "sim-adc"))]
    let spi = Spi::new_blocking(p.SPI0, p.PIN_18, p.PIN_19, p.PIN_16, spi_cfg);
    #[cfg(not(feature = "sim-adc"))]
    let cs_ina = Output::new(p.PIN_17, Level::High);
    // MAX31865 chip select: kept idle HIGH so it never floats onto the
    // shared SPI0 bus. Not driven low anywhere - that sensor is future work
    // (see firmware/README.md maintenance notes).
    #[cfg(not(feature = "sim-adc"))]
    let _cs_tp100 = Output::new(p.PIN_20, Level::High);
    #[cfg(not(feature = "sim-adc"))]
    spawner.spawn(ina_task(spi, cs_ina).unwrap());

    spawner.spawn(spi_slave_pio::spi_pio_task(sm, dma_ch).unwrap());

    loop {
        let duty = DUTY.load(Ordering::Relaxed);
        pwm_cfg.compare_b = duty;
        pwm.set_config(&pwm_cfg);
        Timer::after_millis(100).await;
    }
}
