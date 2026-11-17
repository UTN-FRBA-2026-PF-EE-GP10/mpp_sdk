//! Wire format of the I2C link between the Pico (master) and the ESP32-C3 on
//! the dimmer board (slave). Both firmwares depend on this crate, so the two
//! ends cannot drift. It is `no_std` and has no dependencies, so `cargo test`
//! runs it on the host.
//!
//! The firing angle `alpha` travels in centi-degrees: 0 is full on, 18000
//! (180.00 degrees) is off.
#![cfg_attr(not(test), no_std)]

pub mod master;
pub mod slave;

/// 7-bit I2C address of the dimmer.
pub const I2C_ADDRESS: u8 = 0x2A;

/// Full on: the firing pulse is held, the TRIAC conducts the whole half-cycle.
pub const ALPHA_FULL_ON: u16 = 0;
/// Off: no firing pulse.
pub const ALPHA_OFF: u16 = 18_000;
/// `Status::alpha_applied` while the dimmer does not fire.
pub const APPLIED_NONE: u16 = u16::MAX;

/// The dimmer turns the lamp off when no valid `SetAlpha` arrives for this long.
pub const COMMAND_TIMEOUT_MS: u32 = 2_000;
/// The Pico turns the lamp off when the Pi sends no valid alpha command for this long.
pub const HOST_TIMEOUT_MS: u32 = 3_000;
/// The master repeats the last `SetAlpha` this often, also when nothing changed.
pub const KEEPALIVE_MS: u32 = 500;
/// The master waits this long between `RequestStatus` and the read.
pub const STATUS_DELAY_MS: u32 = 3;

pub const COMMAND_LEN: usize = 4;
pub const STATUS_LEN: usize = 8;

const CMD_SET_ALPHA: u8 = 0x01;
const CMD_REQUEST_STATUS: u8 = 0x02;
const STATUS_MAGIC: u8 = 0xD1;

/// `Status::flags` bits.
pub mod flags {
    /// Zero-cross pulses are arriving.
    pub const MAINS: u8 = 1 << 0;
    /// The dimmer is locked to the mains and may fire.
    pub const LOCKED: u8 = 1 << 1;
    /// The lamp was switched off because no valid command arrived in time.
    pub const TIMED_OUT: u8 = 1 << 2;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    Length,
    Crc,
    /// Unknown command byte, or a magic byte that does not match.
    Unknown,
    /// Alpha above `ALPHA_OFF`.
    Range,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Command {
    SetAlpha(u16),
    RequestStatus,
}

/// What the dimmer reports back.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Status {
    pub flags: u8,
    /// Angle the dimmer really fires at after its limits, or `APPLIED_NONE`.
    pub alpha_applied: u16,
    /// Mains frequency in 0.01 Hz, 0 without mains.
    pub freq_centi_hz: u16,
    /// Commands rejected so far (wraps). A rising value means a noisy cable.
    pub bad_frames: u8,
}

/// CRC-8, polynomial 0x07, init 0xFF: the same as the SPI link to the Pi.
pub fn crc8(data: &[u8]) -> u8 {
    let mut crc: u8 = 0xFF;
    for &byte in data {
        crc ^= byte;
        for _ in 0..8 {
            crc = if crc & 0x80 != 0 {
                (crc << 1) ^ 0x07
            } else {
                crc << 1
            };
        }
    }
    crc
}

/// `[cmd, arg_hi, arg_lo, crc]`. `RequestStatus` sends a zero argument.
pub fn encode_command(command: Command) -> [u8; COMMAND_LEN] {
    let (cmd, arg) = match command {
        Command::SetAlpha(alpha) => (CMD_SET_ALPHA, alpha),
        Command::RequestStatus => (CMD_REQUEST_STATUS, 0),
    };
    let mut frame = [cmd, (arg >> 8) as u8, arg as u8, 0];
    frame[3] = crc8(&frame[..3]);
    frame
}

pub fn decode_command(frame: &[u8]) -> Result<Command, Error> {
    if frame.len() != COMMAND_LEN {
        return Err(Error::Length);
    }
    if crc8(&frame[..3]) != frame[3] {
        return Err(Error::Crc);
    }
    let arg = u16::from_be_bytes([frame[1], frame[2]]);
    match frame[0] {
        CMD_SET_ALPHA if arg <= ALPHA_OFF => Ok(Command::SetAlpha(arg)),
        CMD_SET_ALPHA => Err(Error::Range),
        CMD_REQUEST_STATUS if arg == 0 => Ok(Command::RequestStatus),
        _ => Err(Error::Unknown),
    }
}

/// `[magic, flags, alpha_hi, alpha_lo, freq_hi, freq_lo, bad_frames, crc]`.
pub fn encode_status(status: &Status) -> [u8; STATUS_LEN] {
    let alpha = status.alpha_applied.to_be_bytes();
    let freq = status.freq_centi_hz.to_be_bytes();
    let mut frame = [
        STATUS_MAGIC,
        status.flags,
        alpha[0],
        alpha[1],
        freq[0],
        freq[1],
        status.bad_frames,
        0,
    ];
    frame[7] = crc8(&frame[..7]);
    frame
}

pub fn decode_status(frame: &[u8]) -> Result<Status, Error> {
    if frame.len() != STATUS_LEN {
        return Err(Error::Length);
    }
    if crc8(&frame[..7]) != frame[7] {
        return Err(Error::Crc);
    }
    if frame[0] != STATUS_MAGIC {
        return Err(Error::Unknown);
    }
    Ok(Status {
        flags: frame[1],
        alpha_applied: u16::from_be_bytes([frame[2], frame[3]]),
        freq_centi_hz: u16::from_be_bytes([frame[4], frame[5]]),
        bad_frames: frame[6],
    })
}

