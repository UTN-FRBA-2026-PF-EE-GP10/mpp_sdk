# BeagleBone Black Setup Guide for mpp-sdk

Step-by-step guide to get the BBB talking to the RP2040 Pico over SPI and
running the mpp-sdk.

---

## Step 0 — What you need

| Item | Notes |
|---|---|
| BeagleBone Black (Rev C) | AM335x, 512 MB RAM |
| MicroSD card | ≥ 8 GB, Class 10 recommended |
| 5 V barrel-jack or USB power supply | Barrel jack preferred for stability during flashing |
| Ethernet cable or USB cable | For headless SSH access |
| 6 jumper wires + 1 GND wire | 4 for SPI + 2 for SWD debug/flashing |
| A PC with an SD card reader | To flash the image |

---

## Step 1 — Download the Debian image

> [!IMPORTANT]
> **You don't need to compile Linux.** BeagleBoard.org ships pre-built
> Debian images — just download, flash, and boot.

Go to **https://www.beagleboard.org/distros** and download:

- **Debian 13 (Trixie) IoT** image for the AM335x (BeagleBone Black)
- Pick the **IoT** (non-GUI) variant — you don't need a desktop, and it
  leaves more RAM and disk for the SDK
- The file will be something like `bone-debian-13.x-iot-armhf-YYYY-MM-DD-4gb.img.xz`

> [!TIP]
> "IoT" = headless, no graphical desktop. Since you'll SSH into it from
> your laptop (same as you do with the RPi 5), this is what you want.

---

## Step 2 — Flash the microSD card

On your PC:

```bash
# Option A: balenaEtcher (GUI) — download from https://www.balena.io/etcher/
# Just select the .img.xz file, select the SD card, click Flash.

# Option B: command line (Linux/Mac)
xzcat bone-debian-13.x-iot-armhf-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
sync
```

Replace `/dev/sdX` with your actual SD card device (`lsblk` to find it).

---

## Step 3 — First boot and SSH

1. Insert the microSD into the BBB
2. **Hold the USER/BOOT button** (near the SD slot) while plugging in power
3. Release once the LEDs start blinking (forces boot from SD instead of eMMC)

### Connect via USB (easiest for first setup)

```bash
# The BBB creates a USB network interface at 192.168.7.2
ssh debian@192.168.7.2
# Default password: temppwd (check your image's release notes)
```

### Or via Ethernet

```bash
# If connected to your LAN, find its IP with nmap or check your router
ssh debian@<bbb-ip>
```

### First things to do after logging in

```bash
# Change the default password
passwd

# Update the system
sudo apt update && sudo apt upgrade -y

# Check what you're running
uname -a
# Should show something like: Linux beaglebone 6.12.x armv7l GNU/Linux
cat /etc/debian_version
# Should show: 13.x
```

---

## Step 4 — Optional: flash to eMMC

If you want the OS on the internal 4 GB eMMC (so you don't need the SD card
inserted every time):

```bash
sudo /opt/scripts/tools/eMMC/init-eMMC-flasher-v3.sh
# Takes ~30 min. Board shuts down when done.
# Remove SD card, power back on — it boots from eMMC now.
```

> [!NOTE]
> Running from SD card is fine too — it's just slower. For bench use, either
> works.

---

## Step 5 — Install Python 3.14 and uv

### Check what's already there

```bash
python3 --version
# Debian 13 (Trixie) should have Python 3.13 or 3.14 in the repos
```

### If Python 3.14 is in the repos (likely)

```bash
sudo apt install -y python3.14 python3.14-dev python3.14-venv
```

### If not, install via uv

```bash
# Install uv (works on armv7/armhf)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # or restart your shell

# Let uv install Python 3.14
uv python install 3.14
```

