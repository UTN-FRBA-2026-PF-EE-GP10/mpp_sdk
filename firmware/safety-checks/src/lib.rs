//! Pure, dependency-free safety-cutoff arithmetic shared with
//! `mpp-firmware`'s curve tracer (`mode_curve_tracer.rs`). Extracted into
//! its own crate so it can be unit-tested with plain `cargo test`: the
//! firmware crate is `#![no_std]`/`#![no_main]`, forces the
//! `thumbv6m-none-eabi` target via its own `.cargo/config.toml`, and pulls
//! in ARM-only dependencies (`embassy-rp`, `cortex-m`) - none of which can
//! build for a host test target. This crate has none of those
//! constraints, so it defaults to the host target and supports `cargo
//! test` normally. `#![no_std]` is still asserted for non-test builds so
//! it stays safe to depend on from the `no_std` firmware crate.
#![cfg_attr(not(test), no_std)]

/// Safety cutoff: current. Bench-chosen envelope for the tracer load
/// (~23 V x 0.7 A), below the INA229's own 1 A full scale
/// (`ina229::I_MAX_MA`) so the sensor can still resolve a breach rather
/// than saturating at it.
pub const TRACER_I_MAX_MA: u16 = 700;

/// Safety cutoff: power, in milliwatts - the 23 V x 0.7 A envelope above.
///
/// This is dissipated **linearly in Q3** (TO-220, see
/// `mode_curve_tracer.rs`'s `TRACER_PWM_MAX`), not in a resistor, and a
/// sweep's worst case is the panel's own MPP since that is where V*I
/// peaks. Two panels in series at full sun is ~20 W
/// (`docs/general_information.md`), so this bounds the sweep below what
/// the array can deliver. Tolerable because a sweep is seconds, not
/// continuous - the ESP32-C3 reference device's `LESSONS.md` flags MOSFET
/// heating during repeated sweeps as a real effect on its own
/// (unheatsinked) build, so back-to-back sweeps at this limit want a
/// heatsink on Q3 and an eye on how hot it gets.
pub const TRACER_P_MAX_MW: u32 = 16_100;

/// True if `(v_mv, i_ma)` breaches either cutoff above. Moved here
/// verbatim from `CurveTracer::breach` - no behavior change, extraction
/// only.
pub fn breach(v_mv: u16, i_ma: u16) -> bool {
    let p_mw = v_mv as u32 * i_ma as u32 / 1000;
    i_ma > TRACER_I_MAX_MA || p_mw > TRACER_P_MAX_MW
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn under_both_thresholds_does_not_breach() {
        assert!(!breach(20_000, 500));
    }

    #[test]
    fn current_at_threshold_does_not_breach() {
        assert!(!breach(1_000, TRACER_I_MAX_MA));
    }

    #[test]
    fn current_just_over_threshold_breaches() {
        assert!(breach(1_000, TRACER_I_MAX_MA + 1));
    }

    #[test]
    fn power_at_threshold_does_not_breach() {
        // v_mv * i_ma / 1000 == TRACER_P_MAX_MW exactly, current alone
        // under its own limit.
        let i_ma = 500u16;
        let v_mv = 32_200u16;
        assert_eq!(v_mv as u32 * i_ma as u32 / 1000, TRACER_P_MAX_MW);
        assert!(!breach(v_mv, i_ma));
    }

    #[test]
    fn power_just_over_threshold_breaches_even_under_current_limit() {
        // 32_201 mV still truncates to exactly 16_100 mW, so use 32_202
        // to cross the integer-arithmetic boundary by one reported mW.
        let i_ma = 500u16;
        let v_mv = 32_202u16;
        assert!(v_mv as u32 * i_ma as u32 / 1000 > TRACER_P_MAX_MW);
        assert!(i_ma <= TRACER_I_MAX_MA);
        assert!(breach(v_mv, i_ma));
    }

    #[test]
    fn zero_current_never_breaches() {
        assert!(!breach(u16::MAX, 0));
    }

    #[test]
    fn max_inputs_do_not_overflow() {
        // v_mv and i_ma are both u16; the u32 intermediate product must
        // not overflow (65535 * 65535 fits in u32, but this pins that
        // assumption so a future type change gets caught here).
        let _ = breach(u16::MAX, u16::MAX);
    }
}
