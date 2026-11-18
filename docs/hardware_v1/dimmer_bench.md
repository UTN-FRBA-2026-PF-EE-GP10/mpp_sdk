# Dimmer bench tests

This is the procedure to test the lamp dimmer chain on the bench, step by step:

```text
Pi --SPI--> Pico --I2C--> dimmer ESP32-C3 --> TRIAC --> lamp
```

> **Status: untested on the bench.** The procedure and the script were written without hardware.
> The script was tested only with a fake source. Expect to correct limits and timings after the first run.
> Write down every difference. The protocol is in [dimmer_link.md](dimmer_link.md).

The order is a safety order. Each test adds one hazard. Do not start a test before the one before it passed.

| Test | What is connected | Hazard |
| --- | --- | --- |
| 0 | Pi, Pico, dimmer on a SELV supply. No mains. No lamp. | none |
| 1 | Same as Test 0, plus a scope or logic analyser on the SELV side. | none |
| 2 | Mains and a small lamp (25 to 40 W). | mains, fire |
| 3 | Mains and the full halogen lamp, with the panels. | mains, fire, hot panels |

## Safety rules

Read these before every session.

- Read `hardware/dimmer/README.md` and the bring-up order in
  `firmware/esp32c3-dimmer/README.md`.
- The board switches lethal mains voltage. It is an uncertified prototype.
- Never touch the board, the lamp terminals or a probe while the mains is connected.
- Do not clip an earthed scope onto the mains side. Probe the SELV side only.
- A second person is present in Tests 2 and 3. That person can reach the plug.
- Have a way to cut the mains at once: a plug you can pull, or a switch on a multi-socket.
- Mains tests: put the mains side behind an isolation transformer or a GFCI, with a fuse in line.
- Never leave a lamp on and walk away. Never leave a lamp on while you read the screen.
- Use a small lamp first. Do not use the full halogen lamp before Test 2 passed.
- If a check leaves the lamp on, or you do not know the lamp state: cut the mains first. Think after.
- If the exposure limiter trips: the dimmer already switched the lamp off. Do not try to force it on.
  Send OFF, wait for the cool-down (about 60 s), then continue.
- If you smell something, see smoke, or see the fuse blow: cut the mains, wait, check by eye
  and do not power the board again before you know the cause.
- The script always sends OFF at the end, on an error, on Ctrl-C and on SIGTERM.
  Do not trust this alone. Watch the lamp.

## Tools

- `scripts/dimmer_bench.py` runs the checks the Pi can see over SPI. `--help` lists the options.
- `scripts/dimmer_set.py` sets or reads the dimmer by hand.
- A session checklist: create a session from the template `dimmer-bench` in the workbench.
- Flash the Pico and the dimmer from the same commit. An old and a new version fail the CRC and the link reads as down.

```sh
uv run python3 scripts/dimmer_bench.py --list
uv run python3 scripts/dimmer_bench.py --out results.json            # all Test 0 checks
uv run python3 scripts/dimmer_bench.py --auto-only                   # no human steps
uv run python3 scripts/dimmer_bench.py --only trip --only no-restart
```

How the script reads results:

- Each check prints `PASS`, `FAIL` or `INCONCLUSIVE`.
- The exit code is `0` (all passed), `1` (a check failed), `2` (inconclusive, none failed),
  `3` (refused to start) or `130` (interrupted).
- Without `--mains` the script refuses to command an angle when the status says `mains` is true.
  This protects you from a wrong belief that the lamp is disconnected.
- The script starts a second Python process to hold an angle. It kills that process to test the timeouts.
- `--out` writes every status read to a JSON file. Keep it with the session.

## Test 0: Pico to dimmer link, no mains, no lamp

Purpose: test the link, the timeouts and the exposure limiter with no mains. The limiter counts the
commanded state, not real firing, so every part works with no mains.

Preconditions:

