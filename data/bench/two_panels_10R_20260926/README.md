# Two panels in series, 10 Ohm load

Three curve-tracer sweeps and one closed-loop Perturb & Observe (P&O) run
on the real converter. Use them to test the loaders, `MeasuredPanel` and
the harness on measured data. Read "What failed" first: the run data has
known faults.

## Setup

- Two 10 W panels in series (Voc about 34 V, Isc about 0.37 A), one lamp.
  Panel A stays at 90 degrees. Panel B is at 90, 60 or 30 degrees.
- SEPIC power stage, 10 Ohm, 10 W load on the output, RP2040 firmware over
  SPI, Raspberry Pi host.
- Light is set so the strongest curve peaks at 10 W. The 10 W load is at
  its rating there: keep the light lower for longer sessions.

## Files

| File | Content |
|------|---------|
| `curve_B90.json` | Baseline, B at 90 degrees. One peak, 10.0 W at 29 V. |
| `curve_B60.json` | B at 60 degrees. Two peaks: 6.35 W at 30 V and 4.75 W at 14 V. |
| `curve_B30.json` | B at 30 degrees. Two peaks: 4.74 W at 14 V and a weak 1.8 W at 32 V. |
| `run_po_on_curve_B90.json` | P&O, 10 s, start duty 0.5, reference `curve_B90`. |

Each file uses the record format in `mpp_sdk/curves/record.py` and
`mpp_sdk/runs/record.py`.

## What was removed

Time stamps are cut to the date. Labels are rewritten. Notes are empty.
Session ids are null. File names carry no time. Nothing names a place, a
host or a person.

One correction: the workbench saved the 30 degree curve with panel B at 90
degrees, because the tilt form was not filled in. The tilt is set to 30
here.

## What failed

**Corrupted readings.** The run loop sometimes reads impossible values, such
as 58 A or 45 V from a panel that cannot give more than 0.4 A. A failed SPI
frame makes the host replay the last good reading, so one bad frame repeats
for several steps. The rate was 3 to 4 events per second at about 1500
samples per second. It appeared with one panel and with two, in the Full
and Low ranges, at low and at high light.

- With the stock loop, this aborted many runs as `overcurrent`,
  `overvoltage` or `output-overvoltage`, all within 1.5 s.
- Fix used for the shared run: abort only when 5 readings in a row, over at
  least 50 ms, break a limit. Aborts stopped. The corruption did not.
- Bad readings that stay inside the limits still reach the algorithm and
  the saved run. In `run_po_on_curve_B90.json`, 21 of 15626 samples are off
  the curve, for example 33.6 V with 0.345 A (11.6 W on a 10 W curve).
- Cause not proven. An earlier session ran at about 630 samples per second.
  The runs checked from it have no such samples. The host reported supply
  under-voltage then, which slows its CPU. A loop that is too fast for the Pico, or interference on
  the SPI wires, are the two leads. A pause of about 1.6 ms per step is the
  first test.

**P&O tracking.** The run holds 7.5 W over its last 30 %, which is 75 % of
the 10.0 W the curve allows. The duty moves between 0.07 and 0.51 and does
not settle. The step is 0.005 per sample, at about 1500 samples per second,
and the converter needs tens of milliseconds to respond. Start duty 0.5 also
puts the panel near short circuit, because the 10 Ohm load reflects as 10
Ohm at duty 0.5. The MPP duty is about 0.25 (estimate from the curve).

**InCond and Fuzzy (earlier session, one panel, not in this data).** Both
drove the duty to its 0.05 floor within 0.6 s and held 0.5 to 0.9 W of about
5 W. Likely cause, not tested: the readings repeat exactly, so the voltage
change is 0 and the algorithm holds, and its decisions come faster than the
converter responds.

**Setup errors that cost time.**

- The firmware ADC range constant must match the jumpers. With a mismatch
  the on-chip ADC reads 32 % low, and the output voltage is wrong. The
  input voltage comes from the INA229 and stays correct.
- The 10 W load limits the power to about 8 W. At full light, two panels
  give about 20 W.
- The curve tracer aborted twice with "Voc below 500 mV, no panel to
  sweep". Both cleared on the next attempt. Cause not found (contact or
  relay).
- The workbench run form resets the reference curve and the start duty
  after each run. Several runs were saved with no reference curve.
