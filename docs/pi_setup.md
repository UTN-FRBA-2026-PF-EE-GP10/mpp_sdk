# Raspberry Pi setup

How to prepare a Raspberry Pi as the host of the bench. It runs the
workbench server and talks to the Pico over SPI. For a BeagleBone Black,
see the [BeagleBone Black setup](beaglebone_setup_guide.md).

## Set up the Pi

1. Install Raspberry Pi OS and make sure you can log in over ssh:
   `ssh <user>@<pi-host>`.
2. Enable the SPI interface:
   - Run `sudo raspi-config`, then **Interface Options**, then **SPI**,
     then **Yes**.
   - Reboot.
   - Check that `/dev/spidev0.0` exists.
3. Install `git` and `uv`. Follow the uv install page, then check that
   `uv` is on the `PATH`.
4. Get the repository:

   ```bash
   git clone https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk.git
   cd mpp_sdk
   ```

5. Install the dependencies with the hardware and web extras. The first
   run installs Python 3.14 and can take a few minutes:

   ```bash
   uv sync --extra hardware --extra web
   ```

## Wire the Pico

1. Power off both boards.
2. Connect the Pi SPI0 pins to the Pico SPI1 pins. The Pico is the slave.

   | Pi signal     | Pi pin | Direction | Pico signal        | Pico GPIO | Pico pin |
   | ------------- | ------ | --------- | ------------------ | --------- | -------- |
   | MOSI (GPIO10) | 19     | to Pico   | SPI1_RX (MOSI in)  | GPIO12    | 16       |
   | MISO (GPIO9)  | 21     | from Pico | SPI1_TX (MISO out) | GPIO11    | 15       |
   | SCLK (GPIO11) | 23     | to Pico   | SPI1_SCK           | GPIO10    | 14       |
   | CE0 (GPIO8)   | 24     | to Pico   | SPI1_CS            | GPIO13    | 17       |
   | GND           | 25     | -         | GND                | -         | 18       |

3. Keep the wires short. The default SPI clock is 200 kHz, because faster
   clocks gave torn frames on jumper wires.
4. Power the Pico from its own USB cable or from the board.

The full wiring, the frame protocol and the flashing steps are in
[`firmware/pipico_board/README.md`](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/blob/main/firmware/pipico_board/README.md).
Flash the firmware from a PC with a debug probe, not from the Pi.

## Check the power

1. Run `vcgencmd get_throttled` on the Pi.
2. The result must be `0x0`.
3. Any other value means under-voltage or throttling. Under-voltage can
   stall SPI and abort runs. Fix the supply before you measure:
   - Use the official power supply for the Pi.
   - Do not power the lamp or other loads from the same supply.

## Start the workbench server

1. Run the server from the repository:

   ```bash
   uv run mpp-sdk curve-tracer-web
   ```

   The first start is slow. Wait up to a minute.
2. Open `http://<pi-host>:8000/` from any device on the bench network.
3. The server does not need the Pico at start. The connection pill shows
   an error until the board answers, then it shows **PICO connected**.
4. The server picks SPI bus 0 on a Raspberry Pi. Use `--spi-bus` to
   change it.
5. To try the workbench with no board, add `--demo`.

The server has no login. Keep it on the bench network. See the safety
notes in the [measurement procedure](measurement_procedure.md).

## Start the server at boot

1. Run this once on the Pi, from the repository, as the user that owns it:

   ```bash
   scripts/install_workbench_service.sh
   ```

2. The script asks for `sudo` once. It writes and starts the
   `mpp-workbench` systemd service. No path or user name is stored in the
   repository.
3. Stop any server you started by hand first. Both use port 8000 and the
   SPI link.

| Task | Command |
| --- | --- |
| Status | `systemctl status mpp-workbench` |
| Log | `journalctl -u mpp-workbench -f` |
| Restart | `sudo systemctl restart mpp-workbench` |
| Stop until next boot | `sudo systemctl stop mpp-workbench` |
| Remove | `scripts/install_workbench_service.sh --remove` |

## Restart safely

1. Wait until the workbench is idle: no sweep and no run in progress.
   A restart during a run loses the run.
2. After `git pull` and `uv sync`, restart the service:
   `sudo systemctl restart mpp-workbench`.
3. For a server started by hand, stop it with `Ctrl+C` in its terminal.
   If it runs in the background, find its process with
   `pgrep -f "[m]pp-sdk curve-tracer-web"` and stop it with `kill`. Do
   not run `pkill -f "mpp-sdk curve-tracer-web"` in an ssh command
   string. It matches its own shell.
4. Do not keep a debug probe attached during sweeps or runs. It can make
   the Pico reject Pi frames. Attach it only between runs.

## Next step

Follow the [measurement procedure](measurement_procedure.md) to capture
curves and run algorithms.
