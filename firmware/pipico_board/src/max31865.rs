//! Driver for the Maxim/Analog MAX31865 PT100 RTD-to-digital converter.
//!
//! Measures the panel temperature through the board's PT100 probe - context
//! data for the thesis measurements (panel temperature moves the MPP), not
//! part of the MPPT control loop. The reading is published in a shared
//! atomic and logged over defmt; it is deliberately NOT added to the
//! 12-byte Pi SPI frame, whose layout is a frozen contract with
//! `mpp_sdk/io/spi_mcu.py`.
//!
//! Register map and conversion math follow the MAX31865 datasheet
//! (19-7491; Rev 3; 2015):
//! <https://www.analog.com/media/en/technical-documentation/data-sheets/MAX31865.pdf>
//! Board specifics (from `hardware/untitled.kicad_sch`, the sensing sheet):
//! `R_REF = 400 Ohm 0.1%`, plus a 2/3-wire selector jumper - this driver
//! defaults to 2-wire (`THREE_WIRE = false`); flip that constant if the
//! jumper is set for 3-wire.
//!
//! ## SPI frame
//!
//! Address byte first, then data; read addresses are 0x00-0x07 and the
//! matching write addresses are `addr | 0x80`. Multi-byte reads
//! auto-increment the address. The device supports SPI modes 1 and 3
//! (datasheet "Serial Interface" section), so it shares SPI0's mode-1
//! configuration with the INA229 unchanged.
//!
//! ## Bus ownership
//!
//! Same model as `ina229.rs`: the async `sensors_task` in `main.rs` owns
//! the blocking SPI0 bus exclusively and drives each device's chip select
//! manually (INA229 on GPIO17, this device on GPIO20).

use embassy_rp::gpio::Output;
use embassy_rp::peripherals::SPI0;
use embassy_rp::spi::{Blocking, Spi};

/// Register addresses used by this driver (datasheet Table 1).
mod reg {
    pub const CONFIG: u8 = 0x00;
    /// RTD MSB; LSB (0x02) is read in the same transfer via auto-increment.
    pub const RTD_MSB: u8 = 0x01;
    pub const FAULT_STATUS: u8 = 0x07;
}

/// Write-address bit (datasheet Table 1: write addresses are 0x80-0x87).
const WRITE_BIT: u8 = 0x80;

/// Set for a 3-wire PT100 hookup (config bit 4). The board has a 2/3-wire
/// selector jumper on the sensing sheet; the probe is currently wired
/// 2-wire, which also covers 4-wire per the datasheet.
const THREE_WIRE: bool = false;

/// `CONFIG` bits (datasheet Table 2).
mod cfg {
    /// VBIAS on - required for conversions.
    pub const VBIAS: u8 = 0x80;
    /// Automatic conversion mode: free-running conversions at the filter
    /// rate (~50/60 Hz), no 1-shot triggering or DRDY handshake needed.
    pub const AUTO: u8 = 0x40;
    pub const THREE_WIRE: u8 = 0x10;
    /// Self-clearing: writing 1 clears the fault status register.
    pub const FAULT_CLEAR: u8 = 0x02;
    /// 50 Hz mains filter (Argentina) instead of 60 Hz.
    pub const FILTER_50HZ: u8 = 0x01;
}

/// Steady-state `CONFIG` contents: what a readback returns after init
/// (`FAULT_CLEAR` self-clears and is never read back as 1).
const CONFIG_RUNNING: u8 =
    cfg::VBIAS | cfg::AUTO | if THREE_WIRE { cfg::THREE_WIRE } else { 0 } | cfg::FILTER_50HZ;

/// Reference resistor on the board's RTD input, in milliohms
/// (`400R 0.1% 0805` on the sensing sheet).
pub const R_REF_MOHM: u32 = 400_000;

/// PT100 nominal resistance at 0 degC, in milliohms.
const R0_MOHM: i64 = 100_000;

/// PT100 mean slope over 0-100 degC, in milliohms per degC (IEC 60751
/// alpha = 0.00385: R goes from 100.00 to 138.51 Ohm over that span).
const SLOPE_MOHM_PER_C: i64 = 385;

/// Driver errors.
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Error {
    /// The SPI peripheral reported an error.
    Spi,
    /// `CONFIG` readback after init did not match what was written - wrong
    /// wiring, or the device is unpowered/not present. (The MAX31865 has no
    /// ID register; config readback is the standard presence check.)
    ConfigReadback(u8),
    /// The RTD fault bit was set; payload is the fault status register
    /// (datasheet Table 7: open probe, short, VBIAS issues...). The fault
    /// is cleared before returning so the next read can recover.
    Fault(u8),
}

