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

Status (master reads 9 bytes, at least 3 ms after Request status):

```text
[ 0xD1 | FLAGS | ALPHA_H | ALPHA_L | FREQ_H | FREQ_L | BAD_FRAMES | BUDGET_S | CRC ]
```

- `FLAGS` bit 0: mains present. Bit 1: locked to the mains. Bit 2: lamp switched off by the timeout.
  Bit 3: exposure limit tripped (see [Exposure limit](#exposure-limit)).
- `ALPHA` is the angle the dimmer really fires at, after its own limits. `0xFFFF` means it does not fire.
- `FREQ` is the mains frequency in 0.01 Hz. It is `0` without mains.
- `BAD_FRAMES` counts rejected commands (wraps). A rising value means a noisy cable.
- `BUDGET_S` is the exposure budget in seconds, at most 255.
  Not tripped: lamp-on time left before a trip.
  Tripped: seconds until the dimmer has cooled.
  `0` while tripped means cooled, waiting for an OFF.
- The CRC covers bytes 0 to 7.

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

## Exposure limit

The lamp is open loop, so the dimmer limits how long it may be on.
The limit lives on the dimmer, the last part before the mains.
It does not depend on the Pico or the Pi.
It does not cover a stalled dimmer main loop: that stops the limiter and the deadman too.
A task watchdog for this is a later item.

- The dimmer keeps a "heat" counter in milliseconds.
  It counts the time the lamp is *commanded* on, not the time it really fires.
  So it also runs with no mains, and you can test it on the bench with no mains.
- The counter rises 1 ms per ms while the lamp is commanded on.
  It falls 1 ms per ms while the lamp is off, and never goes below 0.
- At `EXPOSURE_MAX_ON_MS` (120 s) the dimmer trips.
  It forces the lamp off at once (in its 10 ms loop) and latches the trip.
- While tripped, every on-command is refused and the lamp stays off.
  This holds for I2C and for Wi-Fi.
- The trip clears only when both are true:
  the counter is at or below `EXPOSURE_RESUME_MS` (60 s),
  and the host sent an explicit OFF after the trip (`SetAlpha(18000)`, or Wi-Fi level 0).
  An OFF that arrives early is remembered.
  The deadman and the trip itself do not count as that OFF.
  So a host that keeps sending its old angle never restarts the lamp by itself.
  It must send OFF, then ask again.
- The Pico also sends its own OFF at boot and after its 3 s host timeout.
  The dimmer counts that as the acknowledgment.
  So a crashed or idle host acknowledges by itself,
  and the next on-command works after the cool-down.
- The time between two loop ticks is counted when a command arrives,
  so fast on and off toggling does not hide the on time.
- The long-run duty is at most 50 percent.
  Short windows (about 10 s) can repeat until the counter is full.
- The counter is in RAM only.
  A dimmer reset clears it and the trip.
  The lamp is off after a reset, so this is safe.
- Status: flag bit 3 and `BUDGET_S`.
  The Pico copies them to the Pi (SPI reply flag bit 4 and byte 7).
- Only the tripped bit says the lamp is blocked.
  `BUDGET_S` can be `0` while the lamp is still allowed
  (heat between 119.5 s and 120 s).
- When `link_ok` is `0`, the tripped bit and `BUDGET_S` are unknown.
  The Pico sends `0` and `0`.
  The other dimmer flags keep their last values.
- `BUDGET_S` stops at 255 s if `EXPOSURE_MAX_ON_MS` is ever raised above 255 s.

To change the limits after a bench thermal test:

- Edit `EXPOSURE_MAX_ON_MS` and `EXPOSURE_RESUME_MS` in `firmware/dimmer-link/src/lib.rs`.
- Keep `EXPOSURE_RESUME_MS` below `EXPOSURE_MAX_ON_MS`.
- Run `cargo test` in `firmware/dimmer-link`.
- Build and flash the dimmer again.
- Flash the Pico and the dimmer together.
  An old Pico with a new dimmer (or the reverse) fails the CRC, so the link reads as down.
- Check the Python side: its window limit mirrors `EXPOSURE_MAX_ON_MS`.

## SPI commands (Pi to Pico)

Both use the 12-byte frame of the [measurement protocol](mppt_measurement_protocol.md) with the usual CRC.

| CMD | Name | MOSI |
| --- | --- | --- |
| `0xD1` | Set dimmer alpha | `[ ALPHA_H \| ALPHA_L \| CHECKSUM \| 0xD1 \| 0 x 8 ]`. The Pico ignores a value above `18000`. |
| `0xD2` | Request dimmer status | `[ 0 \| 0 \| CHECKSUM \| 0xD2 \| 0 x 8 ]` |

The reply to `0xD2` is in the MISO of the next exchange, like the sweep progress poll:

```text
[ 0xD2 | FLAGS | SET_H | SET_L | APPLIED_H | APPLIED_L | AGE | BUDGET_S | CHECKSUM | ACK | 0x00 x 2 ]
```

- `FLAGS` bit 0: the I2C link works (a status read succeeded in the last second).
  Bits 1 to 3 are the dimmer flags from above, shifted up by one:
  bit 1 mains, bit 2 locked, bit 3 timed out, bit 4 tripped.
- `BUDGET_S` (byte 7) is the budget from the I2C status.
  Without a good status read in the last second, `BUDGET_S` is `0` and the tripped bit is clear.
  Bit 0 then tells that the data is old.
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
  It sets the lamp, then waits up to 1.5 s (poll every 0.25 s) for a valid status with `link_ok`.
  It always sends OFF when the block ends (3 tries), also on an exception or Ctrl-C.
  It raises `DimmerRefused` (after OFF) if the link is not confirmed or the dimmer reports `tripped`.
  `timed_out` is not checked: the Pico reports it from a cache that can be 1 s old.
- If `dimmer_status()` shows `tripped` while the host thinks the lamp is on, it sends OFF.
  That OFF is the acknowledgment the dimmer needs before it accepts "on" again.
- `tripped` and `budget_s` are unknown when `link_ok` is false (the Pico sends 0 and 0).
  `budget_s == 0` does not mean blocked: only `tripped` does.
  The Pico's own OFF (at boot and after its 3 s host timeout) also counts as the OFF acknowledgment.
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
