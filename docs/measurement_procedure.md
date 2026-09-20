# Measurement procedure

A checklist for running a bench measurement session: capturing one curve,
running a tilted series, and a closed-loop run. See `README.md`'s
Quickstart to install the `web` extra first.

## Safety

- **Never expose the server to the internet or an untrusted network.** It
  has no login and no access control. Anyone who can reach it can drive
  the SEPIC converter. Keep it on the bench network only, or reachable
  through a VPN.
- The curve tracer's bleed path dissipates power in Q3 (a linear
  MOSFET). Give it a heatsink and watch its temperature if you run sweeps
  back-to-back - see `firmware/pipico_board/README.md`'s "Curve tracer"
  section.
- A closed-loop run has no on-target safety cutoff besides the duty
  ceiling. The Pi side aborts the run if a reading ever exceeds the
  v_max/i_max limits, if the converter output exceeds v_out_max, or if the
  SPI link drops mid-run. This protection only exists while the
  controlling process (the workbench server, or `run-algorithm`) is
  running.
- **Always put a load on the converter output before a run** (10 Ohm,
  10 W for one panel; 20 Ohm for two). With a light or missing load the
  SEPIC output climbs far above the panel voltage.

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
   `--demo`). The workbench opens on **Measure**.
2. Check the connection pill, top right. It also doubles as the capture
   mode menu:
   - **PICO connected**: a real board, live sweeps. Use this for an
     actual measurement.
   - **Replay on the board**: a real board, but the "Replay curve" buttons
     replay a curve already stored in the firmware instead of measuring
     one. Only selectable while a board is linked.
   - **Demo**: no board at all, bundled sample data, nothing saved.
   Leave it on **PICO connected** for a real capture.
3. Under "Capturing under:", select the tab that matches this capture:
   **Baseline** here (or **Tilted** - see "The tilted-panel procedure"
   below).
4. Click **Start Measurement**. Wait for the curve to finish plotting - a
   few seconds, since the sweep auto-ranges and takes 20 points.
5. Fill in the save form: a **label** (a short description - suggest a
   convention like `"<date> <condition>"`, e.g.
   `"2026-09-08 baseline lamp 30cm"`) and optional **notes** (lamp
   distance, ambient light, anything unusual). Panel A is fixed at 90
   degrees and is not editable in the form. Leave panel B's tilt at 90
   degrees for a baseline capture (both panels matching).
6. Click **Save curve**. Confirm it appears in the "Saved curves" table
   below, and under **Curves > Baseline** in the sidebar.

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
before clicking **Start Measurement**, and select the **Tilted** tab
(not **Baseline**) so the save request's measurement kind matches. The
save form's panel B selector is restricted to the five valid detents, so
picking the wrong angle by typo is not possible - just make sure the
selected value matches where the panel physically is. Use the same label
prefix for the whole series with the angle appended, e.g.
`"2026-09-08 tilted 45deg"`, so the saved-curves table stays readable.
Keep every other condition (lighting, panel A) constant across the whole
series. Sweeps run back-to-back here - see the Safety section above about
Q3's heatsink.

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
curve tracer's separate, bounded bleed path. See the Safety section above
for what protects it.

### From the workbench

1. In **Measure**, click the **Run an algorithm** tab.
2. Pick an **Algorithm**, and optionally a saved curve as **Reference
   curve** (grades the run against it; leave it as "None" to run
   ungraded).
3. Leave **Duration** blank for the default (10 s), or set your own, up
   to the server's safety backstop (600 s). **Starting duty cycle** picks
   which maximum a local tracker hill-climbs to on a multi-peak curve.
   **v_max**/**i_max** default to 40 V / 1 A and set the abort limits.
4. Click **Start run** and confirm. This drives the real converter.
5. Watch the live V/I/duty readouts and the operating point move on the
   reference curve. Click **Stop run** to end it early.
6. When it finishes, click **Open in player** to review the saved run, or
   **Start another run**.

In `--demo` mode, or with **Demo** capture mode selected, the form starts
a *simulated* run instead (against a demo curve or a built-in reference
panel). No board is touched, and the workbench marks the result
"simulated" throughout so it is never mistaken for a measurement.

### From the command line

Useful for scripted or headless captures:

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

## Sharing a session file

Send someone your curves and runs in one file, with no board and no saved
library needed on their end.

**Export**: in **Curves** or **Runs**, click **Select**, tick the items you
want, then **Export N selected**. Type a title when asked - this becomes
the file name. The browser downloads `<title>.mppsession.json`.

**Open**: start the workbench on any machine with
`mpp-sdk curve-tracer-web --demo` (no board needed), open it in a browser,
then click **Open session** in the header, or drag the file onto the
page. The workbench switches to a read-only view of that file: a
**Viewing: `<title>`** banner appears at the top, with a **Close** button
that returns to the normal view. While viewing a session:

- Capture, starting a run, deleting, and remeasuring are all off - nothing
  in the file can be changed, and nothing is sent to a server.
- The curve and run views work the same as usual, including opening a run
  in the player - the player reads the run's samples straight from the
  file.
- No board and no saved library are needed: everything comes from the
  file.

A bad file (wrong format, too large, or corrupted) shows an error message
and leaves the current view untouched.
