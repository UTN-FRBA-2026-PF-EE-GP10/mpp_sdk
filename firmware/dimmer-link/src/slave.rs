//! Pure logic of the dimmer (slave) side: what the status reports and when
//! the deadman fires. The ESP32-C3 firmware calls these from its I2C task and
//! its watchdog loop, so the host tests cover the decisions that matter.

use crate::{ALPHA_FULL_ON, ALPHA_OFF, APPLIED_NONE, FRACTION_FULL, FRACTION_OFF};

/// The angle the dimmer really fires at, in centi-degrees, for the status frame.
///
/// Same math as the firing code: `delay = clamp(fraction * half / 65536,
/// min_delay_us, half - min_tail_us)`, and the angle is `delay / half * 180
/// degrees`. `APPLIED_NONE` when the dimmer does not fire (off, not locked, or
/// no usable half-period).
pub fn applied_alpha(
    fraction: u32,
    half_us: u32,
    locked: bool,
    min_delay_us: u32,
    min_tail_us: u32,
) -> u16 {
    if !locked || fraction == FRACTION_OFF {
        return APPLIED_NONE;
    }
    if fraction == FRACTION_FULL {
        return ALPHA_FULL_ON;
    }
    if half_us <= min_delay_us.saturating_add(min_tail_us) {
        return APPLIED_NONE;
    }
    let delay = (((fraction as u64 * half_us as u64) >> 16) as u32)
        .clamp(min_delay_us, half_us - min_tail_us);
    let alpha = (delay as u64 * ALPHA_OFF as u64 + half_us as u64 / 2) / half_us as u64;
    alpha as u16
}

/// True when the deadman must switch the lamp off: a command was received
/// before (`armed`) and the last valid one is older than `timeout_ms`.
/// Times are wrapping milliseconds.
pub fn command_timed_out(armed: bool, last_command_ms: u32, now_ms: u32, timeout_ms: u32) -> bool {
    armed && now_ms.wrapping_sub(last_command_ms) > timeout_ms
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::alpha_to_fraction;

    const MIN_DELAY: u32 = 1_400;
    const MIN_TAIL: u32 = 1_500;

    fn applied(fraction: u32, half: u32, locked: bool) -> u16 {
        applied_alpha(fraction, half, locked, MIN_DELAY, MIN_TAIL)
    }

    #[test]
    fn mid_angle_is_reported_unchanged() {
        assert_eq!(applied(alpha_to_fraction(9_000), 10_000, true), 9_000);
    }

    #[test]
    fn early_angle_is_raised_to_the_min_delay() {
        // 1.4 ms of 10 ms is 25.2 degrees.
        assert_eq!(applied(alpha_to_fraction(500), 10_000, true), 2_520);
    }

    #[test]
    fn late_angle_is_lowered_to_the_min_tail() {
        // 8.5 ms of 10 ms is 153 degrees.
        assert_eq!(applied(alpha_to_fraction(17_900), 10_000, true), 15_300);
    }

    #[test]
    fn full_on_and_off_are_exceptions() {
        assert_eq!(applied(FRACTION_FULL, 10_000, true), ALPHA_FULL_ON);
        assert_eq!(applied(FRACTION_OFF, 10_000, true), APPLIED_NONE);
    }

    #[test]
    fn no_lock_or_no_half_period_means_no_firing() {
        assert_eq!(applied(FRACTION_FULL, 10_000, false), APPLIED_NONE);
        assert_eq!(applied(alpha_to_fraction(9_000), 10_000, false), APPLIED_NONE);
        assert_eq!(applied(alpha_to_fraction(9_000), 0, true), APPLIED_NONE);
        assert_eq!(applied(alpha_to_fraction(9_000), 2_900, true), APPLIED_NONE);
    }

    #[test]
    fn applied_never_exceeds_off() {
        for half in [8_000, 10_000, 12_500] {
            for alpha in (1..ALPHA_OFF).step_by(97) {
                assert!(applied(alpha_to_fraction(alpha), half, true) < ALPHA_OFF);
            }
        }
    }

    #[test]
    fn timeout_needs_an_armed_deadman() {
        assert!(!command_timed_out(false, 0, 1_000_000, 2_000));
    }

    #[test]
    fn timeout_fires_only_after_the_limit() {
        assert!(!command_timed_out(true, 1_000, 3_000, 2_000));
        assert!(command_timed_out(true, 1_000, 3_001, 2_000));
    }

    #[test]
    fn timeout_survives_the_clock_wrap() {
        let last = u32::MAX - 500;
        assert!(!command_timed_out(true, last, 1_000, 2_000));
        assert!(command_timed_out(true, last, 2_000, 2_000));
    }
}
