#![no_std]
#![no_main]

mod adc_cal;
mod ina229;
mod max31865;
mod mode_curve_tracer;
mod mode_power_supply;
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
use max31865::Max31865;
use portable_atomic::{AtomicBool, AtomicI16, AtomicU16, AtomicU32, AtomicU8, Ordering};
use smart_leds::RGB8;
use {defmt_rtt as _, panic_probe as _};

bind_interrupts!(struct DmaIrqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>, dma::InterruptHandler<DMA_CH1>;
});

bind_interrupts!(struct Pio1Irqs {
    PIO1_IRQ_0 => PioInterruptHandler<PIO1>;
});

/// Jumper state of the ADC_PWR/ADC_VOUT divider network.
/// Configurable dynamically via SPI. Default: Low.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum AdcDividerRange {
    /// 3x 75k in series (235k/10k divider). Full scale ~75.6 V.
    Full = 0,
    /// 2x 75k in series (160k/10k divider). Full scale ~51.5 V.
    Mid = 1,
    /// 1x 75k (85k/10k divider). Full scale ~27.3 V.
    Low = 2,
}

impl AdcDividerRange {
    pub fn from_u8(val: u8) -> Self {
        match val {
            0 => AdcDividerRange::Full,
            1 => AdcDividerRange::Mid,
            _ => AdcDividerRange::Low,
        }
    }
}

/// Host-driven MPPT vs local bench supply.
/// Configurable dynamically via SPI. Default: MppTracker.
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum FirmwareMode {
    MppTracker = 0,
    PowerSupply = 1,
}

impl FirmwareMode {
    pub fn from_u8(val: u8) -> Self {
        match val {
            1 => FirmwareMode::PowerSupply,
            _ => FirmwareMode::MppTracker,
        }
    }
}

// Shared state (written by SPI/ADC tasks, read by main).
pub static DUTY: AtomicU16 = AtomicU16::new(0); // 0 % initial - safe boot state

// Dynamic configuration atomics (configurable on the fly via SPI with default values)
pub static ADC_VIN_DIVIDER_RANGE: AtomicU8 = AtomicU8::new(AdcDividerRange::Low as u8);
pub static ADC_VOUT_DIVIDER_RANGE: AtomicU8 = AtomicU8::new(AdcDividerRange::Low as u8);
pub static MAX31865_ENABLED: AtomicBool = AtomicBool::new(false);
pub static FIRMWARE_MODE: AtomicU8 = AtomicU8::new(FirmwareMode::MppTracker as u8);
pub static RON_MOHM: AtomicU16 = AtomicU16::new(6); // Default 6 mOhm (Infineon IPP060N06N)
pub static CUTOFF_IMAX_MA: AtomicU16 = AtomicU16::new(1000); // Default 1000 mA (1.0 A)
pub static CUTOFF_VMAX_MV: AtomicU16 = AtomicU16::new(40000); // Default 40000 mV (40 V)
pub static CUTOFF_TRIPPED: AtomicBool = AtomicBool::new(false);