/// Firing delay fraction that means full on (the firing pulse is held).
pub const FRACTION_FULL: u32 = 0;
/// Firing delay fraction that means off (never fire). Not a valid Q16 value,
/// so it cannot be mistaken for a late firing angle.
pub const FRACTION_OFF: u32 = u32::MAX;

/// Firing angle as a fraction of the half-period in Q16 (0..=65535), the
/// unit the dimmer firmware uses for its firing delay. The angle runs from 0
/// to 180 degrees over one half-period. Alpha 0 gives `FRACTION_FULL` and
/// `ALPHA_OFF` or more gives `FRACTION_OFF`.
pub fn alpha_to_fraction(alpha: u16) -> u32 {
    if alpha >= ALPHA_OFF {
        return FRACTION_OFF;
    }
    (alpha as u32 * 65_536 + ALPHA_OFF as u32 / 2) / ALPHA_OFF as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc_matches_the_spi_link_vectors() {
        assert_eq!(crc8(&[0x01, 0x23, 0x28]), 0x09);
        assert_eq!(crc8(&[0x01, 0x00, 0x00]), 0x40);
        assert_eq!(crc8(&[0x02, 0x00, 0x00]), 0xFD);
    }

    #[test]
    fn set_alpha_frame_is_pinned() {
        assert_eq!(
            encode_command(Command::SetAlpha(9_000)),
            [0x01, 0x23, 0x28, 0x09]
        );
        assert_eq!(
            encode_command(Command::SetAlpha(ALPHA_FULL_ON)),
            [0x01, 0x00, 0x00, 0x40]
        );
        assert_eq!(
            encode_command(Command::SetAlpha(ALPHA_OFF)),
            [0x01, 0x46, 0x50, 0xD2]
        );
    }

    #[test]
    fn request_status_frame_is_pinned() {
        assert_eq!(
            encode_command(Command::RequestStatus),
            [0x02, 0x00, 0x00, 0xFD]
        );
    }

    #[test]
    fn commands_round_trip() {
        for alpha in [0, 1, 4_500, 9_000, 17_999, ALPHA_OFF] {
            let frame = encode_command(Command::SetAlpha(alpha));
            assert_eq!(decode_command(&frame), Ok(Command::SetAlpha(alpha)));
        }
        let frame = encode_command(Command::RequestStatus);
        assert_eq!(decode_command(&frame), Ok(Command::RequestStatus));
    }

    #[test]
    fn a_flipped_bit_is_rejected() {
        let good = encode_command(Command::SetAlpha(9_000));
        for byte in 0..COMMAND_LEN {
            for bit in 0..8 {
                let mut bad = good;
                bad[byte] ^= 1 << bit;
                assert!(decode_command(&bad).is_err(), "byte {byte} bit {bit}");
            }
        }
    }

    #[test]
    fn a_shifted_frame_is_rejected() {
        // A zero-argument frame shifted by one byte must not pass: same reason as the SPI CRC.
        let good = encode_command(Command::SetAlpha(ALPHA_FULL_ON));
        let shifted = [good[1], good[2], good[3], good[0]];
        assert!(decode_command(&shifted).is_err());
    }

    #[test]
    fn wrong_length_is_rejected() {
        assert_eq!(decode_command(&[0x01, 0x00, 0x00]), Err(Error::Length));
        assert_eq!(decode_command(&[0; 5]), Err(Error::Length));
        assert_eq!(decode_status(&[0; 7]), Err(Error::Length));
    }

    #[test]
    fn alpha_above_off_is_rejected_even_with_a_good_crc() {
        let mut frame = [0x01, 0x46, 0x51, 0];
        frame[3] = crc8(&frame[..3]);
        assert_eq!(decode_command(&frame), Err(Error::Range));
    }

    #[test]
    fn unknown_command_is_rejected_even_with_a_good_crc() {
        let mut frame = [0x7F, 0x00, 0x00, 0];
        frame[3] = crc8(&frame[..3]);
        assert_eq!(decode_command(&frame), Err(Error::Unknown));
    }

    #[test]
    fn status_frame_is_pinned_and_round_trips() {
        let status = Status {
            flags: flags::MAINS | flags::LOCKED,
            alpha_applied: 9_000,
            freq_centi_hz: 5_000,
            bad_frames: 5,
        };
        let frame = encode_status(&status);
        assert_eq!(frame, [0xD1, 0x03, 0x23, 0x28, 0x13, 0x88, 0x05, 0x5A]);
        assert_eq!(decode_status(&frame), Ok(status));
    }

    #[test]
    fn status_with_a_bad_magic_is_rejected() {
        let mut frame = encode_status(&Status {
            flags: 0,
            alpha_applied: APPLIED_NONE,
            freq_centi_hz: 0,
            bad_frames: 0,
        });
        frame[0] = 0xD2;
        frame[7] = crc8(&frame[..7]);
        assert_eq!(decode_status(&frame), Err(Error::Unknown));
    }

    #[test]
    fn alpha_maps_to_the_half_period_fraction() {
        assert_eq!(alpha_to_fraction(0), FRACTION_FULL);
        assert_eq!(alpha_to_fraction(9_000), 32_768);
        assert_eq!(alpha_to_fraction(17_999), 65_532);
    }

    #[test]
    fn off_is_never_a_firing_fraction() {
        assert_eq!(alpha_to_fraction(ALPHA_OFF), FRACTION_OFF);
        assert_eq!(alpha_to_fraction(u16::MAX), FRACTION_OFF);
    }

    #[test]
    fn only_alpha_zero_is_full_on() {
        for alpha in 1..ALPHA_OFF {
            assert_ne!(alpha_to_fraction(alpha), FRACTION_FULL, "alpha {alpha}");
        }
    }
}
