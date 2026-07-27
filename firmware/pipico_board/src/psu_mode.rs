//! `FirmwareMode::PowerSupply`: local, autonomous Vout regulation for
//! standalone bench characterization - ignores the Pi's commanded `DUTY`
//! for gate control (the SPI frame still exchanges normally, so
//! `spi_test.py` keeps working for telemetry/monitoring). Never touches
//! `MppTracker`'s path (see `mpp_slave.rs`) - see plan 011 for the full
//! design rationale, including the deliberate operator decision that the
//! SPI link-lost watchdog does NOT apply here (this mode must keep
//! regulating standalone with no host attached).

use portable_atomic::{AtomicU32, Ordering};

use crate::{DUTY_MAX, MEAS_ADC_VOUT_MV, MEAS_V_MV};

/// Selects whether the gate duty is a fixed constant (`OpenLoop` - no ADC
/// feedback at all, applies `POWER_SUPPLY_FIXED_DUTY` unconditionally) or
/// continuously regulated to `POWER_SUPPLY_VOUT_MV` via `MEAS_ADC_VOUT_MV`
/// feedback (`ClosedLoop`). `OpenLoop` exists to sanity-check the SEPIC
/// transfer-ratio math and the ADC/PWM wiring against a known duty before
/// trusting the closed loop's automatic corrections - bring up in
/// `OpenLoop` first.
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum PowerSupplyLoop {
    OpenLoop,
    ClosedLoop,
}

pub const POWER_SUPPLY_LOOP: PowerSupplyLoop = PowerSupplyLoop::ClosedLoop;

/// `OpenLoop` bench-test duty: D = 0.5 (32768 / 65535), the unity-gain
/// point (V_out = V_in * D/(1-D) = V_in at D = 0.5) - a 5 V lab PSU input
/// into the known-good 10R/5W load (plan 002) should give ~5 V out, well
/// within both the resistor's power rating (2.5 W of its 5 W) and the
/// board's 1 A panel-input limit (~0.6 A). An earlier 0.375 fixed-duty
/// test targeting 3 V measured 2.5 V (real diode/switch/DCR losses, not a
/// bug) - this unity-gain point has proportionally less loss to show.
/// Clamped by `DUTY_MAX` like every other duty source.
pub const POWER_SUPPLY_FIXED_DUTY: u16 = 32768;

/// Target output voltage in millivolts for `PowerSupplyLoop::ClosedLoop`.
/// Bench-test value: 5 V from a 5 V lab PSU input into the known-good
/// 10R/5W load (plan 002) - the same unity-gain point the `OpenLoop` test
/// measured at 4.4 V (real losses shy of the 5 V ideal). The closed loop
/// pushes duty past D = 0.5 to make up that gap and land on the real
/// 5000 mV target. Safe on both the resistor (Iout = 0.5 A, Pout = 2.5 W
/// of its 5 W rating) and the board's 1 A panel-input limit (Iin ~=
/// 0.6 A). Revert to a normal default before merging.
pub const POWER_SUPPLY_VOUT_MV: u16 = 5000;

/// Bumped once per `onchip_adc_task` poll (~100 ms, `main.rs`).
/// `ClosedLoopState::step` gates its control step on this counter, not on
/// `MEAS_ADC_VOUT_MV`'s value - the reading can legitimately repeat across
/// samples (e.g. Vout not moving yet at boot), and gating on
/// value-equality instead of sample-freshness stalls the controller
/// forever the first time that happens.
pub static ADC_SAMPLE_COUNT: AtomicU32 = AtomicU32::new(0);