- J2 (mains) unplugged. No lamp. J3 empty. JP1 as in the firmware README for the SELV-only case.
- The dimmer is powered from its own 3.3 V supply. J1 pins 2, 3 and 4 go to the Pico board.
  Leave pin 1 open on the Pico side (see [dimmer_link.md](dimmer_link.md)).
- The Pico and the dimmer run firmware from the same commit. The Pi can reach the Pico over SPI.
- Optional: a multimeter on FIRE (GPIO4, SELV side). It must stay at 0 V.

Steps and expected readings. Run `uv run python3 scripts/dimmer_bench.py --out test0.json`, or one check at a time with `--only`.

| Check name | What it does | Expected reading | Pass when |
| --- | --- | --- | --- |
| `link` | Reads the status 3 s. | `link_ok` true. `mains` and `locked` false. | All reads valid and as expected. |
| `alpha` | Sets 90 deg, reads back, sets 180 deg, reads back. | `set_alpha_deg` follows. `applied_alpha_deg` is None. | Both read-backs match. |
| `stable` | Polls the status for a minute (`--stable-s`). | `link_ok` always true. | No failed read, status age at most 1.5 s. |
| `host-timeout` | Holds 90 deg in a second process, kills it. | `set_alpha_deg` goes to 180. | At 180 within about 4.5 s and stays there. |
| `i2c-unplug` | You unplug the I2C cable on a prompt. | `link_ok` false. | False within 4 s of your Enter. Back after you plug it in. |
| `spi-unplug` | You unplug the SPI cable on a prompt. | After you plug it back, set angle is 180. | Stays 180 over 4 s. |
| `deadman` | You unplug I2C for 4 s on a prompt. | `timed_out` seen after the plug-in. | Seen, or `INCONCLUSIVE` (see below). |
| `budget-fall` | Commands 90 deg, polls 10 s. | `budget_s` falls about 1 per second. | Slope 0.8 to 1.2 s per s. |
| `budget-rise` | Lamp off, polls 12 s. | `budget_s` rises about 1 per second. | Slope 0.8 to 1.2 s per s. |
| `trip` | Commands on until the trip. | `tripped` after about `budget_s` seconds. | See the limiter steps below. |
| `no-restart` | Streams on-commands past the cool-down. | Still `tripped` and `budget_s` 0. | Then clears after the OFF. |
| `reset-clears` | You reset the dimmer on a prompt. | `budget_s` back to about 120. `tripped` clear. | Both true. |

Notes for the timeouts:

- Pico timeout: the Pico sets alpha to 180 after 3 s without a valid `0xD1`. The status comes
  from a cache up to 1 s old, so the limit in the script is 4.5 s.
- I2C unplug: the Pico marks the link bad after about 2 s. Your Enter press is the start time,
  so the measured time has about 1 s of human delay.
- SPI unplug: the Pi cannot read the Pico while the cable is out. The script kills the holder
  process, so the Pico sees a stopped host. This cannot tell a lost SPI link from a host timeout.
  To see the link-loss latch itself, watch the Pico log on its debug port.
- Dimmer deadman (2 s): the Pico repeats the angle at once after the I2C cable is back,
  and that clears `timed_out`. The Pi may never see the flag. Then the result is `INCONCLUSIVE`.
  Check the flag on the dimmer USB log (it logs the timeout). Do not count `INCONCLUSIVE` as a pass.
- Bad frames: the dimmer counts `BAD_FRAMES`, but the Pico does not send it to the Pi.
  The `stable` check cannot see it. Read it in Test 1 (dimmer USB log or logic analyser).

Limiter steps (the `trip` and `no-restart` checks). Total time is about 7 minutes. The lamp is only
commanded, never lit, so no mains is needed.

1. Start with a full budget (wait 2 minutes after earlier checks). The script reads `budget_s`.
2. `trip`: it commands 90 deg in windows of 30 s, renewed every 10 s. It reads the status every second.
   `tripped` must be set at about `budget_s` seconds after the start (120 s from full).
   The host sends OFF when it sees `tripped`. That OFF is the acknowledgment.
