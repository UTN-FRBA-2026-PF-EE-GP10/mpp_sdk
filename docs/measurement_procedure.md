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
- A closed-loop run has few on-target cutoffs. The firmware sets duty to
  0 when:
  - the Pi sends no frame for about 500 ms,
  - the Pi sends only frames that fail their CRC for 500 ms,
  - the INA229 gives no new reading for 50 ms,
  - the panel current or a voltage goes above the hardware cutoff (default
    1.0 A and 40 V). The cutoff latches; clear it with "Reset Tripped
    Cutoff" in the workbench. A host can only lower these limits.

  The Pi side aborts the run when readings stay above v_max/i_max, when
  the converter output stays above v_out_max, or when the SPI link drops.
  This protection works only while the controlling process (the workbench
  server, or `run-algorithm`) runs.
- **Always put a load on the converter output before a run.** With a
  light or missing load the SEPIC output climbs far above the panel
  voltage.
- Choose the load from the panel curve:
  - The panel looks like `R_in = Vmp / Imp` at its MPP. A load near that
    value puts the MPP near duty 0.5. Two Hissuma panels in series are
    about 80 Ohm.
  - Output voltage is about `sqrt(P x R_load)`. Keep it below v_out_max
    (25 V), or the run aborts. At 80 Ohm that means less than about 7 W.
  - Keep the panel power below 80 % of the resistor rating.

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

## Start the workbench at boot (optional)

Run this once on the host SBC, from the repo checkout:

```bash
scripts/install_workbench_service.sh
```

- It installs and starts the `mpp-workbench` systemd service. The server
  then starts at every boot, with no PC and no ssh session.
- Open `http://<host-ip>:8000/` from any device on the bench network, for
  example a phone.
- The server does not need the Pico at start. The connection pill shows
  an error until the board answers, then changes to **PICO connected**.
- Nothing drives the converter until you start a sweep or a run.
- Stop the service before you start the server by hand. Both use port
  8000 and the SPI link.

| Task | Command |
| --- | --- |
| Status | `systemctl status mpp-workbench` |
| Log | `journalctl -u mpp-workbench -f` |
| Restart (after `git pull` and `uv sync`) | `sudo systemctl restart mpp-workbench` |
| Stop until next boot | `sudo systemctl stop mpp-workbench` |
| Remove | `scripts/install_workbench_service.sh --remove` |

## Capture one curve

1. Open `http://<host-ip>:8000/` (or `http://localhost:8000/` for
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
   **v_max**/**i_max**/**v_out_max** default to 40 V / 0.9 A / 25 V and set
   the abort limits. A limit aborts the run only when readings stay above
   it for 5 readings in a row and at least 50 ms; a shorter streak is
   treated as a bad reading and skipped.
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

Other flags: `--v-max`/`--i-max`/`--v-out-max` (narrow the 40 V / 0.9 A /
25 V default limits),
`--bus`/`--device`/`--speed-hz` (SPI settings, same defaults as the other
hardware scripts). Run `mpp-sdk run-algorithm --help` /
`mpp-sdk plot-run --help` for the full list.

## Bench sessions

A session is a checklist for one bench session: setup fields, a list of
steps with a status, and curves and runs linked to those steps. A curve
or run links into a step - it is never copied - so a session always shows
the current state of your saved library.

### Start a session

1. In the sidebar, open **Sessions** and click **New session**.
2. Pick a template. The workbench suggests the one that matches your
   current setup mode (Single or Full).
3. Type a title, e.g. "Panel A alone under the lamp". Fill in the setup
   fields - panel model, light source, load, ADC range - where they
   differ from the defaults.
4. Click **Create session**. The workbench opens the new session.

### Fill in steps

Each step has a status: **todo**, **done**, **failed**, or **skipped**.
Set it from the dropdown next to the step. Steps come in four kinds:

- **Check**: mark it done once you have verified something, e.g. firmware
  configuration.
- **Number** or **text**: type a value, e.g. Voc read off the panel label.
- **Curve**: link one or more saved curves. Pick one from the list, or
  click **Link most recent curve** right after you save one.
- **Run**: link one or more saved runs, the same way.

Notes are free text under each step, for anything the checklist itself
does not capture.

### Repeats and statistics

A curve or run step can ask for more than one repeat, e.g. "3 curves, one
after the other"). The step shows how many are
linked against how many are asked for, e.g. "2 / 3 repeats". Once two or
more are linked, the workbench shows the median, mean, standard
deviation, min, and max for each number that matters: Voc, Isc, and P at
MPP for curves; held power, P over MPP_th, and time to converge for runs.
With only one linked, it shows that value alone, with no spread.

### Printing and downloads

**Expand all** opens every linked curve's and run's chart at once - do
this before printing (Ctrl+P/Cmd+P), though the workbench also expands
them on its own when the print dialog opens, so nothing is missing from
the printout. **Collapse all** puts them back.

**Download JSON** saves the session record as-is. **Download Markdown**
saves a readable summary: every step, its value and notes, and the
statistics above, as plain text - paste it into a lab notebook or a PR
description. Both downloads hold the session alone, without the curves
and runs it links.

## Sharing a session file

A session file bundles curves and runs (and, from a session, the session
itself) into one file, so someone else can open the workbench with no
board and no saved library and still see the whole picture.

**Export from a session**: open the session, click **Export session
file**. The file holds the session record plus every curve and run its
steps link. A linked curve or run since deleted from the library is
listed as missing in the file, rather than silently left out.

**Export loose curves or runs**: in **Curves** or **Runs**, click
**Select**, tick the items you want, then **Export N selected**. Type a
title when asked - this becomes the file name. This file holds no
session; it is exactly the curves or runs you picked.

Either way, the browser downloads `<title>.mppsession.json`.

**Open**: start the workbench on any machine with
`mpp-sdk curve-tracer-web --demo` (no board needed), open it in a browser,
then click **Open session** in the header, or drag the file onto the
page. The workbench switches to a read-only view of that file: a
**Viewing: `<title>`** banner appears at the top, with a **Close** button
that returns to the normal view. While viewing an imported session:

- Capture, starting a run, deleting, and remeasuring are all off - nothing
  in the file can be changed, and nothing is sent to a server.
- The curve and run views work the same as usual, including opening a run
  in the player - the player reads the run's samples straight from the
  file.
- If the file carries a session, **View session** opens it read-only, the
  same document view as a live session, fed entirely from the file - no
  board and no saved library needed.

A bad file (wrong format, too large, or corrupted) shows an error message
and leaves the current view untouched.
