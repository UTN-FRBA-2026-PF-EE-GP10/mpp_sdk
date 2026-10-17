# Dual-Board Compatibility Guide: Raspberry Pi 5 & BeagleBone Black

This document details the cross-platform changes implemented in `mpp-sdk` to ensure seamless,
single-codebase operation on both the **Raspberry Pi 5** and the **BeagleBone Black (BBB)**
without maintaining separate branches or modifying code when swapping hardware.

---

## 1. Summary of Architectural Differences

| Feature | Raspberry Pi 5 | BeagleBone Black (Rev C) | How It Is Handled |
| :--- | :--- | :--- | :--- |
| **Architecture** | 64-bit ARM (`aarch64`) | 32-bit ARM (`armv7l`) | Standard Python / pure POSIX paths |
| **Default Linux Distribution** | Raspberry Pi OS (Bookworm / Trixie) | Debian 13 (Trixie) IoT | uv installs Python 3.14 on both |
| **SPI Interface File** | `/dev/spidev0.0` (SPI0 CE0) | `/dev/spidev1.0` (SPI1 CS0) | Board model check at startup |
| **Default SPI Bus Index** | `bus = 0` | `bus = 1` | `1` when `/proc/device-tree/model` names a BeagleBone, else `0` |
| **Logic Levels** | 3.3 V CMOS | 3.3 V CMOS | Direct pin-to-pin wiring to RP2040 Pico (no shifter) |
| **RP2040 Firmware** | Unchanged | Unchanged | Same SPI slave protocol (12-byte frame + CRC-8) |

---

## 2. What changes per board

- **SPI bus.** `scripts/curve_tracer_server.py` and `scripts/spi_test.py`
  read `/proc/device-tree/model`. A BeagleBone uses bus 1, all other
  boards use bus 0. `--spi-bus` (server) or `--bus` (`spi_test.py`)
  overrides it.
- **Python.** Both boards run Python 3.14, installed by uv. The Debian 13
  system Python (3.13) is not supported.
- **204 routes.** The server routes that return `204 No Content` return an
  explicit empty `Response`. This works on all FastAPI versions.
- **Firmware.** No change. The SPI protocol is the same on both boards.

---

## 3. Hardware Wiring Reference

The host SPI pins connect to the RP2040 Pico (acting as SPI slave) using 3.3V logic on both boards:

```text
Raspberry Pi 5 (GPIO Header)       RP2040 Pico (Slave)      BeagleBone Black (P9 Header)
─────────────────────────────      ───────────────────      ────────────────────────────
GPIO 11 (SPI0_SCLK)          ──►   GPIO 14 (SCK)       ◄──  P9.31 (SPI1_SCLK)
GPIO 9  (SPI0_MISO)          ◄──   GPIO 11 (TX/MISO)   ──►  P9.29 (SPI1_D0 / MISO)
GPIO 10 (SPI0_MOSI)          ──►   GPIO 12 (RX/MOSI)   ◄──  P9.30 (SPI1_D1 / MOSI)
GPIO 8  (SPI0_CE0)           ──►   GPIO 13 (CSn)       ◄──  P9.28 (SPI1_CS0)
GND                          ───   GND                 ───  P9.1 or P9.2 (GND)
```

---

## 4. Verification

- `uv run pytest` passes on both boards.
- Both boards run `scripts/spi_test.py` and the curve-tracer server
  (with or without `--demo`).

---

## 5. Related Setup Guides

- [BeagleBone Black Setup Guide](beaglebone_setup_guide.md): Complete step-by-step flashing,
  Debian 13 IoT OS setup, SPI1 overlay activation, and SDK installation for the BBB.
- RP2040 firmware and host SPI bring-up: `firmware/pipico_board/README.md`. Details on flashing
  firmware, SPI slave protocol, and Raspberry Pi pinouts.
