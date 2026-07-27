//! `FirmwareMode::MppTracker`: the Pi's SPI-commanded duty applied
//! directly to the SEPIC gate, unmodified beyond the safety clamp - the
//! real MPPT deployment path (`AGENTS.md`: firmware stays a dumb I/O
//! proxy). Never touches `mode_power_supply.rs`'s state.

use portable_atomic::Ordering;

use crate::{DUTY, DUTY_MAX};

/// Clamped at `DUTY_MAX` (95 %), defense-in-depth against SEPIC inductor
/// current runaway.
pub fn compute_duty() -> u16 {
    DUTY.load(Ordering::Relaxed).min(DUTY_MAX)
}
