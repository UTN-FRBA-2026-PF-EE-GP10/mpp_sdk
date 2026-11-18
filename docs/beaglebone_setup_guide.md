# BeagleBone Black setup

How to use a BeagleBone Black (BBB, Rev C) as the bench host instead of a
Raspberry Pi. Only the BBB-specific steps are here. The shared steps are in
the [Raspberry Pi setup](pi_setup.md): install `uv`, clone the repository,
`uv sync --extra hardware --extra web`, start the workbench, install the
boot service.

## Prepare the board

1. Flash the Debian 13 (Trixie) IoT image for the AM335x to a microSD card.
   Use the image and the steps on the official BeagleBoard site
   (<https://www.beagleboard.org/distros>). The IoT image has no desktop.
2. Hold the USER/BOOT button while you apply power. The board then boots
   from the SD card instead of the eMMC.
3. Log in over ssh as `<user>` at `<bbb-host>`. Over USB the board is
   usually at `192.168.7.2`. Change the default password.
4. Run `sudo apt update && sudo apt upgrade -y`.
5. Optional: copy the OS to the 4 GB eMMC with
   `sudo /opt/scripts/tools/eMMC/init-eMMC-flasher-v3.sh`. It takes about
   30 minutes. Remove the SD card after the board shuts down.
6. Install `uv` as in the Pi setup. The BBB is 32-bit ARM (`armv7l`). Some
   wheels, for example `numpy`, may build from source. Install the build
   tools first:
   `sudo apt install -y build-essential python3-dev libopenblas-dev gfortran`.

## Enable SPI1

On the BBB the SPI pins need an overlay. A `raspi-config` toggle does not
exist.

1. HDMI uses the SPI1 pins. Add these lines to `/boot/uEnv.txt`:

   ```text
   disable_uboot_overlay_video=1
   disable_uboot_overlay_audio=1
   ```

2. On Debian 13 with kernel 6.x the overlays are under
   `/boot/dtbs/$(uname -r)/overlays/`. Merge the SPI1 overlay into the
   active device tree:

   ```bash
   sudo fdtoverlay -i /boot/dtbs/$(uname -r)/am335x-boneblack-uboot.dtb \
                   -o /boot/dtbs/$(uname -r)/am335x-boneblack-uboot.dtb \
                   /boot/dtbs/$(uname -r)/overlays/BB-SPIDEV1-00A0.dtbo
   ```

3. Load `spidev` at boot and give the user access without `sudo`:

   ```bash
   echo spidev | sudo tee /etc/modules-load.d/spidev.conf
   echo 'KERNEL=="spidev*", GROUP="dialout", MODE="0660"' | sudo tee /etc/udev/rules.d/80-spidev.rules
   ```

4. Reboot. Check that `/dev/spidev1.0` and `/dev/spidev1.1` exist.

The overlay change is permanent. If you set the pins with `config-pin`
instead, the setting is lost at reboot. Then use a oneshot systemd unit
that runs `config-pin P9.28 spi_cs`, `P9.29 spi`, `P9.30 spi` and
`P9.31 spi_sclk` at boot.

## Wire the Pico

Both boards use 3.3 V logic. Wire them directly, with no level shifter.
The Pico side is the same as for the Pi. Only the host side changes.

| BBB pin | BBB signal | Direction | Pico GPIO |
| --- | --- | --- | --- |
| P9.31 | SPI1_SCLK | to Pico | GPIO10 (SCK) |
| P9.29 | SPI1_D0 (MISO) | from Pico | GPIO11 (TX) |
| P9.30 | SPI1_D1 (MOSI) | to Pico | GPIO12 (RX) |
| P9.28 | SPI1_CS0 | to Pico | GPIO13 (CSn) |
| P9.1 or P9.2 | GND | - | GND |

Optional SWD wires for flashing and logs from the BBB:

| BBB pin | Signal | Pico pad |
| --- | --- | --- |
| P9.12 (GPIO 540) | SWDIO | SWDIO (right pad) |
| P9.14 (GPIO 530) | SWCLK | SWCLK (left pad) |
| P9.1 or P9.2 | GND | GND (middle pad) |

The three SWD pads are at the bottom edge of the Pico, opposite the USB
connector: SWCLK, GND, SWDIO from left to right.

## Test and run

1. Power the Pico board. Run `uv run python scripts/spi_test.py --once`.
   The line must show `V_raw`, `I_raw`, `Vout_raw` and a valid CRC.
2. The SDK picks SPI bus 1 when `/proc/device-tree/model` names a
   BeagleBone. Use `--bus 1` (`spi_test.py`) or `--spi-bus 1` (server) to
   force it. In code use `SpiMcuSource(bus=1, device=0)`.
3. Start the workbench with `uv run mpp-sdk curve-tracer-web`. Open
   `http://<bbb-host>:8000/`.

## Flash the Pico over SWD from the BBB

You build on a PC and flash through the BBB. You do not unplug wires or
press BOOTSEL.

1. On the BBB run `sudo apt install -y openocd`.
2. Write `/etc/openocd/rp2040_swd.cfg` on the BBB:

   ```text
   adapter driver sysfsgpio
   sysfsgpio swdio_num 540
   sysfsgpio swclk_num 530
   transport select swd
   source [find target/rp2040.cfg]
   ```

3. On the PC, in `firmware/pipico_board`, run `cargo build --release`.
4. Copy and flash:

   ```bash
   scp target/thumbv6m-none-eabi/release/mpp-firmware <user>@<bbb-host>:/tmp/mpp-firmware.elf
   ssh <user>@<bbb-host> "sudo openocd -f /etc/openocd/rp2040_swd.cfg -c 'program /tmp/mpp-firmware.elf verify reset exit'"
   ```

## Stream firmware logs (defmt over RTT)

1. On the PC run `cargo install defmt-print`.
2. Write `/etc/openocd/rp2040_rtt.cfg` on the BBB:

   ```text
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
   ```

   - `poll off` stops the continuous core polling. Without it, the SWD
     traffic wakes the `gpio-manager` service and uses 100 % of the single
     CPU core.
   - `rtt polling_interval 1000` polls the buffer once per second. This
     matches the 1 Hz log rate and keeps the CPU at about 10-15 %.
3. Start it with low priority:
   `sudo nice -n 19 openocd -f /etc/openocd/rp2040_rtt.cfg`.
4. On the PC, from the repository root:

   ```bash
   nc <bbb-host> 9999 | defmt-print -e firmware/pipico_board/target/thumbv6m-none-eabi/release/mpp-firmware
   ```

## Differences from the Raspberry Pi

| What | Raspberry Pi | BBB |
| --- | --- | --- |
| Enable SPI | `raspi-config` | Overlay and HDMI disabled |
| SPI device | `/dev/spidev0.0` (bus 0) | `/dev/spidev1.0` (bus 1) |
| SPI pins | Header pins 19, 21, 23, 24 | P9.28 to P9.31 |
| SWD pins | BCM 24, 25 | P9.12 (SWDIO), P9.14 (SWCLK) |
| `SpiMcuSource` | `bus=0, device=0` | `bus=1, device=0` |
| Algorithm and firmware changes | none | none |

The BBB has a 1 GHz Cortex-A8 and 512 MB RAM. It is slower than a Pi 5 for
plots, the workbench and heavy harness runs. The control loop is not
affected: it is one `step(V, I)` call and one SPI exchange.
