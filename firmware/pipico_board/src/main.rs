#![no_std]
#![no_main]

mod ina229;
// MAX31865 disabled - no compatible probe to test with right now (see PR body).
// mod max31865;
mod spi_slave_pio;

use embassy_executor::Spawner;
use embassy_rp::adc::{Adc, Channel as AdcChannel, Config as AdcConfig};
use embassy_rp::bind_interrupts;
use embassy_rp::dma;
use embassy_rp::gpio::{Input, Level, Output, Pull};
use embassy_rp::peripherals::{DMA_CH0, DMA_CH1, PIO1};
use embassy_rp::pio::{InterruptHandler as PioInterruptHandler, Pio};
use embassy_rp::pio_programs::ws2812::{Grb, PioWs2812, PioWs2812Program};
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_rp::spi::{Config as SpiConfig, Phase, Polarity, Spi};
use embassy_time::Timer;
use ina229::Ina229;
// use max31865::Max31865;
// use portable_atomic::AtomicI16;
use portable_atomic::{AtomicU16, AtomicU32, Ordering};
use smart_leds::RGB8;
use {defmt_rtt as _, panic_probe as _};

bind_interrupts!(struct DmaIrqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>, dma::InterruptHandler<DMA_CH1>;
});

bind_interrupts!(struct Pio1Irqs {
    PIO1_IRQ_0 => PioInterruptHandler<PIO1>;
});

// Shared state (written by SPI/ADC tasks, read by main).
pub static DUTY: AtomicU16 = AtomicU16::new(0); // 0 % initial - safe boot state

// 0.95 * 65535, mirrors the SDK's max_duty. Defense-in-depth: the raw SPI
// DUTY word is applied unvalidated by the master, and on a SEPIC an
// unclamped 100 % duty ramps the inductor current unbounded. Frame-integrity
// hardening is spi_slave_pio.rs's job; this is the guard behind it.
const DUTY_MAX: u16 = 62258;
pub static MEAS_V_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_I_MA: AtomicU16 = AtomicU16::new(0);
// MAX31865 disabled - no compatible probe to test with right now (see PR body).
// pub static MEAS_T_CC: AtomicI16 = AtomicI16::new(0);
// On-chip ADC readings, in millivolts. PWR/VOUT are calibrated (divider
// scaling applied); Input_Curr (the INA281 cross-check for MEAS_I_MA) is
// still raw pin mV - its gain/shunt aren't resolved yet.
pub static MEAS_ADC_PWR_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_ADC_VOUT_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_ADC_IIN_MV: AtomicU16 = AtomicU16::new(0);
// Bumped once per successfully-received SPI frame (spi_slave_pio.rs) -
// read-only elsewhere, drives the NeoPixel packet heartbeat.
pub static PACKET_COUNT: AtomicU32 = AtomicU32::new(0);

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

/// Jumper state of the ADC_PWR/ADC_VOUT divider network (see README for
/// the range table and why it matters). Must match the physical board -
/// not auto-sensed, logged once at boot.
#[allow(dead_code)] // Mid/Low selected by editing ADC_DIVIDER_RANGE, not constructed elsewhere.
#[derive(Clone, Copy, defmt::Format)]
enum AdcDividerRange {
    /// 3x 75k in series (235k/10k divider). As-built default.
    Full,
    /// 2x 75k in series (160k/10k divider).
    Mid,
    /// 1x 75k (85k/10k divider) - most resolution at low bench voltages.
    Low,
}

/// Set this to match the jumpers actually shorted on the board.
const ADC_DIVIDER_RANGE: AdcDividerRange = AdcDividerRange::Low;

/// Polls the RP2040's on-chip ADC and logs it next to MEAS_I_MA so
/// ADC_Input_Curr can be eyeballed against the INA229.
#[embassy_executor::task]
async fn onchip_adc_task(
    mut adc: Adc<'static, embassy_rp::adc::Blocking>,
    mut ch_pwr: AdcChannel<'static>,
    mut ch_vout: AdcChannel<'static>,
    mut ch_iin: AdcChannel<'static>,
) {
    // Measured at the Pico's ADC_VREF pin (pin 35), not the nominal 3.3 V.
    // See README for the ADC accuracy notes.
    const ADC_VREF_MV: u32 = 3218;

    fn raw_to_mv(raw: u16) -> u16 {
        (raw as u32 * ADC_VREF_MV / 4095) as u16
    }

    // Scales by the divider's total-to-bottom-leg (10k) resistance ratio,
    // matching the currently-shorted jumper state. Saturates instead of
    // wrapping: on `Full`, inputs above ~65.5 V (still within that range's
    // ~75.6 V full scale) would otherwise overflow u16 silently.
    fn divider_to_actual_mv(adc_mv: u16) -> u16 {
        let mv = match ADC_DIVIDER_RANGE {
            AdcDividerRange::Full => adc_mv as u32 * 235 / 10, // 3x 75k + 10k
            AdcDividerRange::Mid => adc_mv as u32 * 160 / 10,  // 2x 75k + 10k
            AdcDividerRange::Low => adc_mv as u32 * 85 / 10,   // 1x 75k + 10k
        };
        mv.min(u16::MAX as u32) as u16
    }

    defmt::info!(
        "ADC divider range: {} (must match the physical jumpers)",
        ADC_DIVIDER_RANGE
    );

    let mut tick: u32 = 0;
    loop {
        if let Ok(raw) = adc.blocking_read(&mut ch_pwr) {
            MEAS_ADC_PWR_MV.store(divider_to_actual_mv(raw_to_mv(raw)), Ordering::Relaxed);
        }
        if let Ok(raw) = adc.blocking_read(&mut ch_vout) {
            MEAS_ADC_VOUT_MV.store(divider_to_actual_mv(raw_to_mv(raw)), Ordering::Relaxed);
        }
        // ADC_Input_Curr (INA281 cross-check) stays raw pin mV - gain and
        // shunt not resolved yet.
        if let Ok(raw) = adc.blocking_read(&mut ch_iin) {
            MEAS_ADC_IIN_MV.store(raw_to_mv(raw), Ordering::Relaxed);
        }

        tick = tick.wrapping_add(1);
        if tick % 10 == 0 {
            // ~1 Hz at the 100 ms poll period.
            defmt::info!(
                "ADC_PWR={} mV ADC_VOUT={} mV ADC_Input_Curr={} mV (INA229 I={} mA)",
                MEAS_ADC_PWR_MV.load(Ordering::Relaxed),
                MEAS_ADC_VOUT_MV.load(Ordering::Relaxed),
                MEAS_ADC_IIN_MV.load(Ordering::Relaxed),
                MEAS_I_MA.load(Ordering::Relaxed)
            );
        }
        Timer::after_millis(100).await;
    }
}

