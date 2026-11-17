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

Setup facts:

- The array is two panels and a lamp. Light travels from 180 degrees
  toward 0 degrees. 90 degrees is vertical and faces the light, so 90 is
  the untilted reference, not zero.
- Panel A is fixed at 90 degrees. It is the unshaded reference.
- Panel B moves on a mount with five detents: 90, 70, 60, 45, 30 degrees.
  A lower number tilts B further from the light, so it gets less light.
- One tilted capture and a full sweep of angles are the same setup. Both
  use one measurement kind, `tilted`. `mpp-sdk compare-measured` (see
  `docs/methodology.md`, "Measured curves") then grades an algorithm on a
  real partial-shading curve.

For a sweep of angles, repeat "Capture one curve" for each angle:

1. Set panel B to the next detent by hand.
2. Select the **Tilted** tab, not **Baseline**.
3. Click **Start Measurement**.
4. In the save form, pick the same angle for panel B. The selector allows
   only the five detents.
5. Use one label prefix for the series, with the angle added, for example
   `"2026-09-08 tilted 45deg"`.
6. Keep the lighting and panel A the same for the whole series.
7. Sweeps run back-to-back. See the Safety section about the Q3 heatsink.

After the series, run `mpp-sdk compare-measured`. It groups saved curves
by measurement kind, so the series shows up together.

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

- A curve or run step can ask for more than one repeat, for example 3
  curves one after the other. The step shows "2 / 3 repeats".
- With two or more linked, the workbench shows median, mean, standard
  deviation, min and max. For curves: Voc, Isc, P at MPP. For runs: held
  power, P over MPP_th, time to converge.
- With one linked, it shows that value alone.

### Printing and downloads

- **Expand all** opens every linked chart. Use it before you print
  (Ctrl+P or Cmd+P). The workbench also expands them when the print
  dialog opens. **Collapse all** closes them.
- **Download JSON** saves the session record.
- **Download Markdown** saves a readable summary: each step, its value and
  notes, and the statistics.
- Both downloads hold the session alone, without the linked curves and
  runs.

## Sharing a session file

A session file bundles curves and runs, and optionally the session, into
one file. Someone else can open it with no board and no saved library.

Export from a session:

1. Open the session and click **Export session file**.
2. The file holds the session record and every linked curve and run. A
   linked item that was deleted is listed as missing.

Export loose curves or runs:

1. In **Curves** or **Runs**, click **Select** and tick the items.
2. Click **Export N selected** and type a title. The title is the file
   name. The file holds no session.

The browser downloads `<title>.mppsession.json`.

Open a file:

1. Start `mpp-sdk curve-tracer-web --demo` on any machine.
2. Click **Open session** in the header, or drag the file onto the page.
3. A **Viewing: `<title>`** banner shows. Click **Close** to leave.

While you view a file:

- Capture, starting a run, deleting and remeasuring are off. Nothing is
  sent to a server.
- Curve and run views work as usual. The player reads the run samples from
  the file.
- **View session** opens the session read-only, if the file has one.

A bad file (wrong format, too large, corrupted) shows an error. The current
view stays as it was.