3. `trip` then sends a new on-command. The dimmer must refuse it: `tripped` stays set.
4. The OFF came before the cool-down. The dimmer must remember it. `tripped` must clear at about
   the trip time plus the `budget_s` wait that the trip read showed (about 60 s). Not before.
5. After the clear, a new on-command must be accepted: `tripped` false and `budget_s` falls.
6. `no-restart`: it streams on-commands for the whole budget, plus the cool-down. It does not read the status
   (a read that sees `tripped` makes the host send OFF). Then one read must show `tripped` set with
   `budget_s` 0: cooled and waiting for an OFF. The stream alone must not restart the lamp.
   After the read the host sends OFF, and `tripped` must clear within 4 s.
7. `reset-clears`: use it when the budget is below 118. Press the EN button on the ESP32-C3 or
   cycle its power. After about 5 s the link is back, `budget_s` is about 120 and `tripped` is clear.
   Do this with the dimmer log open too.

Write down: the `--out` JSON file, the measured times (Pico timeout, I2C loss, trip time, re-arm time),
the commits of both firmwares, and anything strange (a flickering `link_ok`, a read that fails).

Fail means: stop, do not go on to mains. Fix the cause first. A `FAIL` of `trip` or `no-restart` means the
limiter does not work as designed, so Tests 2 and 3 must wait.

## Test 1: software I2C master timing on the Pico board

Purpose: the board wires SDA to GPIO5 and SCL to GPIO6. No hardware I2C block of the RP2040 can use
that pair, so the Pico firmware drives it in software. Check that the signals fit I2C standard mode (100 kHz).

Preconditions:

- Test 0 passed. Still no mains and no lamp.
- A scope or a logic analyser (at least 8 MHz sample rate) on J5 or J8, pins 3 (SDA) and 4 (SCL),
  ground on pin 2 (GNDA). The 4.7 kohm pull-ups of the Pico board are in place and the cable is short.
- The dimmer USB log open (`log::info!` output), to read the bad frame counter.

Steps:

1. Trigger on a start condition (SDA falls while SCL is high). Capture one status read.
2. Measure the SCL frequency. Write it down.
3. Measure these against the I2C standard mode limits: start hold time (4.0 us minimum),
   stop set-up time (4.0 us minimum), SCL low time (4.7 us minimum), SCL high time (4.0 us minimum).
4. Measure the SCL and SDA rise time (30 to 70 percent of the supply). With 4.7 kohm and the cable
   capacitance it must stay below 1000 ns. Check that the logic levels reach 3.3 V.
5. Decode the frames if the analyser can. Check the address `0x2A`, the ACK bits and the CRC bytes.
6. Poll the status for 10 minutes: `uv run python3 scripts/dimmer_set.py --status` in a loop, or
   `uv run python3 scripts/dimmer_bench.py --only stable --stable-s 600`.
   Read `BAD_FRAMES` on the dimmer log before and after.
7. Old status frame after a skipped read. The dimmer keeps one status frame in its TX buffer.
   If the master skips a read, the next read gets the old frame. To provoke it:
   - Run the 1 s status polling from the Pi.
   - Pause the Pico status reads for a moment (for example stop the Pico log or hold the Pico in
     a debugger for 1 s), or on the analyser look at two consecutive status reads after a read that was skipped.
   - Change the alpha (for example 90 deg to 180 deg) and look at how many status reads pass before
     `set_alpha_deg` and `ALPHA` in the status follow.
   - A lag of one frame (about 0.5 s with the Pico 500 ms status period, 1 s on the Pi side) confirms the
     old frame. Write down the lag. The lamp is safe either way, because the deadman runs on the dimmer.

Expected readings and pass criteria:

