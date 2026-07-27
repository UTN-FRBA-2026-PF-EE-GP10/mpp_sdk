# Data

- `data/plecs/` — generated simulation reference curves (panel I-V lookup
  tables for the PLECS plant-vs-plant comparison). Not measured data; see
  `data/plecs/README.md`.
- `data/bench/` — where measured bench data (e.g. plan 003's duty-sweep
  CSVs) will land, one CSV per run.

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
