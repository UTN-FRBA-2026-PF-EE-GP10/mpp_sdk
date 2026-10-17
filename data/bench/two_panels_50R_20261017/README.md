# Two panels in series, 50 Ohm load

Two curve-tracer sweeps, 15 closed-loop runs and the filled session
checklist, on the real converter. Panel B at 90 degrees (one peak) and at
45 degrees (two peaks). This is the first set where every step waits for
a settled measurement from the Pico (#130, #133).

## Setup

- Two Hissuma PSF10MONO (10 W) panels in series, halogen lamp at a fixed
  setting. Panel A stays at 90 degrees. Panel B is at 90 or 45 degrees.
- SEPIC power stage, 50 Ohm load rated 50 W or more, ADC range Mid.
- Firmware `3129c01`, Python side `1fa6bfc`. Limits: 40 V, 0.9 A, 25 V out.
- Each run step takes about 46 ms (40-95 ms): the Pico waits for Vin to
  settle and averages 17 of 25 samples.

## Files

| File | Content |
|------|---------|
| `session.json` | The session checklist (template `full-setup-characterization`), with the curves and runs linked. |
| `curve_B90.json` | B at 90 degrees. One peak, 7.69 W at 29.2 V / 0.263 A. |
| `curve_B45.json` | B at 45 degrees. Two peaks: 4.03 W at 32.2 V and 3.80 W at 14.1 V. |
| `run_<algorithm>_B90.json` | P&O, InCond, Fuzzy, Scan&Track, PSO. 10 s each, reference `curve_B90`. |
| `run_<algorithm>_B45.json` | The same five on `curve_B45`. PSO also has a 20 s run. |
| `run_po_B45_d0XX.json` | P&O on `curve_B45` from start duty 0.20, 0.25, 0.35, 0.45 (10 s) and 0.50 (30 s). |

Each file uses the record format in `mpp_sdk/curves/record.py`,
`mpp_sdk/runs/record.py` and `mpp_sdk/sessions/record.py`.

## Results

Held power is the mean over the last 30 % of a run. The percentage is
against the reference curve's best sweep point.

**B at 90 degrees, one peak (7.69 W):**

| Algorithm | Held power | Of MPP |
|-----------|-----------:|-------:|
| P&O | 7.72 W | 100 % |
| InCond | 7.70 W | 100 % |
| Fuzzy | 7.70 W | 100 % |
| Scan&Track | 7.71 W | 100 % |
| PSO | 7.74 W | 101 % |

All five track the single peak. P&O, InCond and Fuzzy started at duty
0.45 and settled at 0.35-0.40.

**B at 45 degrees, two peaks (sweep best 4.03 W):**

| Run | Start duty | Held power | Of MPP | Peak |
|-----|-----------:|-----------:|-------:|------|
| P&O | 0.20 | 4.27 W | 106 % | high-voltage (global) |
| P&O | 0.25 | 4.29 W | 106 % | high-voltage (global) |
| P&O | 0.35 | 4.29 W | 106 % | high-voltage (global) |
| P&O | 0.45 | 3.76 W | 93 % | low-voltage (local) |
| P&O, 30 s | 0.50 | 3.77 W | 94 % | low-voltage (local) |
| InCond | 0.50 | 3.77 W | 94 % | low-voltage (local) |
| Fuzzy | 0.50 | 3.72 W | 92 % | low-voltage (local) |
| Scan&Track | own scan | 4.29 W | 106 % | high-voltage (global) |
| PSO | own seed | 3.79 W | 94 % | low-voltage (local) |
| PSO, 20 s | own seed | 3.81 W | 95 % | low-voltage (local) |

- The local trackers stay on the peak nearest their start duty. From 0.35
  or lower, P&O finds the global peak; from 0.45 or higher, the local one.
- Scan&Track finds the global peak. PSO does not, in either run.
- Over 100 %: the 20-point sweep has no point between 32.2 V and 16.0 V,
  so it misses the top of the high-voltage peak. The runs show it is about
  4.29 W.

## Known limits of this data

- One sweep per tilt, not three: no spread for Voc, Isc or MPP.
- Runs are 10 s, apart from the two longer ones. A 30 s run shows the
  steady state better.
- The two zero samples in each Scan&Track run are real: its scan goes to
  duty 0.9, where the panel voltage is near 0 V.
- Panel temperature was not measured.
- Earlier runs in the same session are not included. They logged 0 V / 0 A
  for held duties (fixed in #133). While a debug-probe log monitor stayed
  attached, about 1 in 10 host frames also failed the CRC and the duty did
  not follow the algorithm. Detaching the probe fixed it. #134 hardens the
  firmware against lost duty frames; it was not flashed for these runs.

## What was removed

Time stamps are cut to the date. Labels are rewritten. Notes in the curve
and run files are empty. Session ids are null, and the session id is
`session`. Linked ids are rewritten to the file names here. The operator
field is empty. Nothing names a place, a host or a person.