// 0.95 * 65535, mirrors the SDK's max_duty. The Pi sends the raw SPI DUTY
// word unvalidated, and an unclamped 100 % duty ramps a SEPIC's inductor
// current unbounded. spi_slave_pio.rs guards frame integrity; this guards
// the value it carries.
const DUTY_MAX: u16 = 62258;
pub static MEAS_V_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_I_MA: AtomicU16 = AtomicU16::new(0);
pub static MEAS_T_CC: AtomicI16 = AtomicI16::new(spi_slave_pio::TEMP_NOT_AVAILABLE_CC);
// On-chip ADC, in millivolts, through the bench calibration in adc_cal.rs.
// PWR/VOUT are the terminal voltages (divider applied). Input_Curr (the
// INA281 cross-check for MEAS_I_MA) is still pin mV - its gain/shunt are
// not resolved yet.
pub static MEAS_ADC_PWR_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_ADC_VOUT_MV: AtomicU16 = AtomicU16::new(0);
pub static MEAS_ADC_IIN_MV: AtomicU16 = AtomicU16::new(0);
// Raw on-chip ADC codes (0..=4095) for the NeoPixel status LEDs.
pub static ADC_RAW_PWR: AtomicU16 = AtomicU16::new(0);
pub static ADC_RAW_VOUT: AtomicU16 = AtomicU16::new(0);
pub static ADC_RAW_IIN: AtomicU16 = AtomicU16::new(0);
// Bumped once per SPI frame received (spi_slave_pio.rs). Drives the
// NeoPixel packet heartbeat.
pub static PACKET_COUNT: AtomicU32 = AtomicU32::new(0);
pub static DUTY_SETTLED: AtomicBool = AtomicBool::new(false);
pub static MEAS_TRIGGER_COUNT: AtomicU32 = AtomicU32::new(0);
pub static SETTLED_TRIGGER: AtomicU32 = AtomicU32::new(0);
// Bumped once per onchip_adc_task poll (~100 ms). mode_power_supply's
// ClosedLoop gates its control step on this, not on MEAS_ADC_VOUT_MV's
// value: a reading can repeat across samples (e.g. Vout not moving yet at
// boot), and gating on value-equality instead of sample-freshness would
// stall the controller the first time that happens.
pub static ADC_SAMPLE_COUNT: AtomicU32 = AtomicU32::new(0);
// True for the duration of a curve-tracer sweep (mode_curve_tracer.rs).
// Neither FirmwareMode may drive the gate while a sweep is stepping the
// bleed PWM - see the override in main()'s loop below. This does not by
// itself mean the panel is back on the SEPIC path once it clears - see
// RELAY_ENGAGED for that.
pub static TRACER_ACTIVE: AtomicBool = AtomicBool::new(false);
// True whenever the curve-tracer relay has routed the panel onto the
// bleed path (mode_curve_tracer.rs) - the whole window from "relay
// energized" to "relay explicitly released", which can span multiple
// sweeps, wider than TRACER_ACTIVE's "a sweep is running right now". The
// gate must not be driven while this is true either, or the SEPIC would
// switch with its input disconnected.
pub static RELAY_ENGAGED: AtomicBool = AtomicBool::new(false);

