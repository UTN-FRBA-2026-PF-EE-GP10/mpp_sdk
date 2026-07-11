//! Driver for the Texas Instruments INA229 20-bit SPI power monitor.
//!
//! Measures the panel-side bus voltage (`VBUS`) and shunt current
//! (`CURRENT`) feeding the SEPIC input - the `(V, I)` pair the Pi-side
//! `SpiMcuSource` forwards to the MPPT algorithm.
//!
//! Register map, SPI frame format and scaling constants below were checked
//! against the INA229 datasheet (SLYS023A, Rev. A, May 2022):
//! <https://www.ti.com/lit/ds/symlink/ina229.pdf>. One correction versus the
//! plan this driver was built from: the SPI mode. See "SPI frame" below.
//!
//! ## SPI frame
//!
//! Every transaction starts with a command byte: `ADDR[5:0]` in bits 7:2, a
//! fixed `0` in bit 1, and R/!W in bit 0 (`1` = read, `0` = write) - datasheet
//! Table 7-2. Write frames are always 16 data bits; read frames are
//! register-size (16, 24 or 40 bits).
//!
//! Clock idles low (CPOL = 0). The device samples MOSI on the SCLK *falling*
//! edge and shifts MISO out on the *rising* edge (datasheet Section 7.5.1),
//! which is **SPI mode 1** (`Phase::CaptureOnSecondTransition`) - not mode 0.
//!
//! ## Bus ownership
//!
//! SPI transactions here are a handful of bytes at 1 MHz (tens of
//! microseconds). Rather than pull in DMA channels + interrupt bindings for
//! negligible benefit, this driver uses the RP2040's blocking SPI0
//! peripheral (`Spi<'_, SPI0, Blocking>`) directly from the async
//! `ina_task` in `main.rs`, which owns the bus and one `Output` per chip
//! select exclusively (no shared-bus crate, per `AGENTS.md`).

use embassy_rp::gpio::Output;
use embassy_rp::peripherals::SPI0;
use embassy_rp::spi::{Blocking, Spi};

/// Register addresses used by this driver (datasheet Table 7-3).
mod reg {
    pub const ADC_CONFIG: u8 = 0x01;
    pub const SHUNT_CAL: u8 = 0x02;
    pub const VBUS: u8 = 0x05;
    pub const CURRENT: u8 = 0x07;
    pub const MANUFACTURER_ID: u8 = 0x3E;
}

/// `MANUFACTURER_ID` reset value: ASCII "TI" (datasheet Table 7-23).
const MANUFACTURER_ID_TI: u16 = 0x5449;

/// `ADC_CONFIG` value written at init: continuous bus + shunt voltage
/// conversion (`MODE` = 0xB), conversion time and averaging left at the
/// datasheet reset defaults (`VBUSCT`/`VSHCT`/`VTCT` = 5h = 1052 us, `AVG` =
/// 0h = 1x). Temperature conversion is left out of the MODE field; this
/// driver does not read `DIETEMP` (external PT100 temperature sensing via
/// MAX31865 is separate, future work - see `firmware/README.md`).
const ADC_CONFIG_CONTINUOUS_VI: u16 = 0xBB68;

/// Board shunt resistor value, in milliohms. Not on the schematic (the
/// `Device:R_US` symbol carries a generic placeholder value) - given
/// directly by the operator. See `firmware/README.md` "Sensing" section.
pub const R_SHUNT_MOHM: u32 = 10;

/// Maximum expected string current, in milliamps (`harness/panel_config.py`
/// `I_MAX = 1.0` A).
pub const I_MAX_MA: u32 = 1000;

/// `SHUNT_CAL` register value for `ADCRANGE = 0` (datasheet Equation 2 and
/// 3, Section 8.1.2):
///
/// ```text
/// CURRENT_LSB = I_MAX / 2^19
/// SHUNT_CAL   = 13107.2e6 * CURRENT_LSB * R_SHUNT
/// ```
///
/// Substituting `I_MAX_MA` (mA) and `R_SHUNT_MOHM` (mOhm) and simplifying
/// (`13107.2e6 == 2^17 * 1e5`, and `2^17 / 2^19 == 1/4`) collapses to an
/// exact integer, no floats required:
///
/// ```text
/// SHUNT_CAL = I_MAX_MA * R_SHUNT_MOHM / 40
/// ```
///
/// Worked example at `I_MAX_MA = 1000`, `R_SHUNT_MOHM = 10`:
/// `SHUNT_CAL = 1000 * 10 / 40 = 250`.
const fn shunt_cal(i_max_ma: u32, r_shunt_mohm: u32) -> u16 {
    ((i_max_ma as u64 * r_shunt_mohm as u64) / 40) as u16
}

/// Driver errors.
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum Error {
    /// The SPI peripheral reported an error.
    Spi,
    /// `MANUFACTURER_ID` did not read back `"TI"` (0x5449) - wrong wiring,
    /// or the device is unpowered/not present.
    WrongManufacturerId(u16),
}

impl From<embassy_rp::spi::Error> for Error {
    fn from(_: embassy_rp::spi::Error) -> Self {
        Error::Spi
    }
}