impl From<embassy_rp::spi::Error> for Error {
    fn from(_: embassy_rp::spi::Error) -> Self {
        Error::Spi
    }
}

/// Convert a raw 15-bit RTD ratio reading to centi-degC, saturating to the
/// i16 range.
///
/// The ADC output is ratiometric: `R_rtd = adc / 2^15 * R_REF`. With
/// `R_REF = 400_000` mOhm, one count = ~12.2 mOhm = ~0.032 degC, so integer
/// centi-degC keeps more resolution than the sensor's accuracy class.
/// Temperature uses the linear PT100 approximation
/// `T = (R - R0) / 0.385 Ohm/degC`, good to ~ +/-0.4 degC over 0-100 degC
/// (the bench range); swap in Callendar-Van Dusen later if wider range or
/// tighter accuracy is ever needed.
///
/// Worked examples:
/// - `adc = 8192` -> `R = 8192 * 400_000 / 32768 = 100_000` mOhm
///   -> `(100_000 - 100_000) * 100 / 385 = 0` centi-degC = 0.00 degC.
/// - `adc = 11347` -> `R = 138_513` mOhm
///   -> `38_513 * 100 / 385 = 10_003` centi-degC = ~100.0 degC.
fn rtd_raw_to_centi_c(adc15: u16) -> i16 {
    let r_mohm = (adc15 as i64) * (R_REF_MOHM as i64) / 32768;
    let centi_c = (r_mohm - R0_MOHM) * 100 / SLOPE_MOHM_PER_C;
    centi_c.clamp(i16::MIN as i64, i16::MAX as i64) as i16
}

/// MAX31865 driver over the RP2040's blocking SPI0 peripheral.
pub struct Max31865;

impl Max31865 {
    pub const fn new() -> Self {
        Self
    }

    fn write_reg(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
        value: u8,
    ) -> Result<(), Error> {
        let frame = [addr | WRITE_BIT, value];
        cs.set_low();
        let result = spi.blocking_write(&frame);
        cs.set_high();
        result.map_err(Error::from)
    }

    /// Read `out.len()` consecutive registers starting at `addr` (the
    /// device auto-increments the address within one CS assertion).
    fn read_regs(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
        out: &mut [u8],
    ) -> Result<(), Error> {
        debug_assert!(out.len() <= 2, "no multi-read here exceeds 2 registers");
        let mut rx = [0u8; 3]; // address byte echo + up to 2 data bytes
        let n = out.len();
        cs.set_low();
        let result = spi.blocking_transfer(&mut rx[..1 + n], &[addr]);
        cs.set_high();
        result?;
        out.copy_from_slice(&rx[1..1 + n]);
        Ok(())
    }

    fn read_reg8(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
    ) -> Result<u8, Error> {
        let mut buf = [0u8; 1];
        self.read_regs(spi, cs, addr, &mut buf)?;
        Ok(buf[0])
    }

    /// Configure (VBIAS + auto conversion + 50 Hz filter, clearing any stale
    /// fault) and verify by readback. Call once at boot; on failure retry
    /// from the caller - same no-panic policy as the INA229.
    pub fn init(
        &mut self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
    ) -> Result<(), Error> {
        self.write_reg(spi, cs, reg::CONFIG, CONFIG_RUNNING | cfg::FAULT_CLEAR)?;
        let readback = self.read_reg8(spi, cs, reg::CONFIG)?;
        if readback != CONFIG_RUNNING {
            return Err(Error::ConfigReadback(readback));
        }
        Ok(())
    }

    /// Read the latest RTD conversion, converted to centi-degC.
    ///
    /// Bit 0 of the LSB is the fault flag; when set, the fault status
    /// register is fetched for the error payload and the fault is cleared
    /// so a transient (e.g. probe briefly disconnected) self-recovers.
    pub fn read_temp_centi_c(
        &mut self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
    ) -> Result<i16, Error> {
        let mut buf = [0u8; 2];
        self.read_regs(spi, cs, reg::RTD_MSB, &mut buf)?;
        let raw = u16::from_be_bytes(buf);
        if raw & 0x0001 != 0 {
            let status = self.read_reg8(spi, cs, reg::FAULT_STATUS)?;
            self.write_reg(spi, cs, reg::CONFIG, CONFIG_RUNNING | cfg::FAULT_CLEAR)?;
            return Err(Error::Fault(status));
        }
        Ok(rtd_raw_to_centi_c(raw >> 1))
    }
}

impl Default for Max31865 {
    fn default() -> Self {
        Self::new()
    }
}
