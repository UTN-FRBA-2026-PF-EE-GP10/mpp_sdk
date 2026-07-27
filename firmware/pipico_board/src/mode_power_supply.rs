//! `FirmwareMode::PowerSupply`: local, autonomous Vout regulation for
//! standalone bench characterization - ignores the Pi's commanded `DUTY`
//! for gate control (the SPI frame still exchanges normally for
//! telemetry). Never touches `MppTracker`'s duty (`main.rs`). See plan 011's
//! history for the full design rationale, including why the SPI
//! link-lost watchdog does NOT apply here.

use portable_atomic::Ordering;

use crate::{ADC_SAMPLE_COUNT, DUTY_MAX, MEAS_ADC_VOUT_MV, MEAS_V_MV};

/// `OpenLoop`: fixed `POWER_SUPPLY_FIXED_DUTY`, no feedback - a sanity
/// check for the SEPIC transfer-ratio math and ADC/PWM wiring, meant to
/// run before trusting `ClosedLoop`. `ClosedLoop`: regulates `Vout` to
/// `POWER_SUPPLY_VOUT_MV` automatically.
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum PowerSupplyLoop {
    OpenLoop,
    ClosedLoop,
}

pub const POWER_SUPPLY_LOOP: PowerSupplyLoop = PowerSupplyLoop::ClosedLoop;

/// `OpenLoop` bench-test duty: D = 0.5 (unity gain, V_out = V_in at
/// D = 0.5). Bench value for a 5 V lab PSU input into the 10R/5W load.
pub const POWER_SUPPLY_FIXED_DUTY: u16 = 32768;

/// `ClosedLoop` target output voltage in millivolts. Bench value: 5 V
/// from a 5 V lab PSU input into the 10R/5W load.
pub const POWER_SUPPLY_VOUT_MV: u16 = 5000;

/// Proportional gain: raw step (before clamping) is `err_mv /
/// GAIN_DIVISOR`. Tuned on-target - both bench trim speed and load-step
/// recovery were too slow at the initial 50/200.
const GAIN_DIVISOR: u16 = 20;
/// Per-sample step bounds (duty counts, out of 65535) - one step per
/// fresh ADC sample (~10 Hz), so a single step moves duty by at most
/// ~1.2 %. Watch for oscillation before raising further.
const MIN_STEP: u16 = 1;
const MAX_STEP: u16 = 800;

/// Below this, `MEAS_V_MV` (INA229) is "not a real reading yet" (e.g.
/// before its first successful read, which defaults to 0) rather than a
/// genuine near-zero Vin - `feedforward_duty` would otherwise compute a
/// duty near 100 % as Vin -> 0.
const MIN_VALID_VIN_MV: u16 = 500;

/// One-time feed-forward jump: the ideal (lossless) SEPIC ratio
/// `V_out = V_in * D/(1-D)` solved for `D = V_out/(V_in + V_out)`, applied
/// directly instead of climbing there via proportional steps from
/// `ps_duty = 0` (too slow on real hardware). The trim in `step()` then
/// closes the remaining gap from real losses this ideal formula ignores.
fn feedforward_duty(vin_mv: u16, vout_target_mv: u16) -> u16 {
    let vin = vin_mv as u32;
    let vout = vout_target_mv as u32;
    ((vout * 65535 / (vin + vout)) as u16).min(DUTY_MAX)
}

/// Owned by `main()`'s loop - exactly one instance ever runs.
pub struct ClosedLoopState {
    ps_duty: u16,
    last_adc_sample_seen: Option<u32>,
    seeded: bool,
}

impl ClosedLoopState {
    pub const fn new() -> Self {
        Self {
            ps_duty: 0,
            last_adc_sample_seen: None,
            seeded: false,
        }
    }

    /// Steps at most once per fresh ADC sample (~10 Hz), gated on
    /// `ADC_SAMPLE_COUNT` rather than on `MEAS_ADC_VOUT_MV`'s value - see
    /// that static's doc comment in `main.rs` for why. Called every 1 ms
    /// main-loop tick regardless; most calls are no-ops.
    fn step(&mut self) -> u16 {
        let sample = ADC_SAMPLE_COUNT.load(Ordering::Relaxed);
        if self.last_adc_sample_seen == Some(sample) {
            return self.ps_duty;
        }
        self.last_adc_sample_seen = Some(sample);

        if !self.seeded {
            // Safe no-op each sample until Vin looks real - see
            // MIN_VALID_VIN_MV.
            let vin_mv = MEAS_V_MV.load(Ordering::Relaxed);
            if vin_mv >= MIN_VALID_VIN_MV {
                self.ps_duty = feedforward_duty(vin_mv, POWER_SUPPLY_VOUT_MV);
                self.seeded = true;
            }
            return self.ps_duty;
        }

        let vout_mv = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
        if vout_mv < POWER_SUPPLY_VOUT_MV {
            let step = ((POWER_SUPPLY_VOUT_MV - vout_mv) / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
            self.ps_duty = self.ps_duty.saturating_add(step).min(DUTY_MAX);
        } else if vout_mv > POWER_SUPPLY_VOUT_MV {
            let step = ((vout_mv - POWER_SUPPLY_VOUT_MV) / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
            self.ps_duty = self.ps_duty.saturating_sub(step);
        }
        self.ps_duty
    }
}

/// Compute this tick's gate duty for `PowerSupply` mode.
pub fn compute_duty(closed_loop: &mut ClosedLoopState) -> u16 {
    match POWER_SUPPLY_LOOP {
        PowerSupplyLoop::OpenLoop => POWER_SUPPLY_FIXED_DUTY.min(DUTY_MAX),
        PowerSupplyLoop::ClosedLoop => closed_loop.step(),
    }
}
