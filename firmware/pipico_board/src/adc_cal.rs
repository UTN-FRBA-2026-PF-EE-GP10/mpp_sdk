//! On-chip ADC calibration: one straight line from raw code to pin voltage.
//!
//! Measured on the bench against the INA229, which reads the same input
//! node as `ADC_PWR` (through the shunt and the relay's resting contact,
//! no diode between). Points from 0.5 V to 18 V on the input, `Low` divider
//! range, least-squares fit on the raw codes:
//!
//! ```text
//! pin voltage = 0.79322 mV * (code - 13.19)
//! ```
//!
//! The offset (about 13 codes, ~90 mV at the terminals on `Low`) was the
//! main error: the uncorrected reading was 16 % high at 0.5 V and showed
//! ~90 mV on `ADC_VOUT` with 0 V on the output. The line leaves at most
//! ~40 mV of error, near 4 V, where the RP2040-E11 DNL spike at code 512
//! bends the curve. That is not corrected: the INA229 stays the reference
//! for the algorithm.
//!
//! `ADC_VOUT` uses the same line: with a battery on the output, it gave the
//! same raw code as `ADC_PWR` at the same voltage (596.6 against 596.7 at
//! 3.974 V).
//!
//! This line describes the RP2040's own ADC, not the divider ahead of it.
//! Changing the divider range (jumpers + `ADC_DIVIDER_RANGE` in `main.rs`,
//! see `docs/hardware_v1/calibration.md`) does not move this fit: the gain
//! and zero stay valid. Redo this fit only on a different board, or after
//! changing the Pico.

/// Pin voltage per raw code, in microvolts x 100 (793.22 uV).
const UV_X100_PER_CODE: u64 = 79_322;

/// Raw code at 0 V on the pin, x 100 (13.19 codes).
const ZERO_CODE_X100: u64 = 1_319;

/// Converts a raw 12-bit ADC code to the voltage at the ADC pin, in mV.
/// Codes at or below the zero point read 0.
pub fn raw_to_pin_mv(raw: u16) -> u16 {
    let above_zero_x100 = (raw as u64 * 100).saturating_sub(ZERO_CODE_X100);
    // x100 codes * (uV x100 per code) = uV x 10_000; / 10_000_000 = mV.
    (above_zero_x100 * UV_X100_PER_CODE / 10_000_000) as u16
}

/// Divider ratios (terminal mV per pin mV, x100), one per jumper range.
///
/// These come from the nominal resistor values on the divider
/// (`firmware/pipico_board/README.md`'s range table): `(R_top + R_bottom) /
/// R_bottom`, e.g. Low is `(75k + 10k) / 10k = 8.50`. They are separate
/// from `raw_to_pin_mv` above: the divider sits ahead of the ADC pin and is
/// a different part of the signal chain from the RP2040's own gain/zero.
///
/// The two-point check in `docs/hardware_v1/calibration.md` ("Changing the
/// ADC range") measures the real ratio against a meter. If it is off by
/// more than about 1% (1% resistor tolerance, stacked over three
/// resistors, can do that), replace the nominal value here with the
/// measured one - never adjust `UV_X100_PER_CODE`/`ZERO_CODE_X100` above to
/// compensate for a divider error.
pub const RATIO_LOW_X100: u32 = 850; // 1x 75k + 10k
pub const RATIO_MID_X100: u32 = 1_600; // 2x 75k + 10k
pub const RATIO_FULL_X100: u32 = 2_350; // 3x 75k + 10k

/// Applies the jumper-selected divider ratio to a pin-mV reading
/// (`raw_to_pin_mv`'s output), giving the voltage at the panel/output
/// terminals. Saturates instead of wrapping: on `Full`, terminal readings
/// above ~65.5 V (still within that range's ~75.6 V full scale) would
/// otherwise overflow u16 silently.
pub fn divider_to_actual_mv(range: crate::AdcDividerRange, pin_mv: u16) -> u16 {
    let ratio_x100 = match range {
        crate::AdcDividerRange::Full => RATIO_FULL_X100,
        crate::AdcDividerRange::Mid => RATIO_MID_X100,
        crate::AdcDividerRange::Low => RATIO_LOW_X100,
    };
    let mv = pin_mv as u32 * ratio_x100 / 100;
    mv.min(u16::MAX as u32) as u16
}