/// Polls the INA229 over SPI0 at the SDK's control period
/// (`CONTROL_PERIOD_MS = 1.0`) and publishes `(V, I)` for the SPI-slave link.
#[embassy_executor::task]
async fn sensors_task(
    mut spi: Spi<'static, embassy_rp::peripherals::SPI0, embassy_rp::spi::Blocking>,
    mut cs_ina: Output<'static>,
    mut cs_tp100: Output<'static>,
) {
    let mut ina = Ina229::new();

    // Retry with backoff instead of panicking: a wiring/power fault on the
    // sensing board must not take down the Pi SPI link. It should keep
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

    let mut max = Max31865::new();
    let mut max_ok = false;
    let mut was_max_enabled = false;

    let mut tick: u32 = 0;
    let mut last_trigger: u32 = 0;
    loop {
        let trigger = MEAS_TRIGGER_COUNT.load(Ordering::Relaxed);
        if trigger != 0 && trigger != last_trigger {
            if SETTLED_TRIGGER.load(Ordering::Relaxed) != trigger {
                Timer::after_millis(1).await;
                continue;
            }
            last_trigger = trigger;
            
            let mut v_samples = [0u16; 25];
            let mut i_samples = [0u16; 25];
            
            for i in 0..25 {
                if let (Ok(v), Ok(c)) = (
                    ina.read_vbus_mv(&mut spi, &mut cs_ina),
                    ina.read_current_ma(&mut spi, &mut cs_ina),
                ) {
                    v_samples[i] = v;
                    i_samples[i] = c;
                } else {
                    v_samples[i] = if i > 0 { v_samples[i-1] } else { 0 };
                    i_samples[i] = if i > 0 { i_samples[i-1] } else { 0 };
                }
                Timer::after_micros(800).await;
            }
            
            v_samples.sort_unstable();
            i_samples.sort_unstable();
            
            // 25 samples: drop 4 lowest (0..4) and 4 highest (21..25), average remaining 17 (4..21)
            let v_mean = (v_samples[4..21].iter().map(|&x| x as u32).sum::<u32>() / 17) as u16;
            let i_mean = (i_samples[4..21].iter().map(|&x| x as u32).sum::<u32>() / 17) as u16;
            
            MEAS_V_MV.store(v_mean, Ordering::Relaxed);
            MEAS_I_MA.store(i_mean, Ordering::Relaxed);
            DUTY_SETTLED.store(true, Ordering::Relaxed);
            mode_curve_tracer::INA_SAMPLE_COUNT.fetch_add(1, Ordering::Relaxed);
            defmt::info!("settled INA: V={} mV I={} mA", v_mean, i_mean);
            continue;
        }

        // Only stream continuous reads if curve tracer sweep is running
        if TRACER_ACTIVE.load(Ordering::Relaxed) {
            match (
                ina.read_vbus_mv(&mut spi, &mut cs_ina),
                ina.read_current_ma(&mut spi, &mut cs_ina),
            ) {
                (Ok(v), Ok(i)) => {
                    MEAS_V_MV.store(v, Ordering::Relaxed);
                    MEAS_I_MA.store(i, Ordering::Relaxed);
                    mode_curve_tracer::INA_SAMPLE_COUNT.fetch_add(1, Ordering::Relaxed);
                }
                _ => defmt::error!("INA229 read failed"),
            }
        }

        tick = tick.wrapping_add(1);

        let max_enabled = MAX31865_ENABLED.load(Ordering::Relaxed);
        if max_enabled {
            if !was_max_enabled {
                max_ok = max.init(&mut spi, &mut cs_tp100).is_ok();
                if max_ok {
                    defmt::info!("MAX31865 ready (enabled on the fly)");
                } else {
                    defmt::error!("MAX31865 init failed, will retry in background");
                }
                was_max_enabled = true;
            }

            if tick.is_multiple_of(100) {
                if max_ok {
                    match max.read_temp_centi_c(&mut spi, &mut cs_tp100) {
                        Ok(t) => MEAS_T_CC.store(t, Ordering::Relaxed),
                        Err(e) => {
                            if tick.is_multiple_of(1000) {
                                defmt::error!("MAX31865 read failed: {}", e);
                            }
                        }
                    }
                } else if tick.is_multiple_of(5000) {
                    max_ok = max.init(&mut spi, &mut cs_tp100).is_ok();
                    if max_ok {
                        defmt::info!("MAX31865 ready");
                    }
                }
            }
        } else if was_max_enabled {
            defmt::info!("MAX31865 disabled on the fly");
            was_max_enabled = false;
            max_ok = false;
            MEAS_T_CC.store(spi_slave_pio::TEMP_NOT_AVAILABLE_CC, Ordering::Relaxed);
        }

        if tick.is_multiple_of(1000) {
            // ~1 Hz at the 1 ms poll period - RTT flooding at 1 kHz stalls
            // the target.
            let v = MEAS_V_MV.load(Ordering::Relaxed);
            let i = MEAS_I_MA.load(Ordering::Relaxed);
            let t = MEAS_T_CC.load(Ordering::Relaxed);
            if t == spi_slave_pio::TEMP_NOT_AVAILABLE_CC {
                defmt::info!("V={} mV I={} mA T=n/a", v, i);
            } else {
                defmt::info!(
                    "V={} mV I={} mA T={}.{:02} C",
                    v,
                    i,
                    t / 100,
                    (t % 100).abs()
                );
            }
        }
        Timer::after_millis(1).await;
    }
}

