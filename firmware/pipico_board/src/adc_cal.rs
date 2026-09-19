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
//! 3.974 V). Redo the fit after changing the divider range or the board:
//! the `ADC cal:` log line gives one point per second (raw code against the
//! INA229), and two supply voltages far apart are enough.

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