### Install uv (if you didn't already)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv --version
```

> [!WARNING]
> **ARM 32-bit heads up.** The BBB is `armv7l` (32-bit ARM), not `aarch64`
> (64-bit). Most Python packages have wheels for armhf, but some may need
> to compile from source — `numpy` in particular might take a few minutes to
> build. Install build dependencies just in case:
> ```bash
> sudo apt install -y build-essential python3-dev libopenblas-dev gfortran
> ```

---

## Step 6 — Enable SPI

This is the main difference from the RPi 5, where SPI is enabled with a
simple `raspi-config` toggle. The BBB needs pin-muxing.

### 6a — Disable HDMI (frees SPI1 pins)

SPI1 shares pins with HDMI on the BBB. Since you're running headless, disable
it:

```bash
sudo nano /boot/uEnv.txt
```

Add or uncomment these lines:

```text
disable_uboot_overlay_video=1
disable_uboot_overlay_audio=1
```

### 6b — Enable the SPI1 overlay

On **Debian 13 (Trixie) with kernel 6.x**, overlays are stored in `/boot/dtbs/$(uname -r)/overlays/` rather than `/lib/firmware/`.

To permanently enable SPI1 directly in the active device tree:

```bash
# 1. Merge the SPI1 overlay into the base device tree blob
sudo fdtoverlay -i /boot/dtbs/$(uname -r)/am335x-boneblack-uboot.dtb \
                -o /boot/dtbs/$(uname -r)/am335x-boneblack-uboot.dtb \
                /boot/dtbs/$(uname -r)/overlays/BB-SPIDEV1-00A0.dtbo

# 2. Ensure the spidev driver loads at boot
echo spidev | sudo tee /etc/modules-load.d/spidev.conf

# 3. Give user debian read/write access to SPI without sudo
sudo tee /etc/udev/rules.d/80-spidev.rules > /dev/null << 'EOF'
KERNEL=="spidev*", GROUP="dialout", MODE="0660"
EOF

# 4. Reboot
sudo reboot
```

### 6c — Verify SPI is working

```bash
ls -l /dev/spidev*
# Should show:
# crw-rw---- 1 root dialout 153, 1 /dev/spidev1.0
# crw-rw---- 1 root dialout 153, 0 /dev/spidev1.1
```

---

## Step 7 — Wire the BBB to the RP2040 Pico

### 7a — SPI telemetry and control wiring

```text
BeagleBone Black (P9 header)          RP2040 Pico
──────────────────────────────        ─────────────
P9.31  (SPI1_SCLK) ─────────────────► GPIO 14 (SCK)
P9.29  (SPI1_D0 = MISO) ◄───────────── GPIO 11 (TX/MISO)
P9.30  (SPI1_D1 = MOSI) ─────────────► GPIO 12 (RX/MOSI)
P9.28  (SPI1_CS0) ──────────────────► GPIO 13 (CSn)
P9.1 or P9.2  (GND) ────────────────► GND
```

### 7b — SWD flashing & debug wiring (optional but recommended)

Allows flashing firmware remotely and reading high-speed `defmt` debug logs without touching the Pico or plugging in USB cables:

```text
BeagleBone Black (P9 header)          RP2040 Pico Debug Header / Pads
──────────────────────────────        ───────────────────────────────
P9.12  (GPIO 540 / SWDIO) ──────────► SWDIO (right pad)
P9.14  (GPIO 530 / SWCLK) ──────────► SWCLK (left pad)
P9.1 or P9.2  (GND) ────────────────► GND   (middle pad or shared pin)
```

> [!IMPORTANT]
> **Both boards are 3.3 V logic.** No level shifter needed — wire directly.
> These are the same Pico SPI1 slave pins the firmware already uses; only
> the *host* side changed.

### Quick reference — P9 header physical location

```text
    P9 Header (BBB, top-left edge, USB port facing you)
    ┌────────────────────────────┐
    │ Pin 1 (GND)   Pin 2 (GND) │  ← use either for GND
    │ ...                       │
    │ Pin 11         Pin 12     │  ← P9.12 = SWDIO (GPIO 540)
    │ Pin 13         Pin 14     │  ← P9.14 = SWCLK (GPIO 530)
    │ ...                       │
    │ Pin 27         Pin 28     │  ← P9.28 = SPI1_CS0
    │ Pin 29         Pin 30     │  ← P9.29 = MISO, P9.30 = MOSI
    │ Pin 31         Pin 32     │  ← P9.31 = SCLK
    │ ...                       │
    └────────────────────────────┘
