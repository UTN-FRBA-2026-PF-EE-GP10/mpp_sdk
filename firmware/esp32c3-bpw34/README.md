# esp32c3-bpw34

Rust firmware (ESP-IDF, `std`) for an ESP32-C3 reading a BPW34 photodiode
through an MCP6002 transimpedance amplifier (TIA) on the ADC.

This is a standalone light-sensor experiment, separate from the main
RP2040 HIL firmware in [`../pipico_board`](../pipico_board).

## Toolchain prerequisites

System packages (Debian/Ubuntu/Pop!_OS) needed to build ESP-IDF and to
flash over USB:

```sh
sudo apt install git wget flex bison gperf python3 python3-venv \
    cmake ninja-build ccache libffi-dev libssl-dev dfu-util \
    libudev-dev pkg-config
```

Rust tooling:

```sh
cargo install ldproxy espflash
```

`rust-toolchain.toml` already pins `nightly` with the `rust-src` component,
so `rustup` will fetch it automatically on first build — no manual
`rustup toolchain add` needed.

Unlike the Xtensa ESP32 targets, the ESP32-C3 is RISC-V, so it builds with
upstream `nightly` (no `espup`/Xtensa fork required). The target is
`riscv32imc-esp-espidf`, set in `.cargo/config.toml`.

## First build

```sh
cargo build --release
```

The first build downloads and compiles ESP-IDF `v5.5.3` (pinned in
`.cargo/config.toml` via `ESP_IDF_VERSION`) into `ESP_IDF_TOOLS_INSTALL_DIR
= "workspace"`. This takes a while and several GB of disk — expect it once
per machine, cached afterward.

## Flash and run

```sh
cargo run --release
```

The `.cargo/config.toml` runner is `espflash flash --monitor`, so this
builds, flashes over USB, and streams serial log output in one command.
Log lines come from plain `println!` in `src/main.rs` (this project uses
`log`/`println!`, not `defmt` — unlike the RP2040 firmware).

## The circuit

A BPW34 photodiode feeds an MCP6002 op-amp wired as a transimpedance
amplifier (TIA), converting photocurrent to a voltage the ESP32-C3's ADC
can read.

- **Bias (`V+`)**: a 1k / 10k divider off the 3.3V rail sets the
  non-inverting input to `3.3V * 1/11 ≈ 0.3V`. This reverse-biases the
  photodiode slightly, which is standard for a fast, low-dark-current TIA
  front end.
- **Feedback (`Rf`)**: two 470k resistors in parallel give
  `Rf = 120k`. TIA output swing is `V_out = V+ + I_photo * Rf`, so gain is
  set purely by `Rf`.
- **Output**: the op-amp output drives the ESP32-C3 ADC pin directly
  (currently GPIO2, `AdcChannelDriver` on `adc1`, 12-bit resolution,
  `DB_12` attenuation, with the IDF calibration API applied so raw counts
  are converted to millivolts in software).

## What it does

`src/main.rs` reads `adc1`/`GPIO2` in a loop (12-bit, `DB_12` attenuation),
applies the IDF ADC calibration curve to get millivolts, and prints
`raw=... voltage=...mV` every 500ms.
