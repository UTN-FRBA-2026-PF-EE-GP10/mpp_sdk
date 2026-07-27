//! `FirmwareMode::MppTracker`: the Pi's SPI-commanded duty is applied
//! directly to the SEPIC gate, unmodified beyond the safety clamp. This is
//! the real MPPT deployment path - the RP2040 stays a dumb I/O proxy, all
//! control decisions are made on the Pi (see `AGENTS.md`). Never touches
//! `PowerSupply` mode's state (see `psu_mode.rs`).

use portable_atomic::Ordering;

use crate::{DUTY, DUTY_MAX};

/// Apply the Pi's commanded SPI duty directly, clamped at `DUTY_MAX` (95 %)
/// as defense-in-depth against SEPIC inductor current runaway - see
/// `main.rs`'s `DUTY_MAX` doc comment.
pub fn compute_duty() -> u16 {
    DUTY.load(Ordering::Relaxed).min(DUTY_MAX)
}
