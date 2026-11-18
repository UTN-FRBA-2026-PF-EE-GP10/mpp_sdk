# Dimmer link

The halogen lamp lights the panels. The Pi sets its firing angle `alpha` through the Pico.

```text
Pi (SPI0 master) --SPI--> Pico (SPI1 slave, I2C master) --I2C--> dimmer ESP32-C3 (I2C slave) --> TRIAC --> lamp
```

- The wire format of the I2C side lives in one crate: `firmware/dimmer-link`.
  The Pico firmware and the dimmer firmware both use it.
- The Pi side uses two SPI commands, listed below.

## Wiring

Connect one of the Pico board I2C headers (J5 or J8) to the dimmer connector J1.

| Pico board J5 / J8 | Net | Dimmer J1 | Net |
| --- | --- | --- | --- |
| 1 | +3.3V | 1 | 3V3 in |
| 2 | GNDA | 2 | GND |
| 3 | I2C_SDA (GPIO5) | 3 | SDA (ESP32-C3 IO6) |
| 4 | I2C_SCL (GPIO6) | 4 | SCL (ESP32-C3 IO7) |

- The Pico board has 4.7 kohm pull-ups on both lines. The dimmer has none. Keep the cable short.
- J1 pin 1 powers the ESP32-C3. The dimmer design asks for a regulated 3.3 V supply of at least 1 A.
  Power the dimmer from its own supply and leave pin 1 open on the Pico side,
  unless you checked the spare current of the Pico board 3.3 V rail.
- Connect the grounds. The dimmer ground is the isolated SELV side. The mains side stays behind the optocouplers.
- On the RP2040, GPIO5 is only I2C0 SCL and GPIO6 is only I2C1 SDA.
  No I2C block can drive this pair as SDA and SCL, so the Pico firmware drives the pair in software.

## I2C frames

- 7-bit address `0x2A`, 100 kHz, Pico is master.
- All values are big-endian. The CRC is CRC-8, polynomial `0x07`, init `0xFF`, the same as the SPI link.

Command (master writes 4 bytes):

```text
[ CMD | ARG_H | ARG_L | CRC ]
```

| CMD | Name | ARG |
| --- | --- | --- |
| `0x01` | Set alpha | alpha in 0.01 degree. `0` is full on, `18000` is off. Above `18000` is rejected. |
| `0x02` | Request status | `0` |

Status (master reads 8 bytes, at least 3 ms after Request status):

```text
[ 0xD1 | FLAGS | ALPHA_H | ALPHA_L | FREQ_H | FREQ_L | BAD_FRAMES | CRC ]
```

- `FLAGS` bit 0: mains present. Bit 1: locked to the mains. Bit 2: lamp switched off by the timeout.
- `ALPHA` is the angle the dimmer really fires at, after its own limits. `0xFFFF` means it does not fire.
- `FREQ` is the mains frequency in 0.01 Hz. It is `0` without mains.
- `BAD_FRAMES` counts rejected commands (wraps). A rising value means a noisy cable.

## Safety

- The dimmer is off after boot.
- The Pico repeats the last Set alpha every 500 ms.
  The dimmer turns the lamp off after 2 s without a valid Set alpha.
- The dimmer checks this timeout in its own loop, not in the I2C code, so a stalled I2C driver cannot keep the lamp on.
  The timeout also releases the full-on state.
- A new valid Set alpha clears the `TIMED_OUT` flag and the lamp follows the new angle.
- The Pi repeats `0xD1` at least every second while the lamp is on.
  The Pico sets alpha to off after 3 s without a valid `0xD1`.
  A stopped or crashed Pi program switches the lamp off.
- The Pico sets alpha to off at boot and when the SPI link to the Pi is lost.
- The dimmer firmware limits the firing delay, so the real range is about 25 to 153 degrees at 50 Hz.
  The angles `0` (full on) and `18000` (off) are the exceptions.
  Read `ALPHA` in the status to see the real value.
- A lamp that is on for no reason is a fire risk. Keep the lamp under watch while the link is new.

## SPI commands (Pi to Pico)

Both use the 12-byte frame of the [measurement protocol](mppt_measurement_protocol.md) with the usual CRC.

| CMD | Name | MOSI |
| --- | --- | --- |
| `0xD1` | Set dimmer alpha | `[ ALPHA_H \| ALPHA_L \| CHECKSUM \| 0xD1 \| 0 x 8 ]`. The Pico ignores a value above `18000`. |
| `0xD2` | Request dimmer status | `[ 0 \| 0 \| CHECKSUM \| 0xD2 \| 0 x 8 ]` |

The reply to `0xD2` is in the MISO of the next exchange, like the sweep progress poll:

```text
[ 0xD2 | FLAGS | SET_H | SET_L | APPLIED_H | APPLIED_L | AGE | 0x00 | CHECKSUM | ACK | 0x00 x 2 ]
```

- `FLAGS` bit 0: the I2C link works (a status read succeeded in the last second).
  Bits 1 to 3 are the dimmer flags from above, shifted up by one:
  bit 1 mains, bit 2 locked, bit 3 timed out.
- The CRC covers bytes 0 to 7, then `ACK` (byte 9), then byte 10 (`SETTLED`, always `0` here), in that order.
  Every MISO frame does the same.
- `SET` is the alpha the Pico holds now.
  It is the last alpha the Pi sent, or `18000` after a timeout or a link loss. `APPLIED` is the angle the dimmer reported.
- `AGE` is the time since the last good status read, in 100 ms units, saturating at 255.

## Lamp power

For a resistive lamp the power fraction at angle `alpha` is `P = 1 - alpha/pi + sin(2 alpha)/(2 pi)`.

## Python use

- `SpiMcuSource` sends the commands.
- Every "lamp on" has a deadline: `max_on_s` (default 60 s, at most 120 s, else `ValueError`).
  The lamp is open loop, so a lamp that stays on by mistake is a fire risk.
- A thread repeats the last alpha every second (the `dimmer_keepalive_s` argument, at most 2 s).
  At the deadline the same thread sends OFF and stops, also if the caller hangs.
- A new `set_dimmer_*` call starts a new deadline. `dimmer_window_left_s()` gives the time left
  (`None` when the lamp is off).
- `lamp_window(power=...)` or `lamp_window(alpha_deg=...)` is the safe way to use the lamp.
  It sets the lamp, reads the status once, and always sends OFF when the block ends,
  also on an exception or Ctrl-C.
  It raises `DimmerRefused` (after OFF) if the dimmer reports `tripped`.
- If `dimmer_status()` shows `tripped` while the host thinks the lamp is on, it sends OFF.
  That OFF is the acknowledgment the dimmer needs before it accepts "on" again.
- `close()` and `dimmer_off()` stop the thread and switch the lamp off.
- `scripts/dimmer_set.py` does the same from the command line.
  With `--hold`, `--max-on-s` sets the longest time the lamp stays on.
  The status line shows `tripped` and `budget_s`.

```python
with SpiMcuSource() as src:
    with src.lamp_window(power=0.5, max_on_s=10.0):
        measure()  # the lamp is on here and off afterwards
    print(src.dimmer_status())
```
