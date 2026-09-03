# Data

- `data/plecs/` — generated simulation reference curves (panel I-V lookup
  tables for the PLECS plant-vs-plant comparison). Not measured data; see
  `data/plecs/README.md`.
- `data/bench/` — where measured bench data (e.g. plan 003's duty-sweep
  CSVs) will land, one CSV per run.
- `data/curves/` — captured curve-tracer sweeps, one JSON file per sweep,
  written by `mpp_sdk.curves.library.save`. Git-ignored: this is operator
  measurement data, not repo content. Each file holds `schema`,
  `captured_at`, `label`, `measurement` (grouping key: `baseline`,
  `partial-shade`, `tilt-sweep`, `dimmer`, `other` - see
  `mpp_sdk/curves/record.py`'s `MEASUREMENT_KINDS`), `panels` (id + tilt
  per panel in the array), `notes`, and `points` (`v`/`i` pairs in
  volts/amps, ordered as swept). See `mpp_sdk/curves/record.py` for the
  full schema and `mpp_sdk/curves/library.py` for the file layout.

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