/// Sign-extend a 20-bit two's-complement value out of a 24-bit register.
///
/// `VSHUNT`/`VBUS`/`CURRENT` are 24-bit registers, left-justified: the
/// signed 20-bit value sits in bits 23:4, bits 3:0 always read 0 (datasheet
/// Tables 7-9, 7-10, 7-12). Shift right 4 to normalize, then sign-extend
/// from bit 19 via a shift-left/arithmetic-shift-right round trip through a
/// 32-bit signed int.
fn sign_extend_20(raw24: u32) -> i32 {
    let v20 = ((raw24 >> 4) & 0x000F_FFFF) as i32;
    (v20 << 12) >> 12
}

/// Convert a raw `VBUS` register value to millivolts, saturating.
///
/// `VBUS` LSB = 195.3125 uV = 25/128 mV exactly (datasheet Table 7-10).
/// Worked example: `raw = 204_800 << 4` (i.e. the register's bits 23:4 hold
/// `204_800`) -> `204_800 * 25 / 128 = 40_000` mV = 40 V.
fn vbus_raw_to_mv(raw24: u32) -> u16 {
    let counts = sign_extend_20(raw24) as i64;
    let mv = (counts * 25 + 64) / 128; // +64 rounds to nearest instead of truncating
    mv.clamp(0, u16::MAX as i64) as u16
}

/// Convert a raw `CURRENT` register value to milliamps, saturating negative
/// (reverse-flow) readings to 0.
///
/// `CURRENT_LSB = I_MAX_MA / 2^19` (datasheet Equation 3). Worked example at
/// `I_MAX_MA = 1000`: register counts `262_144` (= 2^19 / 2, half of
/// full-scale) -> `1000 * 262_144 / 524_288 = 500` mA.
fn current_raw_to_ma(raw24: u32, i_max_ma: u32) -> u16 {
    let counts = sign_extend_20(raw24) as i64;
    let ma = (counts * i_max_ma as i64) / (1 << 19);
    ma.clamp(0, u16::MAX as i64) as u16
}

/// TI INA229 driver over the RP2040's blocking SPI0 peripheral.
pub struct Ina229 {
    i_max_ma: u32,
}

impl Ina229 {
    pub const fn new() -> Self {
        Self { i_max_ma: I_MAX_MA }
    }

    fn write_reg(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
        value: u16,
    ) -> Result<(), Error> {
        let cmd = [addr << 2, (value >> 8) as u8, value as u8];
        cs.set_low();
        let result = spi.blocking_write(&cmd);
        cs.set_high();
        result.map_err(Error::from)
    }

    /// Read a register whose contents occupy `out.len()` bytes (MSB first).
    fn read_reg(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
        out: &mut [u8],
    ) -> Result<(), Error> {
        debug_assert!(
            out.len() <= 4,
            "no INA229 register used here exceeds 24 bits"
        );
        let cmd = (addr << 2) | 0b01;
        let mut rx = [0u8; 5]; // command byte echo + up to 4 data bytes
        let n = out.len();
        cs.set_low();
        let result = spi.blocking_transfer(&mut rx[..1 + n], &[cmd]);
        cs.set_high();
        result?;
        out.copy_from_slice(&rx[1..1 + n]);
        Ok(())
    }

    fn read_reg16(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
    ) -> Result<u16, Error> {
        let mut buf = [0u8; 2];
        self.read_reg(spi, cs, addr, &mut buf)?;
        Ok(u16::from_be_bytes(buf))
    }

    fn read_reg24(
        &self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
        addr: u8,
    ) -> Result<u32, Error> {
        let mut buf = [0u8; 3];
        self.read_reg(spi, cs, addr, &mut buf)?;
        Ok(u32::from_be_bytes([0, buf[0], buf[1], buf[2]]))
    }

    /// ID check + `ADC_CONFIG` + `SHUNT_CAL`. Call once at boot, and retry
    /// with backoff on failure - a wiring/power fault here must not panic,
    /// the Pi link should keep running and report zeros.
    pub fn init(
        &mut self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
    ) -> Result<(), Error> {
        let id = self.read_reg16(spi, cs, reg::MANUFACTURER_ID)?;
        if id != MANUFACTURER_ID_TI {
            return Err(Error::WrongManufacturerId(id));
        }
        self.write_reg(spi, cs, reg::ADC_CONFIG, ADC_CONFIG_CONTINUOUS_VI)?;
        self.write_reg(
            spi,
            cs,
            reg::SHUNT_CAL,
            shunt_cal(self.i_max_ma, R_SHUNT_MOHM),
        )?;
        Ok(())
    }

    /// Read `VBUS`, converted to millivolts (saturating).
    pub fn read_vbus_mv(
        &mut self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
    ) -> Result<u16, Error> {
        let raw = self.read_reg24(spi, cs, reg::VBUS)?;
        Ok(vbus_raw_to_mv(raw))
    }

    /// Read `CURRENT`, converted to milliamps (saturating negative to 0).
    pub fn read_current_ma(
        &mut self,
        spi: &mut Spi<'_, SPI0, Blocking>,
        cs: &mut Output<'_>,
    ) -> Result<u16, Error> {
        let raw = self.read_reg24(spi, cs, reg::CURRENT)?;
        Ok(current_raw_to_ma(raw, self.i_max_ma))
    }
}

impl Default for Ina229 {
    fn default() -> Self {
        Self::new()
    }
}
