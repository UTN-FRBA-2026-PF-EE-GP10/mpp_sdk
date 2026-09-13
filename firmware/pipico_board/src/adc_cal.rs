//! RP2040 ADC calibration and DNL correction (RP2040-E11).
//!
//! The RP2040's on-chip 12-bit SAR ADC suffers from bit-weight mismatch in
//! its capacitive DAC at bit 9 transitions. This creates 7 deterministic,
//! unusually wide codes (DNL spikes) at multiples of 512:
//! 512, 1024, 1536, 2048, 2560, 3072, and 3584.
//!
//! `dnl_fix` linearizes the raw reading by taking into account the extra
//! width of these spike codes and the resulting cumulative offset.

/// Nominal excess width (in LSBs) of the DNL spike at each 512-code boundary:
/// indices 0..6 correspond to boundaries 512, 1024, 1536, 2048, 2560, 3072, 3584.
///
/// Typical RP2040 dies show ~3-8 LSB excess width at each boundary.
pub const DNL_SPIKE_WIDTHS: [u16; 7] = [
    4, // at 512
    4, // at 1024
    5, // at 1536
    6, // at 2048 (major MSB transition)
    5, // at 2560
    4, // at 3072
    3, // at 3584
];

/// Cumulative offset added to codes in each 512-code segment (0..7).
///
/// - Segment 0 (codes 0..511): offset 0
/// - Segment 1 (codes 512..1023): offset = spike[0]
/// - Segment k: offset = sum(spike[0..k])
pub const CUMULATIVE_OFFSETS: [u16; 8] = {
    let mut offsets = [0u16; 8];
    let mut sum = 0;
    let mut i = 0;
    while i < 7 {
        sum += DNL_SPIKE_WIDTHS[i];
        offsets[i + 1] = sum;
        i += 1;
    }
    offsets
};

/// Total excess LSBs across all 7 spikes.
pub const TOTAL_EXCESS_LSBS: u16 = CUMULATIVE_OFFSETS[7];

/// Full-scale equivalent code after DNL correction (4095 + total excess LSBs).
pub const CORRECTED_FULL_SCALE: u32 = 4095 + TOTAL_EXCESS_LSBS as u32;

/// Corrects the RP2040-E11 DNL spike error on a raw 12-bit ADC reading.
///
/// - `raw`: raw ADC sample in 0..4095.
/// - Returns: linearized code in 0..`CORRECTED_FULL_SCALE`.
///
/// Strictly monotonic: `dnl_fix(raw + 1) > dnl_fix(raw)`.
#[inline]
pub fn dnl_fix(raw: u16) -> u16 {
    let raw = raw.min(4095);
    let segment = (raw >> 9) as usize; // 0..7 (single-cycle shift on ARM Cortex-M0+)
    let offset_in_segment = raw & 0x1FF; // 0..511

    let base_corrected = raw + CUMULATIVE_OFFSETS[segment];

    // If sitting exactly on a spike code (raw == 512 * k for k > 0),
    // place the reading at the center of the wide code step.
    if segment > 0 && offset_in_segment == 0 {
        let spike_width = DNL_SPIKE_WIDTHS[segment - 1];
        base_corrected - (spike_width / 2)
    } else {
        base_corrected
    }
}
