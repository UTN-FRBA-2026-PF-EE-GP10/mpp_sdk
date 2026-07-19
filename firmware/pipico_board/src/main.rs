#![no_std]
#![no_main]

mod ina229;
// MAX31865 disabled - no compatible probe to test with right now (see PR body).
// mod max31865;
mod spi_slave_pio;

use embassy_executor::Spawner;
use embassy_rp::bind_interrupts;
use embassy_rp::dma;
use embassy_rp::gpio::{Input, Level, Output, Pull};
use embassy_rp::peripherals::DMA_CH0;
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_rp::spi::{Config as SpiConfig, Phase, Polarity, Spi};
use embassy_time::Timer;
use ina229::Ina229;
// use max31865::Max31865;
// use portable_atomic::AtomicI16;
use portable_atomic::{AtomicU16, Ordering};
use {defmt_rtt as _, panic_probe as _};

bind_interrupts!(struct DmaIrqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>;
});

// Shared state (written by SPI/ADC tasks, read by main).
pub static DUTY: AtomicU16 = AtomicU16::new(0x8000); // 50 % initial
pub static MEAS_V_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_I_MA: AtomicU16 = AtomicU16::new(0);
// MAX31865 disabled - no compatible probe to test with right now (see PR body).
// pub static MEAS_T_CC: AtomicI16 = AtomicI16::new(0);

/// Polls the INA229 over SPI0 at the SDK's control period
/// (`CONTROL_PERIOD_MS = 1.0`) and publishes `(V, I)` for the SPI-slave link.
#[embassy_executor::task]
async fn sensors_task(
    mut spi: Spi<'static, embassy_rp::peripherals::SPI0, embassy_rp::spi::Blocking>,
    mut cs_ina: Output<'static>,
    // Held high, untouched: MAX31865 disabled right now (see PR body).
    _cs_tp100: Output<'static>,
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

    // MAX31865 disabled - no compatible probe to test with right now (see PR body).
    // let mut max = Max31865::new();
    // let mut max_ok = match max.init(&mut spi, &mut cs_tp100) {
    //     Ok(()) => {
    //         defmt::info!("MAX31865 ready");
    //         true
    //     }
    //     Err(e) => {
    //         defmt::error!("MAX31865 init failed: {}, will retry in background", e);
    //         false
    //     }
    // };

    let mut tick: u32 = 0;
    loop {
        match (
            ina.read_vbus_mv(&mut spi, &mut cs_ina),
            ina.read_current_ma(&mut spi, &mut cs_ina),
        ) {
            (Ok(v), Ok(i)) => {
                MEAS_V_MV.store(v, Ordering::Relaxed);
                MEAS_I_MA.store(i, Ordering::Relaxed);
            }
            _ => defmt::error!("INA229 read failed"),
        }

        tick = tick.wrapping_add(1);

        // MAX31865 disabled - no compatible probe to test with right now (see PR body).
        // if tick % 100 == 0 {
        //     if max_ok {
        //         match max.read_temp_centi_c(&mut spi, &mut cs_tp100) {
        //             Ok(t) => MEAS_T_CC.store(t, Ordering::Relaxed),
        //             Err(e) => {
        //                 if tick % 1000 == 0 {
        //                     defmt::error!("MAX31865 read failed: {}", e);
        //                 }
        //             }
        //         }
        //     } else if tick % 5000 == 0 {
        //         max_ok = max.init(&mut spi, &mut cs_tp100).is_ok();
        //         if max_ok {
        //             defmt::info!("MAX31865 ready");
        //         }
        //     }
        // }

        if tick % 1000 == 0 {
            // ~1 Hz at the 1 ms poll period - RTT flooding at 1 kHz stalls
            // the target.
            defmt::info!(
                "V={} mV I={} mA",
                MEAS_V_MV.load(Ordering::Relaxed),
                MEAS_I_MA.load(Ordering::Relaxed)
            );
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

    // Curve-tracer relay + bleed PWM: idle low is both the safe default
    // and normal MPPT operation (low releases the relay, SEPIC path active).
    let mut tracer_en = Output::new(p.PIN_2, Level::Low);
    let _tracer_pwm = Output::new(p.PIN_3, Level::Low);
    // Bring-up aid: hold But1 (active-low, switch to GND) to energize the
    // relay and hear it click. Remove once the curve tracer has real logic.
    let but1 = Input::new(p.PIN_0, Pull::Up);

    let (sm, sm_origin) = spi_slave_pio::init(p.PIO0, p.PIN_10, p.PIN_11, p.PIN_12, p.PIN_13);
    let dma_ch = dma::Channel::new(p.DMA_CH0, DmaIrqs);

    // SPI0 bus: SCK GPIO18, MOSI GPIO19, MISO GPIO16. Chip selects are
    // manual GPIO outputs (not the peripheral's hardware CS) so the bus
    // can be shared with the MAX31865 later; declared here at `main`'s top
    // level so they're never dropped (drop would float the pin).
    let mut spi_cfg = SpiConfig::default();
    spi_cfg.frequency = 1_000_000;
    // INA229 samples MOSI on SCLK falling edge, shifts MISO out on the
    // rising edge (datasheet Section 7.5.1): SPI mode 1, not mode 0.
    spi_cfg.polarity = Polarity::IdleLow;
    spi_cfg.phase = Phase::CaptureOnSecondTransition;
    let spi = Spi::new_blocking(p.SPI0, p.PIN_18, p.PIN_19, p.PIN_16, spi_cfg);
    let cs_ina = Output::new(p.PIN_17, Level::High);
    let cs_tp100 = Output::new(p.PIN_20, Level::High);
    spawner.spawn(sensors_task(spi, cs_ina, cs_tp100).unwrap());

    spawner.spawn(spi_slave_pio::spi_pio_task(sm, sm_origin, dma_ch).unwrap());

    loop {
        let duty = DUTY.load(Ordering::Relaxed);
        pwm_cfg.compare_b = duty;
        pwm.set_config(&pwm_cfg);

        tracer_en.set_level(if but1.is_low() {
            Level::High
        } else {
            Level::Low
        });

        Timer::after_millis(100).await;
    }
}