// Polls the RP2040's on-chip ADC and logs it next to MEAS_I_MA so
/// ADC_Input_Curr can be eyeballed against the INA229.
#[embassy_executor::task]
async fn onchip_adc_task(
    mut adc: Adc<'static, embassy_rp::adc::Blocking>,
    mut ch_pwr: AdcChannel<'static>,
    mut ch_vout: AdcChannel<'static>,
    mut ch_iin: AdcChannel<'static>,
) {
    use adc_cal::raw_to_pin_mv as raw_to_mv;

    // Matches the currently-shorted jumper state. The ratio numbers and the
    // saturating conversion live in adc_cal.rs, next to the rest of the ADC
    // calibration.
    fn pwr_divider_to_actual_mv(adc_mv: u16) -> u16 {
        let range = AdcDividerRange::from_u8(ADC_VIN_DIVIDER_RANGE.load(Ordering::Relaxed));
        adc_cal::divider_to_actual_mv(range, adc_mv)
    }

    fn vout_divider_to_actual_mv(adc_mv: u16) -> u16 {
        let range = AdcDividerRange::from_u8(ADC_VOUT_DIVIDER_RANGE.load(Ordering::Relaxed));
        adc_cal::divider_to_actual_mv(range, adc_mv)
    }

    defmt::info!(
        "ADC divider ranges: Vin={} Vout={} (dynamically configurable)",
        AdcDividerRange::from_u8(ADC_VIN_DIVIDER_RANGE.load(Ordering::Relaxed)),
        AdcDividerRange::from_u8(ADC_VOUT_DIVIDER_RANGE.load(Ordering::Relaxed))
    );

    let mut last_trigger: u32 = 0;
    let mut idle_tick: u32 = 0;
    loop {
        let trigger = MEAS_TRIGGER_COUNT.load(Ordering::Relaxed);
        if trigger != 0 && trigger != last_trigger {
            last_trigger = trigger;
            
            Timer::after_millis(2).await;
            
            let mut settle_buf = [0i32; 8];
            let mut settle_idx = 0;
            let start_t = embassy_time::Instant::now();
            let max_wait = embassy_time::Duration::from_millis(20);
            
            loop {
                let raw = adc.blocking_read(&mut ch_pwr).unwrap_or(0);
                let mv = pwr_divider_to_actual_mv(raw_to_mv(raw)) as i32;
                
                if settle_idx < 8 {
                    settle_buf[settle_idx] = mv;
                    settle_idx += 1;
                } else {
                    for i in 0..7 { settle_buf[i] = settle_buf[i+1]; }
                    settle_buf[7] = mv;
                    
                    let v_prev = (settle_buf[0] + settle_buf[1] + settle_buf[2] + settle_buf[3]) / 4;
                    let v_curr = (settle_buf[4] + settle_buf[5] + settle_buf[6] + settle_buf[7]) / 4;
                    
                    if (v_curr - v_prev).abs() < 50 {
                        break;
                    }
                }
                
                if start_t.elapsed() >= max_wait {
                    break;
                }
                Timer::after_millis(1).await;
            }
            
            SETTLED_TRIGGER.store(trigger, Ordering::Relaxed);
            
            let mut pwr_samples = [0u16; 25];
            let mut vout_samples = [0u16; 25];
            let mut iin_samples = [0u16; 25];
            
            for i in 0..25 {
                pwr_samples[i] = adc.blocking_read(&mut ch_pwr).unwrap_or(0);
                vout_samples[i] = adc.blocking_read(&mut ch_vout).unwrap_or(0);
                iin_samples[i] = adc.blocking_read(&mut ch_iin).unwrap_or(0);
                Timer::after_micros(800).await;
            }
            
            pwr_samples.sort_unstable();
            vout_samples.sort_unstable();
            iin_samples.sort_unstable();
            
            // 25 samples: drop 4 lowest (0..4) and 4 highest (21..25), average remaining 17 (4..21)
            let pwr_mean = (pwr_samples[4..21].iter().map(|&x| x as u32).sum::<u32>() / 17) as u16;
            let vout_mean = (vout_samples[4..21].iter().map(|&x| x as u32).sum::<u32>() / 17) as u16;
            let iin_mean = (iin_samples[4..21].iter().map(|&x| x as u32).sum::<u32>() / 17) as u16;
            
            ADC_RAW_PWR.store(pwr_mean, Ordering::Relaxed);
            ADC_RAW_VOUT.store(vout_mean, Ordering::Relaxed);
            ADC_RAW_IIN.store(iin_mean, Ordering::Relaxed);

            MEAS_ADC_PWR_MV.store(pwr_divider_to_actual_mv(raw_to_mv(pwr_mean)), Ordering::Relaxed);
            MEAS_ADC_VOUT_MV.store(vout_divider_to_actual_mv(raw_to_mv(vout_mean)), Ordering::Relaxed);
            MEAS_ADC_IIN_MV.store(raw_to_mv(iin_mean), Ordering::Relaxed);
            
            ADC_SAMPLE_COUNT.fetch_add(1, Ordering::Relaxed);
            defmt::info!("settled ADC: PWR={} mV VOUT={} mV", pwr_divider_to_actual_mv(raw_to_mv(pwr_mean)), vout_divider_to_actual_mv(raw_to_mv(vout_mean)));
            continue;
        }

        // Only stream continuous reads if in PowerSupply mode
        let current_fw_mode = FirmwareMode::from_u8(FIRMWARE_MODE.load(Ordering::Relaxed));
        if current_fw_mode == FirmwareMode::PowerSupply {
            let pwr_raw = adc.blocking_read(&mut ch_pwr).ok();
            if let Some(raw) = pwr_raw {
                ADC_RAW_PWR.store(raw, Ordering::Relaxed);
                MEAS_ADC_PWR_MV.store(pwr_divider_to_actual_mv(raw_to_mv(raw)), Ordering::Relaxed);
            }
            let vout_raw = adc.blocking_read(&mut ch_vout).ok();
            if let Some(raw) = vout_raw {
                ADC_RAW_VOUT.store(raw, Ordering::Relaxed);
                MEAS_ADC_VOUT_MV.store(vout_divider_to_actual_mv(raw_to_mv(raw)), Ordering::Relaxed);
            }
            if let Ok(raw) = adc.blocking_read(&mut ch_iin) {
                ADC_RAW_IIN.store(raw, Ordering::Relaxed);
                MEAS_ADC_IIN_MV.store(raw_to_mv(raw), Ordering::Relaxed);
            }
            ADC_SAMPLE_COUNT.fetch_add(1, Ordering::Relaxed);
        } else {
            // In MppTracker mode, when idle (between settling triggers or before first trigger),
            // update raw ADC readings for the NeoPixel status LEDs without overwriting
            // the settled telemetry registers (MEAS_*).
            idle_tick = idle_tick.wrapping_add(1);
            if idle_tick.is_multiple_of(50) {
                if let Ok(raw) = adc.blocking_read(&mut ch_pwr) {
                    ADC_RAW_PWR.store(raw, Ordering::Relaxed);
                }
                if let Ok(raw) = adc.blocking_read(&mut ch_vout) {
                    ADC_RAW_VOUT.store(raw, Ordering::Relaxed);
                }
                if let Ok(raw) = adc.blocking_read(&mut ch_iin) {
                    ADC_RAW_IIN.store(raw, Ordering::Relaxed);
                }
            }
        }

        Timer::after_millis(1).await;
    }
}

