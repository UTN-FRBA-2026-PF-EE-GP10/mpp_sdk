# Measurement procedure

A checklist for running a bench measurement session: capturing one curve,
running a tilted series, and (once you have a board) a closed-loop run.
See `README.md`'s Quickstart to install the `web` extra first.

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
   kind matches this capture - see "The tilted-panel procedure" below for
   `tilted`).
3. Click **Start Measurement**. Wait for the curve to finish plotting - a
   few seconds, since the sweep auto-ranges and takes 20 points.
4. Fill in the save form: a **label** (a short description - suggest a
   convention like `"<date> <condition>"`, e.g.
   `"2026-09-08 baseline lamp 30cm"`) and optional **notes** (lamp
   distance, ambient light, anything unusual). Panel A is fixed at 90
   degrees and is not editable in the form. Leave panel B's tilt at 90
   degrees for a baseline capture (both panels matching).
5. Click **Save curve**. Confirm it appears in the table below.

## The tilted-panel procedure

**Why**: this bench's array is two panels and a lamp. The light travels
from 180 degrees toward 0 degrees; 90 degrees is vertical and faces the
light squarely, so 90 is the *untilted* reference, not zero. Panel A is
always fixed at 90 degrees - it is the unshaded reference panel and is
never adjusted. Panel B is the one that moves, on a mount with five fixed
detents: 90, 70, 60, 45, 30 degrees. Lower numbers tilt panel B further
right, away from the light, so it receives less illumination. A single
tilted capture and a full sweep across panel B's angles are the same
physical setup, just one point or several - hence one measurement kind,
`tilted`, for both. It lets `mpp-sdk compare-measured` (see
`docs/methodology.md`'s "Measured curves" section) grade an algorithm's
partial-shading behavior against a real, physically varying array shape
instead of an inferred one.

**Procedure for a sweep**: repeat "Capture one curve" once per angle,
with two changes each time: physically set panel B to the next detent
before clicking **Start Measurement**, and select the **tilted** card
(not **baseline**) so the save request's measurement kind matches. The
save form's panel B selector is restricted to the five valid detents, so
picking the wrong angle by typo is not possible - just make sure the
selected value matches where the panel physically is. Use the same label
prefix for the whole series with the angle appended, e.g.
`"2026-09-08 tilted 45deg"`, so the saved-curves table stays readable.
Keep every other condition (lighting, panel A) constant across the whole
series.

**After the series**: run `mpp-sdk compare-measured` (see
`docs/methodology.md`) - it groups saved curves by measurement kind, so a
consistently labeled tilted series shows up together automatically.

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