```

#### Pico Debug Pads Location
On the Raspberry Pi Pico, the 3-pin debug header/pads are located at the bottom edge opposite the USB connector:
```text
  ┌────────────────────────────────────────────────────────┐
  │ [USB]                                     [SWCLK GND SWDIO] │
  └────────────────────────────────────────────────────────┘
                                               Pin 1: SWCLK (left)
                                               Pin 2: GND   (middle)
                                               Pin 3: SWDIO (right)
```

---

## Step 8 — Clone and install the SDK

```bash
# On the BeagleBone Black, via SSH:
cd ~
git clone https://github.com/<your-org>/mpp-sdk.git
cd mpp-sdk

# Install with hardware extras
uv sync --extra hardware

# If you also want the web workbench:
uv sync --extra hardware --extra web
```

---

## Step 9 — Test the SPI link

### Quick test with spi_test.py

```bash
# Power on the Pico board, then:
uv run python scripts/spi_test.py --once
```

You should see a line with V_raw, I_raw, Vout_raw values and a `✓` in the
`crc?` column — same output you get on the RPi 5.

**The only difference**: pass `bus=1` instead of the default `bus=0`:

```bash
# If spi_test.py uses the default bus=0 and your BBB has SPI1:
# Edit BUS at the top of spi_test.py from 0 to 1, or:
```

### Using SpiMcuSource directly

```python
from mpp_sdk.io.spi_mcu import SpiMcuSource

# BBB uses SPI1 → bus=1
with SpiMcuSource(bus=1, device=0) as src:
    src.write(0.0)         # send duty=0
    v, i = src.read()      # read telemetry
    print(f"V={v:.3f} V, I={i:.3f} A")
```

### Running the full web workbench

```bash
uv run mpp-sdk curve-tracer-web
# Open http://<bbb-ip>:8000/ from your laptop
```

---

## Step 10 — Make SPI config persist across reboots

If you used the Device Tree Overlay method (Step 6b), it already persists.

If you used `config-pin` (Step 6c), create a systemd service:

```bash
sudo tee /etc/systemd/system/spi1-pins.service > /dev/null << 'EOF'
[Unit]
Description=Configure SPI1 pins for mpp-sdk
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/config-pin P9.28 spi_cs
ExecStart=/usr/bin/config-pin P9.29 spi
ExecStart=/usr/bin/config-pin P9.30 spi
ExecStart=/usr/bin/config-pin P9.31 spi_sclk
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable spi1-pins.service
sudo systemctl start spi1-pins.service
```

---

## Step 11 — Remote firmware flashing via OpenOCD SWD

With SWD connected (Step 7b), you can build the firmware on your PC (fast) and flash the Pico over the network via the BeagleBone Black — no need to unplug wires or hold the BOOTSEL button.

### 11a — Install OpenOCD on the BeagleBone Black

```bash
# On the BBB:
sudo apt update && sudo apt install -y openocd
```

### 11b — Create the flashing configuration on the BBB

Create `/etc/openocd/rp2040_swd.cfg`:

```bash
sudo tee /etc/openocd/rp2040_swd.cfg > /dev/null << 'EOF'
adapter driver sysfsgpio
sysfsgpio swdio_num 540
sysfsgpio swclk_num 530
transport select swd
source [find target/rp2040.cfg]
EOF
```

### 11c — Build on your PC and flash remotely

From your host PC inside the repository:

```bash
# 1. Compile the firmware in release mode
cd firmware/pipico_board
cargo build --release

# 2. Transfer the ELF binary to the BeagleBone
scp target/thumbv6m-none-eabi/release/mpp-firmware debian@<bbb-ip>:/tmp/mpp-firmware.elf

