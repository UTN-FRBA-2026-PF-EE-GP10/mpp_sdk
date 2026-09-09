//! `FirmwareMode::PowerSupply`: autonomous Vout regulation for standalone
//! bench tests, with no Pi needed. It ignores the Pi's commanded `DUTY`
//! and never touches `MppTracker`'s duty (`main.rs`). The SPI link-lost
//! watchdog does not apply here, since this mode must keep running with
//! no Pi attached.

use portable_atomic::Ordering;

use crate::{ADC_SAMPLE_COUNT, DUTY_MAX, MEAS_ADC_VOUT_MV, MEAS_V_MV};

/// `OpenLoop` checks the SEPIC transfer-ratio math and ADC/PWM wiring
/// before trusting `ClosedLoop`'s feedback.
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum PowerSupplyLoop {
    OpenLoop,
    ClosedLoop,
}

pub const POWER_SUPPLY_LOOP: PowerSupplyLoop = PowerSupplyLoop::ClosedLoop;

/// D = 0.5 is unity gain (`V_out = V_in`). Bench value for a 5 V lab PSU
/// into the 10R/5W load.
pub const POWER_SUPPLY_FIXED_DUTY: u16 = 32768;

/// Bench value: 5 V from a 5 V lab PSU into the 10R/5W load.
pub const POWER_SUPPLY_VOUT_MV: u16 = 5000;

/// Tuned on-target: 50/200 was too slow, both for trim speed and
/// load-step recovery.
const GAIN_DIVISOR: u16 = 20;
/// One step per fresh ADC sample (~10 Hz), so a step moves duty by at
/// most ~1.2 %. Raise with care — watch for oscillation.
const MIN_STEP: u16 = 1;
const MAX_STEP: u16 = 800;

/// Below this, treat `MEAS_V_MV` as not-yet-real (its default before the
/// first successful read is 0), not a real near-zero Vin. Otherwise
/// `feedforward_duty` computes near-100 % duty as Vin -> 0.
const MIN_VALID_VIN_MV: u16 = 500;

/// Jumps straight to the ideal SEPIC ratio's duty
/// (`D = V_out/(V_in + V_out)`) instead of climbing there step by step
/// from zero, which is too slow on real hardware. `step()`'s trim then
/// closes the gap from the real losses this ideal formula ignores.
fn feedforward_duty(vin_mv: u16, vout_target_mv: u16) -> u16 {
    let vin = vin_mv as u32;
    let vout = vout_target_mv as u32;
    ((vout * 65535 / (vin + vout)) as u16).min(DUTY_MAX)
}

/// One instance, owned by `main()`'s loop.
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

    /// Re-seeds as if from a cold start. `main()` calls this when the
    /// curve-tracer relay hands the panel back after a sweep: `ps_duty`
    /// would otherwise still hold its stale pre-sweep value and jump
    /// straight to it, skipping `MIN_STEP`/`MAX_STEP` — but the duty
    /// actually applied during the sweep was 0, not `ps_duty`. Starting
    /// cold (a `feedforward_duty` jump, then trim) matches reality.
    pub fn reset(&mut self) {
        *self = Self::new();
    }

    /// Steps at most once per fresh ADC sample (~10 Hz) — gated on
    /// `ADC_SAMPLE_COUNT`, not `MEAS_ADC_VOUT_MV`'s value, since a
    /// repeated value does not mean a stale sample (see that static's
    /// doc comment in `main.rs`). Called every 1 ms regardless; most
    /// calls are no-ops.
    fn step(&mut self) -> u16 {
        let sample = ADC_SAMPLE_COUNT.load(Ordering::Relaxed);
        if self.last_adc_sample_seen == Some(sample) {
            return self.ps_duty;
        }
        self.last_adc_sample_seen = Some(sample);

        if !self.seeded {
            // No-op until Vin looks real — see MIN_VALID_VIN_MV.
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

pub fn compute_duty(closed_loop: &mut ClosedLoopState) -> u16 {
    match POWER_SUPPLY_LOOP {
        PowerSupplyLoop::OpenLoop => POWER_SUPPLY_FIXED_DUTY.min(DUTY_MAX),
        PowerSupplyLoop::ClosedLoop => closed_loop.step(),
    }
}
