//! Decision logic of the Pico (I2C master): which alpha goes to the dimmer now.
//! Pure, so the safety rules run as host unit tests.

use crate::{ALPHA_OFF, HOST_TIMEOUT_MS, flags};

/// Alpha to send to the dimmer.
///
/// - `requested`: the last valid alpha from the Pi.
/// - `host_age_ms`: time since the last valid command from the Pi, `None` if none came since boot.
/// - `link_lost`: the SPI link to the Pi is down.
///
/// The lamp is off unless the Pi is present and recent.
pub fn alpha_to_send(requested: u16, host_age_ms: Option<u32>, link_lost: bool) -> u16 {
    match host_age_ms {
        Some(age) if !link_lost && age < HOST_TIMEOUT_MS => requested.min(ALPHA_OFF),
        _ => ALPHA_OFF,
    }
}

/// Flags and budget for the SPI `0xD2` reply: `(flags, budget_s)`.
///
/// The dimmer flags move up one bit (bit 0 is `link_ok`), so `TRIPPED` is
/// bit 4. Without a fresh I2C status the budget is 0 and `TRIPPED` is clear:
/// the data is stale and `link_ok` already says so.
pub fn spi_status_fields(dimmer_flags: u8, budget_s: u8, link_ok: bool) -> (u8, u8) {
    let known = dimmer_flags & (flags::MAINS | flags::LOCKED | flags::TIMED_OUT | flags::TRIPPED);
    if link_ok {
        ((known << 1) | 1, budget_s)
    } else {
        ((known & !flags::TRIPPED) << 1, 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spi_fields_shift_the_dimmer_flags_and_carry_the_budget() {
        let all = flags::MAINS | flags::LOCKED | flags::TIMED_OUT | flags::TRIPPED;
        assert_eq!(spi_status_fields(all, 77, true), (0b1_1111, 77));
        assert_eq!(spi_status_fields(flags::TRIPPED, 0, true), (0b1_0001, 0));
        assert_eq!(spi_status_fields(flags::MAINS, 120, true), (0b0_0011, 120));
        // An unknown high bit never leaks into the reply.
        assert_eq!(spi_status_fields(0xF0, 5, true), (0b1, 5));
    }

    #[test]
    fn spi_fields_without_a_fresh_status_report_budget_0_and_not_tripped() {
        let (f, b) = spi_status_fields(flags::TRIPPED | flags::MAINS, 200, false);
        assert_eq!(b, 0);
        // Link bit and tripped bit clear; the older flags keep their old behaviour.
        assert_eq!(f, flags::MAINS << 1);
    }

    #[test]
    fn boot_before_any_command_is_off() {
        assert_eq!(alpha_to_send(0, None, false), ALPHA_OFF);
        assert_eq!(alpha_to_send(9_000, None, false), ALPHA_OFF);
    }

    #[test]
    fn a_recent_valid_command_passes_through() {
        assert_eq!(alpha_to_send(9_000, Some(0), false), 9_000);
        assert_eq!(alpha_to_send(0, Some(HOST_TIMEOUT_MS - 1), false), 0);
    }

    #[test]
    fn host_timeout_turns_the_lamp_off() {
        assert_eq!(
            alpha_to_send(9_000, Some(HOST_TIMEOUT_MS), false),
            ALPHA_OFF
        );
        assert_eq!(alpha_to_send(0, Some(u32::MAX), false), ALPHA_OFF);
    }

    #[test]
    fn a_lost_spi_link_turns_the_lamp_off() {
        assert_eq!(alpha_to_send(9_000, Some(0), true), ALPHA_OFF);
    }

    #[test]
    fn a_link_gap_leaves_the_lamp_off_until_a_new_command() {
        // The Pico clears its host timestamp on link loss: no command seen.
        assert_eq!(alpha_to_send(ALPHA_OFF, None, false), ALPHA_OFF);
    }

    #[test]
    fn an_out_of_range_request_never_passes() {
        assert_eq!(alpha_to_send(u16::MAX, Some(0), false), ALPHA_OFF);
    }
}