const NEOPIXEL_COUNT: usize = 4;

/// Flashes the GPIO4 NeoPixel strip briefly on every SPI frame the Pi
/// successfully sends, dark otherwise - a packet-received heartbeat,
/// separate from GPIO14's firmware-alive one. Runs on PIO1 (PIO0 is
/// owned by the SPI slave) with its own DMA channel, decoupled from
/// `spi_pio_task` via `PACKET_COUNT` so it can never affect that task's
/// timing budget.
#[embassy_executor::task]
async fn neopixel_task(mut ws2812: PioWs2812<'static, PIO1, 0, NEOPIXEL_COUNT, Grb>) {
    const OFF: [RGB8; NEOPIXEL_COUNT] = [RGB8 { r: 0, g: 0, b: 0 }; NEOPIXEL_COUNT];
    const FLASH: [RGB8; NEOPIXEL_COUNT] = [RGB8 { r: 0, g: 32, b: 0 }; NEOPIXEL_COUNT];

    let mut last_seen: u32 = 0;
    ws2812.write(&OFF).await;
    loop {
        let current = PACKET_COUNT.load(Ordering::Relaxed);
        if current != last_seen {
            last_seen = current;
            ws2812.write(&FLASH).await;
            Timer::after_millis(20).await;
            ws2812.write(&OFF).await;
        }
        Timer::after_millis(10).await;
    }
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    defmt::info!("mpp-firmware booted (PIO SPI slave)");

    // SEPIC gate PWM on GPIO15 (PWM_Gate net, through a 10R + 3.3nF network
    // into the driver stage): 100 kHz at the default 125 MHz sysclk with
    // divider 1, top = 1249. Duty is commanded via `DUTY` (u16, 0 = 0 %,
    // 65535 = 100 %) over the Pi SPI link.
    let mut pwm_cfg = PwmConfig::default();
    pwm_cfg.top = 1249;
    pwm_cfg.compare_b = 0;
    let mut pwm = Pwm::new_output_b(p.PWM_SLICE7, p.PIN_15, pwm_cfg.clone());

    // Curve-tracer relay + bleed PWM: idle low is both the safe default
    // and normal MPPT operation (low releases the relay, SEPIC path active).
    let mut tracer_en = Output::new(p.PIN_2, Level::Low);
    let _tracer_pwm = Output::new(p.PIN_3, Level::Low);
    // Bring-up aid: hold But1 (active-low, switch to GND) to energize the
    // relay and hear it click. Remove once the curve tracer has real logic.
    let but1 = Input::new(p.PIN_0, Pull::Up);

    // Heartbeat LED (GPIO14, "Blinky" net): toggles in the main loop so a
    // stuck/hung firmware shows as a frozen LED, not just an always-on one.
    let mut heartbeat = Output::new(p.PIN_14, Level::Low);

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

    let adc = Adc::new_blocking(p.ADC, AdcConfig::default());
    let ch_pwr = AdcChannel::new_pin(p.PIN_26, Pull::None);
    let ch_vout = AdcChannel::new_pin(p.PIN_27, Pull::None);
    let ch_iin = AdcChannel::new_pin(p.PIN_28, Pull::None);
    spawner.spawn(onchip_adc_task(adc, ch_pwr, ch_vout, ch_iin).unwrap());

    spawner.spawn(spi_slave_pio::spi_pio_task(sm, sm_origin, dma_ch).unwrap());

    // GPIO4 NeoPixel packet heartbeat: separate PIO block/DMA channel from
    // the SPI slave above, see neopixel_task's doc comment for why.
    let Pio {
        common: mut pio1_common,
        sm0: pio1_sm0,
        ..
    } = Pio::new(p.PIO1, Pio1Irqs);
    let ws2812_program = PioWs2812Program::new(&mut pio1_common);
    let ws2812 = PioWs2812::new(
        &mut pio1_common,
        pio1_sm0,
        p.DMA_CH1,
        DmaIrqs,
        p.PIN_4,
        &ws2812_program,
    );
    spawner.spawn(neopixel_task(ws2812).unwrap());

    let mut tick: u32 = 0;
    loop {
        let duty = DUTY.load(Ordering::Relaxed).min(DUTY_MAX);
        pwm_cfg.compare_b = (duty as u32 * 1250 / 65536) as u16;
        pwm.set_config(&pwm_cfg);

        tracer_en.set_level(if but1.is_low() {
            Level::High
        } else {
            Level::Low
        });

        tick = tick.wrapping_add(1);
        if tick % 500 == 0 {
            // 500 ms per half-period at the 1 ms loop cadence -> ~1 Hz blink.
            heartbeat.toggle();
        }

        Timer::after_millis(1).await;
    }
}
