//! Decision logic of the Pico (I2C master): which alpha goes to the dimmer now.
//! Pure, so the safety rules run as host unit tests.

use crate::{ALPHA_OFF, HOST_TIMEOUT_MS};

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

#[cfg(test)]
mod tests {
    use super::*;

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
    fn an_out_of_range_request_never_passes() {
        assert_eq!(alpha_to_send(u16::MAX, Some(0), false), ALPHA_OFF);
    }
}