# 3. Flash, verify, and reboot the Pico
ssh debian@<bbb-ip> "sudo openocd -f /etc/openocd/rp2040_swd.cfg -c 'program /tmp/mpp-firmware.elf verify reset exit'"
```

> [!TIP]
> **One-step build & flash:** You can configure Cargo on your PC to flash automatically when you type `cargo run --release`.
> In `firmware/pipico_board/.cargo/config.toml`, set:
> ```toml
> [target.thumbv6m-none-eabi]
> runner = "bash -c 'scp $0 debian@<bbb-ip>:/tmp/mpp-firmware.elf && ssh debian@<bbb-ip> \"sudo openocd -f /etc/openocd/rp2040_swd.cfg -c \\\"program /tmp/mpp-firmware.elf verify reset exit\\\"\"'"
> ```

---

## Step 12 — Stream live debug logs (defmt over RTT)

The firmware logs telemetry (voltage, current, temperature, ADC calibration) via `defmt` over SEGGER RTT using the SWD pins. You can stream these logs live to your PC over Ethernet without needing a serial/UART cable.

### 12a — Setup host PC tools

On your development PC, install `defmt-print`:

```bash
cargo install defmt-print
```

### 12b — Configure RTT on the BeagleBone Black

Create `/etc/openocd/rp2040_rtt.cfg` on the BBB:

```bash
sudo tee /etc/openocd/rp2040_rtt.cfg > /dev/null << 'EOF'
bindto 0.0.0.0
adapter driver sysfsgpio
sysfsgpio swdio_num 540
sysfsgpio swclk_num 530
transport select swd
source [find target/rp2040.cfg]
init
poll off
rtt setup 0x20000000 0x40000 "SEGGER RTT"
rtt polling_interval 1000
rtt start
rtt server start 9999 0
EOF
```

> [!IMPORTANT]
> **Critical BBB CPU optimization:**
> - `poll off` disables OpenOCD's continuous GDB core polling. Without this, constant SWD bitbang traffic wakes up BeagleBoard's `gpio-manager` system service, pegging the single CPU core at 100%.
> - `rtt polling_interval 1000` polls the RTT buffer once per second instead of the default ~1 ms, which matches the ~1 Hz sensor logging rate and drops CPU usage down to ~10–15%.

### 12c — Start the RTT server on the BBB

Run OpenOCD with reduced priority (`nice -n 19`) so it never starves real-time tasks:

```bash
# In foreground:
sudo nice -n 19 openocd -f /etc/openocd/rp2040_rtt.cfg

# Or in background with nohup:
sudo nohup nice -n 19 openocd -f /etc/openocd/rp2040_rtt.cfg > /tmp/openocd.log 2>&1 &
```

### 12d — View the log stream from your PC

From the root of the `mpp-sdk` repository on your PC, pipe the RTT TCP stream directly into `defmt-print`:

```bash
nc <bbb-ip> 9999 | defmt-print -e firmware/pipico_board/target/thumbv6m-none-eabi/release/mpp-firmware
```

You will see live decoded firmware logs in your terminal:
```text
INFO  V=0 mV I=0 mA T=n/a
INFO  ADC_PWR=0 mV ADC_VOUT=8 mV ADC_Input_Curr=3 mV (INA229 V=0 mV I=0 mA)
INFO  ADC cal: PWR raw=0.0 pin=0 mV scaled=0 mV | VOUT raw=14.3 pin=0 mV scaled=0 mV | INA229 V=0 mV (n=10)
```

To stop viewing, simply press `Ctrl+C`.

---

## Summary of differences from the RPi 5

| What | RPi 5 | BBB |
|---|---|---|
| Image | Raspberry Pi OS | Debian IoT from beagleboard.org |
| Enable SPI | `raspi-config` toggle | Device tree overlay + HDMI disable |
| SPI device | `/dev/spidev0.0` (bus=0) | `/dev/spidev1.0` (bus=1) |
| SPI pins | GPIO header (BCM 8-11) | P9 header (pins 28-31) |
| SWD debug pins | GPIO header (BCM 24, 25) | P9 header (P9.12=SWDIO, P9.14=SWCLK) |
| Firmware flashing | SWD via RPi GPIO (`rp2040.cfg`) | SWD via BBB GPIO (`sysfsgpio`) |
| Live telemetry logs | defmt over RTT (port 9999) | defmt over RTT (port 9999, `poll off`) |
| `SpiMcuSource()` call | `SpiMcuSource(bus=0, device=0)` | `SpiMcuSource(bus=1, device=0)` |
| Code changes needed | — | **None** (just different constructor args) |
| Firmware changes | — | **None** |

> [!CAUTION]
> **Performance caveat.** The BBB has a 1 GHz Cortex-A8 with 512 MB RAM — it
> will be noticeably slower than the RPi 5 for heavy tasks (matplotlib
> figures, the web workbench, numpy-heavy harness runs). The MPPT control
> loop itself is unaffected — it's just `step(V, I) → D` + one SPI exchange.
