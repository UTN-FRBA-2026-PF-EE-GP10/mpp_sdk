# Data

- `data/plecs/` - generated simulation reference curves (panel I-V lookup
  tables for the PLECS plant-vs-plant comparison). Not measured data; see
  `data/plecs/README.md`.
- `data/bench/` - bench measurements, one CSV per run, written by
  `scripts/duty_sweep.py` (columns: duty, V in, I in, V out from the ADC,
  V out from the meter, sample count, load in ohms). 2026-09-19, 10 Ohm
  load, supply on the input:
  - `duty_sweep_10R_20260919T154546Z.csv` - D 0 to 0.45 at 5 V in. From
    D = 0.30 up, V out runs ~0.3-0.4 V below `V_in * D / (1 - D)` (the
    output diode drop); below that the gap shrinks, and at D = 0.05 V out
    is slightly above the ideal ratio. Efficiency rises from 43 % at
    D = 0.10 to 82 % at D = 0.45 (1.3 W in).
  - `duty_hold_D045_5Vin_10R_20260919.csv`,
    `duty_hold_D040_12Vin_10R_20260919.csv` - long holds with the meter
    reading typed in: ADC 3.221 V against 3.2 V, and 7.006 V against
    7.00 V (86 % efficiency at 5.7 W in).
- `data/curves/` - captured curve-tracer sweeps, one JSON file per sweep,
  written by `mpp_sdk.curves.library.save`. Git-ignored: this is operator
  measurement data, not repo content. Each file holds `schema`,
  `captured_at`, `label`, `measurement` (grouping key: `baseline`,
  `tilted`, `dimmed`, `other` - see
  `mpp_sdk/curves/record.py`'s `MEASUREMENT_KINDS`), `panels` (id + tilt
  per panel in the array), `notes`, `source` (provenance: `hardware`,
  `firmware-replay`, `simulated`, or `unknown` - see `CURVE_SOURCES` in
  the same file), `session_id` (the session it was captured in, or
  `null`; a file written before it existed has no such key), and
  `points` (`v`/`i` pairs in volts/amps, ordered as swept). See
  `mpp_sdk/curves/record.py` for the full schema and
  `mpp_sdk/curves/library.py` for the file layout.
- `data/runs/` - captured closed-loop MPPT runs, one JSON file per run,
  written by `mpp_sdk.runs.library.save` (via `mpp-sdk run-algorithm`).
  Git-ignored, same reasoning as `data/curves/`. Each file holds `schema`,
  `captured_at`, `label`, `algorithm`, `curve_ref` (paired curve's
  filename under `data/curves/`, or `null`), `aborted`, `notes`, `source`
  (provenance: `hardware`, `simulated`, or `unknown` - see `RUN_SOURCES`
  in the same file), `session_id` (as for curves), and `samples`
  (`t`/`v`/`i`/`d` per control step). See `mpp_sdk/runs/record.py` for the
  full schema.
- `data/sessions/` - bench sessions, one JSON file per session, written
  by `mpp_sdk.sessions.library`. Git-ignored, same reasoning as
  `data/curves/` and `data/runs/`. A session is a filled-in copy of a
  template (`mpp_sdk/sessions/templates/*.json`, shipped with the SDK,
  not user data): setup fields, a checklist of steps with a status and,
  where relevant, a value and linked curve/run ids, and open questions
  with their answers. Unlike curves and runs, a session is mutable -
  edited over the course of a session via `mpp_sdk.sessions.library.update`
  - so its filename never changes once created. See
  `mpp_sdk/sessions/record.py` for the full schema. This directory used
  to be named `data/reports/` - if that directory still exists on your
  disk, it is no longer read; move its files under `data/sessions/` (or
  delete them) at your convenience.

## Before committing any measured file

Per `AGENTS.md`'s "What not to commit": scrub location/serial metadata
first.

- Binary captures (scope screenshots, photos): strip EXIF/GPS
  (`exiftool -all= <file>`).
- CSV/text logs: review the header and any embedded metadata for lab
  network paths, internal hostnames, GPS coordinates, or serials tied to a
  physical location, and remove them before committing.

Document what was scrubbed (and how) in a short note alongside the data,
same as `data/plecs/README.md` documents its generation.