const NEOPIXEL_COUNT: usize = 4;

/// Converts a raw 12-bit ADC reading (0..=4095) to an RGB status color:
/// - Below 50% (< 2048): Green
/// - In between values (50% to 100%):
///     50%..67%  (2048..2730): Yellow
///     67%..83%  (2731..3413): Orange
///     83%..100% (3414..4089): Red
/// - Over the limit / saturated (>= 4090): Blinking Red
fn adc_raw_to_rgb(raw: u16, blink_on: bool) -> RGB8 {
    if raw >= 4090 {
        if blink_on {
            RGB8 { r: 32, g: 0, b: 0 }
        } else {
            RGB8 { r: 0, g: 0, b: 0 }
        }
    } else if raw >= 3414 {
        RGB8 { r: 32, g: 0, b: 0 } // Red
    } else if raw >= 2731 {
        RGB8 { r: 32, g: 8, b: 0 } // Orange
    } else if raw >= 2048 {
        RGB8 { r: 32, g: 24, b: 0 } // Yellow
    } else {
        RGB8 { r: 0, g: 32, b: 0 } // Green
    }
}

/// Drives the 4-LED WS2812 strip on GPIO4:
/// - LED 0: Vin (ADC_PWR)
/// - LED 1: Vout (ADC_VOUT)
/// - LED 2: I (ADC_Input_Curr)
/// - LED 3: SPI packet heartbeat (flashes green on received frame, dark otherwise)
///
/// Runs on PIO1 with its own DMA channel, decoupled from SPI timing.
#[embassy_executor::task]
async fn neopixel_task(mut ws2812: PioWs2812<'static, PIO1, 0, NEOPIXEL_COUNT, Grb>) {
    const BLACK: RGB8 = RGB8 { r: 0, g: 0, b: 0 };
    const SPI_FLASH: RGB8 = RGB8 { r: 0, g: 32, b: 0 };

    let mut last_seen: u32 = 0;
    let mut flash_timer_ms: u8 = 0;
    let mut blink_tick: u16 = 0;
    let mut refresh_tick: u16 = 0;
    let mut last_pixels: [RGB8; NEOPIXEL_COUNT] = [BLACK; NEOPIXEL_COUNT];

    ws2812.write(&last_pixels).await;

    loop {
        let current = PACKET_COUNT.load(Ordering::Relaxed);
        if current != last_seen {
            last_seen = current;
            flash_timer_ms = 20; // 20 ms flash
        }

        let pwr_raw = ADC_RAW_PWR.load(Ordering::Relaxed);
        let vout_raw = ADC_RAW_VOUT.load(Ordering::Relaxed);
        let iin_raw = ADC_RAW_IIN.load(Ordering::Relaxed);

        // 250 ms ON / 250 ms OFF blinking phase for over-limit channels
        let blink_on = blink_tick < 250;

        let pixels = [
            adc_raw_to_rgb(pwr_raw, blink_on),
            adc_raw_to_rgb(vout_raw, blink_on),
            adc_raw_to_rgb(iin_raw, blink_on),
            if flash_timer_ms > 0 { SPI_FLASH } else { BLACK },
        ];

        // Write on state change or periodic 1-second refresh
        if pixels != last_pixels || refresh_tick >= 1000 {
            ws2812.write(&pixels).await;
            last_pixels = pixels;
            refresh_tick = 0;
        }

        if flash_timer_ms > 0 {
            flash_timer_ms = flash_timer_ms.saturating_sub(10);
        }

        blink_tick = (blink_tick + 10) % 500;
        refresh_tick = refresh_tick.saturating_add(10);

        Timer::after_millis(10).await;
    }
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    let initial_mode = FirmwareMode::from_u8(FIRMWARE_MODE.load(Ordering::Relaxed));
    if initial_mode == FirmwareMode::PowerSupply {
        defmt::info!(
            "mpp-firmware booted (PIO SPI slave), mode: {} ({})",
            initial_mode,
            mode_power_supply::PowerSupplyLoop::from_u8(
                mode_power_supply::POWER_SUPPLY_LOOP.load(Ordering::Relaxed)
            )
        );
    } else {
        defmt::info!(
            "mpp-firmware booted (PIO SPI slave), mode: {}",
            initial_mode
        );
    }

    // SEPIC gate PWM on GPIO15 (PWM_Gate net, through a 10R + 3.3nF network
    // into the driver stage): 100 kHz at the default 125 MHz sysclk with
    // divider 1, top = 1249. Duty is commanded via `DUTY` (u16, 0 = 0 %,
    // 65535 = 100 %) over the Pi SPI link.
    let mut pwm_cfg = PwmConfig::default();
    pwm_cfg.top = 1249;
    pwm_cfg.compare_b = 0;
    let mut pwm = Pwm::new_output_b(p.PWM_SLICE7, p.PIN_15, pwm_cfg.clone());

    // Curve-tracer relay + bleed PWM (mode_curve_tracer.rs owns both from
    // here on): idle low/0 is both the safe default and normal MPPT
    // operation (relay released, SEPIC path active, bleed PWM off).
    // Tracer_pwm on GPIO3 -> PWM_SLICE1 channel B (floor(3/2) = 1, odd ->
    // B - same RP2040 fixed GPIO-to-PWM-slice mapping as the SEPIC gate's
    // GPIO15 -> PWM_SLICE7 channel B, datasheet section 4.5.2).
    let mut tracer_pwm_cfg = PwmConfig::default();
    tracer_pwm_cfg.top = mode_curve_tracer::TRACER_PWM_MAX;
    tracer_pwm_cfg.compare_b = 0;
    let tracer_pwm = Pwm::new_output_b(p.PWM_SLICE1, p.PIN_3, tracer_pwm_cfg.clone());
    let tracer_en = Output::new(p.PIN_2, Level::Low);
    // But1 (active-low, switch to GND): edge-triggered sweep start, see
    // mode_curve_tracer::curve_tracer_task.
    let but1 = Input::new(p.PIN_0, Pull::Up);
    let curve_tracer =
        mode_curve_tracer::CurveTracer::new(tracer_en, tracer_pwm, tracer_pwm_cfg, but1);

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
    spawner.spawn(mode_curve_tracer::curve_tracer_task(curve_tracer).unwrap());

    let mut tick: u32 = 0;
    let mut psu_closed_loop = mode_power_supply::ClosedLoopState::new();
    let mut tracer_holding_panel = false;
    let mut last_applied_duty: u16 = u16::MAX;

    loop {
        // The gate must stay off both while a sweep is running
        // (TRACER_ACTIVE) and for as long as the relay stays engaged
        // afterward (RELAY_ENGAGED can outlive TRACER_ACTIVE - see its
        // doc comment). Driving the SEPIC while the relay holds the panel
        // on the bleed path would switch into a disconnected input.
        let tracer_holds_panel =
            TRACER_ACTIVE.load(Ordering::Relaxed) || RELAY_ENGAGED.load(Ordering::Relaxed);
        let active_mode = FirmwareMode::from_u8(FIRMWARE_MODE.load(Ordering::Relaxed));
        let commanded_duty = match active_mode {
            // Apply the Pi's commanded SPI duty directly, clamped as
            // defense-in-depth against SEPIC inductor current runaway.
            FirmwareMode::MppTracker => DUTY.load(Ordering::Relaxed).min(DUTY_MAX),
            FirmwareMode::PowerSupply => mode_power_supply::compute_duty(&mut psu_closed_loop),
        };
        
        // Hardware cutoffs protection
        let i_meas = MEAS_I_MA.load(Ordering::Relaxed);
        let v_in = MEAS_ADC_PWR_MV.load(Ordering::Relaxed);
        let v_out = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
        let imax = CUTOFF_IMAX_MA.load(Ordering::Relaxed);
        let vmax = CUTOFF_VMAX_MV.load(Ordering::Relaxed);

        let over_limit = (imax > 0 && i_meas > imax)
            || (vmax > 0 && (v_in > vmax || v_out > vmax));
        if over_limit && !CUTOFF_TRIPPED.load(Ordering::Relaxed) {
            CUTOFF_TRIPPED.store(true, Ordering::Relaxed);
            defmt::error!(
                "Hardware cutoff tripped: I={} mA (max {}), Vin={} mV, Vout={} mV (max {})",
                i_meas, imax, v_in, v_out, vmax
            );
        }
        let cutoff_tripped = CUTOFF_TRIPPED.load(Ordering::Relaxed);

        let duty = if tracer_holds_panel || cutoff_tripped {
            0
        } else {
            if tracer_holding_panel {
                // Falling edge: the relay just handed the panel back to
                // the SEPIC path. compute_duty() was skipped for the
                // whole hold, so PowerSupply mode's closed loop must not
                // resume from its stale pre-hold ps_duty - see
                // ClosedLoopState::reset()'s doc comment. A no-op in
                // MppTracker mode, which has no closed-loop state to go
                // stale.
                psu_closed_loop.reset();
            }
            commanded_duty
        };
        tracer_holding_panel = tracer_holds_panel;

        if duty != last_applied_duty {
            last_applied_duty = duty;
        }

        pwm_cfg.compare_b = (duty as u32 * 1250 / 65536) as u16;
        pwm.set_config(&pwm_cfg);

        tick = tick.wrapping_add(1);
        if tick.is_multiple_of(500) {
            // 500 ms per half-period at the 1 ms loop cadence -> ~1 Hz blink.
            heartbeat.toggle();
        }

        Timer::after_millis(1).await;
    }
}
