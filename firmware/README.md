# mpp-firmware

Rust firmware for the Raspberry Pi Pico (RP2040) using [Embassy](https://embassy.dev/).

## Toolchain prerequisites

System packages (Debian/Ubuntu/Pop!_OS):

```sh
sudo apt install libudev-dev pkg-config
```

Rust tooling:

```sh
rustup target add thumbv6m-none-eabi
cargo install elf2uf2-rs probe-rs-tools
```

## Flashing — two options

### Option A: debug probe via a second Pico (recommended)

Gives you one-command flash + live defmt logs over RTT with no button holding.

#### 1. Flash debugprobe onto the probe Pico

Download `debugprobe_on_pico2.uf2` (for Pico 2 / RP2350) from:
<https://github.com/raspberrypi/debugprobe/releases/latest>

Hold **BOOTSEL** on the probe Pico while plugging it in,
then drag the UF2 onto the `RPI-RP2` disk.
It reboots as a CMSIS-DAP probe.

#### 2. Install udev rules (Linux, one-time)

```sh
curl -fsSL https://probe.rs/files/69-probe-rs.rules | sudo tee /etc/udev/rules.d/69-probe-rs.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG plugdev $USER
# log out and back in for the group change to take effect
```

#### 3. Wire probe to target

The target Pico exposes three SWD pads on the bottom edge (left → right when viewed
from the top with the USB connector facing up):

```text
[ SWCLK | GND | SWDIO ]
```

| Probe Pico 2W | Target RP2040 Pico  |
|---------------|---------------------|
| GPIO3 (SWDIO) | SWDIO (right pad)   |
| GPIO2 (SWDCLK)| SWCLK (left pad)    |
| GND           | GND   (middle pad)  |

Both boards can be powered from their own USB cables — no shared power wire needed.

##### RPi ↔ Pico SPI connection (HIL mode)

The Pico runs as **SPI1 slave**. Connect the Raspberry Pi 5 SPI0 master to the Pico SPI1 pins:

| RPi5 (SPI0 master) | RP2040 Pico (SPI1 slave) | GPIO   |
|--------------------|--------------------------|--------|
| MOSI (GPIO10)      | SPI1_TX / MOSI-in        | GPIO11 |
| MISO (GPIO9)       | SPI1_RX / MISO-out       | GPIO12 |
| SCLK (GPIO11)      | SPI1_SCK                 | GPIO10 |
| CE0  (GPIO8)       | SPI1_CS                  | GPIO13 |
| GND                | GND                      | —      |

#### 4. Flash and stream logs

The `.cargo/config.toml` runner is already set to `probe-rs run --chip RP2040`:

```sh
cargo run --release
```

defmt log output appears directly in the terminal.

---

### Option B: BOOTSEL / mass-storage (no probe required)

Temporarily switch the runner in `.cargo/config.toml`:

```toml
runner = "elf2uf2-rs deploy"
```

Then:

1. Hold **BOOTSEL** on the target Pico while plugging it into USB.
it mounts as `RPI-RP2`.
2. Run:

```sh
cargo run --release
```

The UF2 is copied to the disk and the Pico reboots automatically.
No log output is available in this mode (RTT requires a probe connection).

## Build only

```sh
cargo build --release
```

## What it does

Default `src/main.rs` blinks the on-board LED on `PIN_25` and emits defmt log lines
over RTT.

## GPIO Assignments

| Pin | GPIO    | Net Name        | Function / Notes              |
|-----|---------|-----------------|-------------------------------|
| 1   | GPIO0   | LED1            | LED 1 control                 |
| 2   | GPIO1   | LED2            | LED 2 control                 |
| 4   | GPIO2   | GPIO2           | General purpose               |
| 5   | GPIO3   | GPIO3           | General purpose               |
| 6   | GPIO4   | GPIO4           | General purpose               |
| 7   | GPIO5   | I2C_SDA         | I2C data                      |
| 9   | GPIO6   | I2C_SCL         | I2C clock                     |
| 10  | GPIO7   | GPIO7           | General purpose               |
| 11  | GPIO8   | GPIO8           | General purpose               |
| 12  | GPIO9   | GPIO9           | General purpose               |
| 14  | GPIO10  | SPI1_SCK        | SPI1 clock                    |
| 15  | GPIO11  | SPI1_TX         | SPI1 MOSI                     |
| 16  | GPIO12  | SPI1_RX         | SPI1 MISO                     |
| 17  | GPIO13  | SPI1_CS         | SPI1 chip select              |
| 19  | GPIO14  | Blinky          | Status / heartbeat LED        |
| 20  | GPIO15  | PWM_Gate        | PWM output (via 10R + 3.3nF)  |
| 21  | GPIO16  | SPI0_MISO       | SPI0 MISO                     |
| 22  | GPIO17  | SPI0_CS1        | SPI0 chip select 1            |
| 24  | GPIO18  | SPI0_SCK        | SPI0 clock                    |
| 25  | GPIO19  | SPI0_MOSI       | SPI0 MOSI                     |
| 26  | GPIO20  | SPI0_CS2        | SPI0 chip select 2            |
| 27  | GPIO21  | INA_OOR_Alert   | INA out-of-range alert input  |
| 29  | GPIO22  | DRDY_TMP        | Temp sensor data-ready input  |
| 31  | GPIO26  | ADC_PWR         | ADC0 — power measurement      |
| 32  | GPIO27  | ADC_VOUT        | ADC1 — Vout measurement       |
| 34  | GPIO28  | ADC_Input_Curr  | ADC2 — input current          |
