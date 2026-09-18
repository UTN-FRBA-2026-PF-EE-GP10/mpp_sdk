//! RP2040 ADC DNL correction (RP2040-E11).
//!
//! The RP2040's on-chip 12-bit SAR ADC has mismatched capacitors in its
//! DAC. The errata (RP2040-E11) lists four unusually wide codes (DNL
//! spikes): 512, 1536, 2560 and 3584. Every code above a spike reads low
//! by that spike's excess width.
//!
//! `dnl_fix` linearizes the raw reading by adding back the excess width
//! of every spike below it.

/// The four spike codes from RP2040-E11, with each one's excess width in
/// LSBs. The widths are nominal estimates, not measured on this board's
/// die: a sweep of a known ramp into the ADC would pin them down. The
/// codes themselves are fixed by the silicon.
const DNL_SPIKES: [(u16, u16); 4] = [(512, 4), (1536, 5), (2560, 5), (3584, 3)];

/// Full-scale code after DNL correction (4095 + every spike's width).
pub const CORRECTED_FULL_SCALE: u32 = {
    let mut total = 4095u32;
    let mut i = 0;
    while i < DNL_SPIKES.len() {
        total += DNL_SPIKES[i].1 as u32;
        i += 1;
    }
    total
};

/// Corrects the RP2040-E11 DNL spike error on a raw 12-bit ADC reading.
///
/// - `raw`: raw ADC sample in 0..4095.
/// - Returns: linearized code in 0..`CORRECTED_FULL_SCALE`.
///
/// Strictly monotonic: `dnl_fix(raw + 1) > dnl_fix(raw)`.
#[inline]
pub fn dnl_fix(raw: u16) -> u16 {
    let raw = raw.min(4095);
    let mut corrected = raw;
    for &(code, width) in DNL_SPIKES.iter() {
        if raw > code {
            corrected += width;
        } else if raw == code {
            // A reading on a spike code could be anywhere inside the wide
            // step - place it at the center.
            corrected += width / 2;
        }
    }
    corrected
}