- SCL frequency: 100 kHz or lower, and stable. Pass when it is not above 100 kHz and the timing limits hold.
- Start and stop timing: each value is inside the limits above.
- Rise time: below 1000 ns on both lines.
- Bad frames: the counter does not rise over 10 minutes. Pass when it stays still. A rising count means a noisy cable
  or bad timing.
- Old frame: not a pass or fail test. It is a measurement. Write down whether the lag exists.

Write down: the scope or analyser screenshot (SELV side only, no serial numbers in the picture),
the values above, the bad frame count before and after, the lag result.

## Test 2: mains with a small lamp

Purpose: check the zero-cross lock, the real firing angle range, the lamp power against alpha and
that the lamp is dark when it must be.

Preconditions:

- Tests 0 and 1 passed.
- A small resistive lamp, 25 to 40 W. Never the full halogen lamp first.
- The mains side behind an isolation transformer or a GFCI. A fuse in line (see the board design notes for the value).
  A second person ready to cut the plug. The enclosure is closed, the heatsink and the fuse are fitted.
- The dimmer has a certified isolated 3.3 V supply on J1 with JP1 fitted, not the laptop USB.
- Optional: a power meter on the lamp, or a true-RMS meter rated CAT III 300 V across the lamp.
- If you have no power meter: the panel and the converter on the bench, to capture a curve at each angle.

Steps:

1. Follow the bring-up order in `firmware/esp32c3-dimmer/README.md`,
   step 3, with the lamp on J3. Switch the lamp off in the firmware first (the lamp is off after boot).
2. Apply the mains. The lamp stays dark.
3. `uv run python3 scripts/dimmer_bench.py --mains --only mains-lock`. Type the confirmation line when asked.
   Expect `mains` true and `locked` true. Read the mains frequency from the dimmer log: about 50 Hz.
4. `--mains --only mains-range`. It sets 10, 30, 60, 90, 120, 150 and 170 deg, one at a time, each in
   a short window with OFF between them. Expect `applied_alpha_deg`
   equal to the requested angle between about 25 and 153 deg.
   Outside that range the firmware limits the delay, so the applied angle stops at about 25 or 153 deg.
   Write down every pair.
5. Alpha sweep and lamp power. Use short windows (10 s or less) at, for example, 30, 60, 90, 120 and 150 deg:
   `uv run python3 scripts/dimmer_set.py --alpha 90 --hold --max-on-s 10`.
   - With a power meter: write down the power at each angle. Divide by the power at full on. Compare with
     `lamp_power_fraction(alpha)` from `mpp_sdk.io.dimmer`. Use the applied angle, not the requested one.
   - Without a power meter: use the panel short-circuit current as a light sensor. Capture a curve in the
     workbench at each angle (one window per curve). Compare Isc against alpha with `lamp_power_fraction`.
     Isc rises with light, but not strictly in proportion, so use it only to check the shape and the order.
6. `--mains --only mains-dark`. At 180 deg the lamp must be dark. When the holder process is killed,
   the lamp must be dark within about 4 s. Answer the question about the lamp. You must really look at it.

Expected readings and pass criteria:

- `mains` true, `locked` true, frequency about 50 Hz.
- Applied angle equal to the requested angle inside about 25 to 153 deg, never outside 24 to 154 deg.
- Lamp power falls as alpha rises and is near `lamp_power_fraction` (write down the difference).
- Lamp dark at 180 deg, and dark after the keepalive stops.
- No fuse blown, no heat or smell, `bad_frames` quiet on the dimmer log.

Write down: the pairs requested and applied, the power or Isc at each angle, the frequency, the lamp
and the protection used, and the lamp state in the dark checks.

If a check fails, cut the mains first. Do not go on to Test 3.

## Test 3: full halogen lamp with the panels

Purpose: see the real use: the full lamp lights the panels in short windows. Learn how fast the
panels heat and cool, so that the limiter constants can be tuned.

Preconditions:

- Test 2 passed.
- The full halogen lamp (about 1 kW) is on J3. The TRIAC heatsink is fitted. The lamp is a heat source:
  keep it away from anything that burns, with a stand that does not move.
- The panels sit at the planned distance. A second person watches the lamp and the panels.
- If you have a temperature probe: on the back of the panel, at the same place every time.
- The Pi reads the limiter state: `budget_s` shows on every `dimmer_set.py --status` line.

Steps:

1. Record the panel temperature before the first window.
2. Open a short window (10 s or less): `uv run python3 scripts/dimmer_set.py --power 0.5 --hold --max-on-s 10`.
   Capture a curve inside it if the workbench is ready. Never use a window longer than needed.
3. Record the panel temperature at the end of the window and again 30 s, 60 s and 120 s after the lamp is off.
   This shows how fast the panels cool when the lamp is off.
4. Repeat with a longer window (20 s, then 30 s) only if the temperature rise is small.
   Write down the `budget_s` before and after each window.
5. Leave the lamp off for at least 2 minutes between series. The lamp is never on while you wait.

Expected readings and pass criteria:

- The lamp follows the angle and is off after each window.
- The panel temperature rise per window is small enough that the next curve is still comparable.
- `budget_s` falls during a window and rises after it, as in Test 0.
- Pass when nothing overheats, the lamp is always off after a window, and the temperature data exist.

Write down: the temperature before and after each window and at 30, 60 and 120 s of cooling,
the window lengths and angles, the distance, the room temperature and the `budget_s` values.
The owner uses the data to tune `EXPOSURE_MAX_ON_MS` and `EXPOSURE_RESUME_MS` in
`firmware/dimmer-link/src/lib.rs` (see [dimmer_link.md](dimmer_link.md)).

## Results table

Copy this table for each session.

| Test | Check | Result | Measured value | Date | Operator | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | link | | | | | |
| 0 | alpha | | | | | |
| 0 | stable | | | | | |
| 0 | host-timeout | | time to 180 deg: | | | |
| 0 | i2c-unplug | | time to link_ok false: | | | |
| 0 | spi-unplug | | | | | |
| 0 | deadman | | | | | |
| 0 | budget-fall / budget-rise | | rates: | | | |
| 0 | trip | | trip time, re-arm time: | | | |
| 0 | no-restart | | | | | |
| 0 | reset-clears | | | | | |
| 1 | SCL frequency | | kHz: | | | |
| 1 | start, stop, rise time | | | | | |
| 1 | bad frames, 10 min | | before, after: | | | |
| 1 | old frame after a skipped read | | lag: | | | |
| 2 | mains and lock | | Hz: | | | |
| 2 | applied angle range | | | | | |
| 2 | lamp power against alpha | | | | | |
| 2 | dark at 180 and after keepalive stop | | | | | |
| 3 | short windows | | | | | |
| 3 | panel temperature and cooling | | | | | |

Use the session template `dimmer-bench` for the same list in the workbench.

## What this does not prove

- Nothing here ran on hardware yet. The limits and times in this page are the design values, not measured values.
- A pass of Test 0 does not prove the lamp is safe on mains. It proves the logic with no mains.
- The limiter counts commanded on time, not real power or real temperature. It does not tell how hot the
  panels or the lamp are.
- The limiter does not cover a stalled dimmer main loop. A stalled loop stops the limiter and the
  2 s deadman too. A task watchdog is a later item.
- The script cannot read the mains frequency or the dimmer `BAD_FRAMES`: the SPI reply does not carry them.
- The SPI-unplug check cannot tell a lost SPI link from a host timeout.
- The power of the lamp against alpha is a model (`lamp_power_fraction`, resistive lamp). A real lamp is not a
  pure resistor when cold, and the TRIAC adds leakage at low power.
- Short windows on a small lamp do not show what a long run with the full lamp does to the panels.
- One session is one sample. Repeat the checks on another day before you trust the numbers.
