# Dual-Board Compatibility Guide: Raspberry Pi 5 & BeagleBone Black

This document details the cross-platform changes implemented in `mpp-sdk` to ensure seamless, single-codebase operation on both the **Raspberry Pi 5** and the **BeagleBone Black (BBB)** without maintaining separate branches or modifying code when swapping hardware.

---

## 1. Summary of Architectural Differences

| Feature | Raspberry Pi 5 | BeagleBone Black (Rev C) | How It Is Handled |
| :--- | :--- | :--- | :--- |
| **Architecture** | 64-bit ARM (`aarch64`) | 32-bit ARM (`armv7l`) | Standard Python / pure POSIX paths |
| **Default Linux Distribution** | Raspberry Pi OS (Bookworm / Trixie) | Debian 13 (Trixie) IoT | `pyproject.toml` supports `Python >= 3.13` |
| **SPI Interface File** | `/dev/spidev0.0` (SPI0 CE0) | `/dev/spidev1.0` (SPI1 CS0) | Dynamic runtime device detection |
| **Default SPI Bus Index** | `bus = 0` | `bus = 1` | `1 if not exists(/dev/spidev0.0) and exists(/dev/spidev1.0) else 0` |
| **Logic Levels** | 3.3 V CMOS | 3.3 V CMOS | Direct pin-to-pin wiring to RP2040 Pico (no shifter) |
| **RP2040 Firmware** | Unchanged | Unchanged | Same SPI slave protocol (12-byte frame + CRC-8) |

---

## 2. File-by-File Changes & Explanations

### A. Automatic SPI Bus Selection in `scripts/curve_tracer_server.py`

#### What was changed:
```python
# scripts/curve_tracer_server.py (Lines 105-106)

# Auto-detect default SPI bus: BBB uses SPI1 (bus=1), RPi uses SPI0 (bus=0).
_DEFAULT_SPI_BUS = 1 if not Path("/dev/spidev0.0").exists() and Path("/dev/spidev1.0").exists() else 0
```
And in `main()` CLI argument parsing:
```python
parser.add_argument("--spi-bus", type=int, default=_DEFAULT_SPI_BUS, help=f"SPI bus (default: {_DEFAULT_SPI_BUS})")
```

#### How it works on both boards:
1. **On Raspberry Pi 5**: 
   - Linux exposes `/dev/spidev0.0`.
   - `Path("/dev/spidev0.0").exists()` evaluates to `True`.
   - `_DEFAULT_SPI_BUS` resolves to `0`.
2. **On BeagleBone Black**: 
   - SPI1 is mapped to `/dev/spidev1.0` via device tree overlay (`BB-SPIDEV1-00A0.dtbo`). `/dev/spidev0.0` does not exist.
   - `Path("/dev/spidev0.0").exists()` is `False`, and `Path("/dev/spidev1.0").exists()` is `True`.
   - `_DEFAULT_SPI_BUS` automatically resolves to `1`.
3. **Manual Override**: If a custom SPI configuration or another bus is used, the CLI option `--spi-bus <N>` still takes precedence over the default.

---

### B. Automatic SPI Bus Selection in `scripts/spi_test.py`

#### What was changed:
```python
# scripts/spi_test.py (Lines 17-18)

# Auto-detect default bus: BeagleBone Black uses SPI1 (bus=1), RPi uses SPI0 (bus=0).
DEFAULT_BUS = 1 if not os.path.exists("/dev/spidev0.0") and os.path.exists("/dev/spidev1.0") else 0
DEFAULT_DEVICE = 0
```
CLI arguments:
```python
parser.add_argument("--bus", type=int, default=DEFAULT_BUS, help=f"SPI bus (default: {DEFAULT_BUS})")
parser.add_argument("--device", type=int, default=DEFAULT_DEVICE, help=f"SPI device (default: {DEFAULT_DEVICE})")
```

#### How it works:
Running `python scripts/spi_test.py --once` without extra flags will connect to bus 0 on Raspberry Pi and bus 1 on BeagleBone Black automatically.

---

### C. FastAPI Status 204 Route Compliance in `scripts/curve_tracer_server.py`

#### What was changed:
Imported `Response` from `fastapi`:
```python
from fastapi import FastAPI, HTTPException, Response
```

Updated all routes declaring `status_code=204` (`/api/curves/{id}`, `/api/panels/{id}`, `/api/sessions/{id}`, `/api/runs/{id}`, `/api/runs/stop`, `/api/start-sweep`, `/api/start-demo-sweep`, `/api/release-relay`):
```python
# Example: DELETE /api/curves/{curve_id}
@app.delete("/api/curves/{curve_id}", status_code=204, response_class=Response)
def delete_curve(curve_id: str) -> Response:
    curve_library.delete(_curve_path(curve_id))
    return Response(status_code=204)
```

#### Why this is required & how it works on both boards:
- In HTTP RFC specifications, an HTTP `204 No Content` response must never have a message body.
- FastAPI versions validate route signatures. If a function returns `None` without explicitly specifying `response_class=Response` or having an explicit return type of `Response`, FastAPI attempts to generate a JSON response body containing `null`, triggering:
  `AssertionError: Status code 204 must not have a response body`
- Setting `response_class=Response` and returning `Response(status_code=204)` adheres strictly to the standard and works consistently across FastAPI releases (both the pip/uv version installed on the RPi/PC and Debian 13's system `python3-fastapi` on the BBB).

---

### D. Python 3.13 / 3.14 Compatibility in `pyproject.toml` and `mpp_sdk/models/measured.py`

#### What was changed:
1. **`pyproject.toml`**:
   ```toml
   requires-python = ">=3.13"
   ```
   *Rationale*: Debian 13 (Trixie) on BeagleBone Black includes Python 3.13.5 in apt repositories. Lowering the minimum version requirement from `>=3.14` to `>=3.13` allows the SDK to install smoothly on Debian 13 while remaining fully compatible with Python 3.14+ on the Raspberry Pi and PC.

2. **`mpp_sdk/models/measured.py`**:
   ```python
   from __future__ import annotations
   ```
   *Rationale*: Postpones evaluation of type annotations, ensuring PEP 604 union types (`TypeA | TypeB`) evaluate cleanly under Python 3.13 runtimes.

---

### E. Python Multi-Exception Syntax Fix in `mpp_sdk/panels/library.py`

#### What was changed:
```python
# Line 193
# Before:
except OSError, ValueError, KeyError, TypeError:

# After:
except (OSError, ValueError, KeyError, TypeError):
```

#### Why:
In Python 3, multiple exceptions caught in a single `except` statement must be enclosed in parentheses as a tuple. Without parentheses, Python 3 treats subsequent identifiers as invalid syntax. This bugfix ensures compatibility across all Python 3 implementations.

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

## 4. Verification and Validation

All 683 project unit tests run and pass without regressions:
```bash
uv run pytest tests/
# Result: 683 passed, 7 skipped, 1 warning in 16.23s
```

Both boards can execute:
- Direct SPI communications via `python scripts/spi_test.py`
- Curve tracer backend & web workbench via `python scripts/curve_tracer_server.py` (with or without `--demo`)

---

## 5. Related Setup Guides

- [BeagleBone Black Setup Guide](beaglebone_setup_guide.md): Complete step-by-step flashing, Debian 13 IoT OS setup, SPI1 overlay activation, and SDK installation for the BBB.
- [RP2040 Firmware & Host SPI Bringup](../firmware/pipico_board/README.md): Details on flashing firmware, SPI slave protocol, and Raspberry Pi pinouts.
