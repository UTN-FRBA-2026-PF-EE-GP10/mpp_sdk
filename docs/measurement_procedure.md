# Measurement procedure

A checklist for running a bench measurement session: capturing one curve,
running a tilt-sweep series, and (once you have a board) a closed-loop
run. See `README.md`'s Quickstart to install the `web` extra first.

## Before you start

- [ ] Board wired and powered. See `firmware/pipico_board/README.md`'s
  "GPIO Assignments" section for the pinout.
- [ ] Firmware flashed with `FIRMWARE_MODE = MppTracker` (the default -
  check `firmware/pipico_board/src/main.rs` if unsure).
- [ ] Panel(s) connected and getting light. A sweep on a dark panel
  aborts - see `firmware/pipico_board/README.md`'s "Curve tracer" section,
  "Auto-range", for why.
- [ ] `mpp-sdk curve-tracer-web` running (real board), or
  `mpp-sdk curve-tracer-web --demo` (practice run, any machine, no board -
  useful for rehearsing this checklist first).

## Capture one curve

1. Open `http://<pi-host>:8000/` (or `http://localhost:8000/` for
   `--demo`).
2. In the grid of measurement-kind cards, select **baseline** (or whatever
   kind matches this capture - see "The tilt-sweep procedure" below for
   `tilt-sweep`).
3. Click **Start Measurement**. Wait for the curve to finish plotting - a
   few seconds, since the sweep auto-ranges and takes 20 points.
4. Fill in the save form: a **label** (a short description - suggest a
   convention like `"<date> <condition>"`, e.g.
   `"2026-09-08 baseline lamp 30cm"`) and optional **notes** (lamp
   distance, ambient light, anything unusual). Leave each panel's tilt
   field at its physical resting angle (0 degrees if flat).
5. Click **Save curve**. Confirm it appears in the table below.

## The tilt-sweep procedure

**Why**: a tilt-sweep is a series of curves at the same illumination with
one panel's tilt angle varied. It lets `mpp-sdk compare-measured` (see
`docs/methodology.md`'s "Measured curves" section) grade an algorithm's
partial-shading behavior against a real, physically varying array shape
instead of an inferred one.

**Convention** (a starting point, not a hard rule): sweep the same panel
through a fixed set of angles - `0, 15, 30, 45, 60` degrees is a
reasonable spread, adjusted to what the mounting hardware can hold
steady. Keep every other condition (lighting, the other panel's tilt)
constant across the whole series. Use the same label prefix for the
whole series with the angle appended, e.g.
`"2026-09-08 tilt-sweep 30deg"`, so the saved-curves table stays readable.

**Procedure**: repeat "Capture one curve" once per angle, with two
changes each time: physically set the panel to the next angle before
clicking **Start Measurement**, and select the **tilt-sweep** card (not
**baseline**) so the save request's measurement kind matches, and set
that panel's tilt field to the actual angle used - the tilt field is what
grouping and analysis code reads, not just the label text.

**After the series**: run `mpp-sdk compare-measured` (see
`docs/methodology.md`) - it groups saved curves by measurement kind, so a
consistently labeled tilt-sweep series shows up together automatically.

## Where the files land

Captured curves live under `data/curves/`, one JSON file per sweep
(git-ignored - see `data/README.md`). Closed-loop runs (below) live under
`data/runs/`. Both directories can be overridden per-process
(`MPP_SDK_CURVE_DIR`, `MPP_SDK_RUN_DIR`) - see `data/README.md` if you
need that.

## Closed-loop runs

A run drives the SEPIC continuously with a live algorithm, unlike the
curve tracer's separate, bounded bleed path. There is no on-target safety
cutoff for this beyond the duty ceiling, so `run-algorithm` adds its own
client-side abort if a reading ever exceeds 40 V or 1 A.

1. `uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check`.
   By default this also sweeps and saves a ground-truth curve first
   (skip that with `--no-sweep --curve <path>` to reuse an existing
   capture). Prints a summary (steps captured, whether it aborted, the
   final V/I/D) and saves a run under `data/runs/`.
2. `uv run mpp-sdk plot-run` (with no argument, plots the most recent
   run). Produces a figure with the P-V curve and the run's trajectory
   overlaid (colored by time), plus V/I/P time series.

Other flags: `--v-max`/`--i-max` (override the 40 V/1 A default limits),
`--bus`/`--device`/`--speed-hz` (SPI settings, same defaults as the other
hardware scripts). Run `mpp-sdk run-algorithm --help` /
`mpp-sdk plot-run --help` for the full list.