/// Proportional gain: the raw step (before clamping) is `err_mv /
/// GAIN_DIVISOR`. Raised from an initial 50 after on-target testing showed
/// convergence to a setpoint (and recovery from a load-current step, e.g.
/// a motor load) was too slow - this is a straightforward gain increase on
/// the same proportional law, not a switch to PI/PID (see plan 011's STOP
/// condition on that).
const GAIN_DIVISOR: u16 = 20;
/// Per-sample step bounds (duty counts, out of 65535). Raised from 200 to
/// 800 alongside `GAIN_DIVISOR` for the same reason. Still far below
/// `DUTY_MAX`, and still gated to at most one step per fresh ADC sample
/// (~10 Hz), so a single step can move duty by at most ~1.2 % - watch for
/// oscillation on the bench before raising either constant further.
const MIN_STEP: u16 = 1;
const MAX_STEP: u16 = 800;

/// Below this, `MEAS_V_MV` (INA229) is treated as "not a real reading yet"
/// (e.g. before `sensors_task`'s first successful read, which defaults to
/// 0) rather than a genuine near-zero Vin. Seeding the feed-forward jump
/// off a bogus near-zero Vin would compute a duty near 100 % (`D =
/// V_out/(V_in + V_out)` blows up as V_in -> 0) - this floor is what stops
/// that. Well below any input this board is meant to run from.
const MIN_VALID_VIN_MV: u16 = 500;

/// One-time feed-forward jump: solves the ideal (lossless) SEPIC ratio
/// `V_out = V_in * D/(1-D)` for `D = V_out/(V_in + V_out)` and applies it
/// directly, instead of climbing there purely via `GAIN_DIVISOR`/`MAX_STEP`
/// proportional steps from `ps_duty = 0` - on-target testing showed that
/// climb alone converges too slowly for a bench supply, especially at
/// setpoints far from the start. The proportional trim in `step()` then
/// closes the remaining gap from real losses (diode/switch/DCR drops -
/// see `docs/rationale.md`'s CCM/DCM section) this ideal formula ignores.
fn feedforward_duty(vin_mv: u16, vout_target_mv: u16) -> u16 {
    let vin = vin_mv as u32;
    let vout = vout_target_mv as u32;
    let duty = (vout * 65535) / (vin + vout);
    (duty as u16).min(DUTY_MAX)
}

/// Per-run closed-loop state - owned by `main()`'s loop (one instance),
/// not global, since exactly one instance of this controller ever runs.
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

    /// Steps the controller at most once per fresh ADC sample (~10 Hz) -
    /// see `ADC_SAMPLE_COUNT`'s doc comment for why this must be gated on
    /// sample-freshness, not on the measured value changing. `main.rs`
    /// calls this every 1 ms tick regardless; most calls are no-ops.
    fn step(&mut self) -> u16 {
        let sample = ADC_SAMPLE_COUNT.load(Ordering::Relaxed);
        if self.last_adc_sample_seen != Some(sample) {
            self.last_adc_sample_seen = Some(sample);

            if !self.seeded {
                // Wait for a plausible Vin reading before jumping - see
                // MIN_VALID_VIN_MV's doc comment. Until then, ps_duty stays
                // at its safe initial 0 and this is a no-op each sample.
                let vin_mv = MEAS_V_MV.load(Ordering::Relaxed);
                if vin_mv >= MIN_VALID_VIN_MV {
                    self.ps_duty = feedforward_duty(vin_mv, POWER_SUPPLY_VOUT_MV);
                    self.seeded = true;
                }
                return self.ps_duty;
            }

            let vout_mv = MEAS_ADC_VOUT_MV.load(Ordering::Relaxed);
            if vout_mv < POWER_SUPPLY_VOUT_MV {
                // Below target Vout: increase duty to boost voltage.
                let err = POWER_SUPPLY_VOUT_MV - vout_mv;
                let step = (err / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
                self.ps_duty = self.ps_duty.saturating_add(step).min(DUTY_MAX);
            } else if vout_mv > POWER_SUPPLY_VOUT_MV {
                // Above target Vout: decrease duty to lower voltage.
                let err = vout_mv - POWER_SUPPLY_VOUT_MV;
                let step = (err / GAIN_DIVISOR).clamp(MIN_STEP, MAX_STEP);
                self.ps_duty = self.ps_duty.saturating_sub(step);
            }
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
