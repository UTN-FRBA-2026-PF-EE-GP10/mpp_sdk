# Plan 041: Workbench guide page - todo list

- **Goal**: one docs page that lets a teammate run a measurement session
  alone.
- **Rule**: every number and screenshot on the page comes from a real
  session. Not from Demo mode, not from memory.
- **Status**: IN PROGRESS. Session 1 (Luxen alone) 2026-09-22 -> page v1.
  Session 2 (panels A and B) later -> page v2.
- **Depends on**: plan 040 (Step 0 done). Session 1 also covers its Steps
  1-4.

## Session 1: Luxen LN-10P alone (2026-09-22)

Work in the workbench as a session made from the Single template. This list
adds what the plan needs and what the pre-session audit found.

Before:

- [ ] Pi power: `vcgencmd get_throttled` reads `0x0`. It read `0x50005`
      (under-voltage) on 2026-09-21: use a 5 V / 3 A supply. Low voltage can
      stall the link and abort a run as `link-down`.
- [ ] A workbench server already runs on the Pi and holds SPI and port
      8000. Reuse it (same commit as `main`) or stop it first.
- [ ] Firmware confirmed: `MppTracker`, `ADC_DIVIDER_RANGE = Low`,
      `MAX31865_ENABLED = false`. `main` is right, but only a debug probe
      shows the boot log. No commit is embedded, so write the commit you
      flashed in the session's firmware field. Jumpers JP6, JP7, JP8, JP13
      shorted (Low).
- [ ] The lamp has its own supply, not the one that feeds the Pi and the
      board. On 2026-09-21 the lamp tripped a shared regulator mid-run and
      cut the Pi and the board with it. That run and its samples were lost.
- [ ] Panel lit and on the input. One sweep: Isc below 700 mA.
- [ ] 10 Ohm, 10 W load on J4, lead secured, airflow. The load takes about
      8.6 W at the MPP.
- [ ] Meter on the converter output. Someone at the power switch.
- [ ] Browser: **Single** mode and units **A/W** (a fresh browser starts in
      Full and mA), pill **PICO connected**, light theme, zoom 100 %.
- [ ] Session created, Luxen panel model picked.

Do:

- [ ] First run: read the meter against **V out** during it. Allow about
      50 mV. Runs do not store V out.
- [ ] Baseline curve, 3 times. Link each capture right away with **Link
      most recent** (an unlinked curve is missing from the export). Do not
      use **Capture into this step** for this template.
- [ ] Runs on the curve, 10 s, start duty 0.5: P&O, InCond, Fuzzy,
      Scan&Track, PSO, 3 each. The run form resets each time: pick the
      **Reference curve** again.
- [ ] Seed test: P&O from duty 0.85 (type it in).
- [ ] Stop test: **Stop run** halfway.
- [ ] Link-down test, last: SPI cable out halfway. It must abort
      `link-down`. The UI does not show duty 0: read it on the meter, or as
      V in rising toward Voc.
- [ ] Note samples per second (plan 040 needs it).

Expect:

- MPP near D = 0.35 and V out near 10 V at label light, lower duty in
  weaker light.
- Sweeps heat Q3. Runs heat the SEPIC stage and the load, not Q3.

Keep:

- [ ] Export the session file (`.mppsession.json`). It cuts each run to
      2000 samples: download the runs from the Runs list for full traces.
- [ ] Send the file to teammates.

Screenshots (PNG, `docs/assets/workbench/sN-name.png`):

- [ ] S1 connected pill, S2 pill menu, S3 capture ready, S4 mid-sweep,
      S5 save form, S8 run form, S9 confirm dialog, S10 run live,
      S11 run done, S12 player, S13 pill red (cable out).

## Session 2: panels A and B (later)

- [ ] Bypass diode across each panel (meter in diode mode).
- [ ] ADC range `Mid`: jumpers, constant, reflash, meter check.
- [ ] 20 Ohm load (two 10 Ohm, 10 W in series).
- [ ] Light: Isc below 700 mA and power below 16.1 W with both panels.
- [ ] **Full** mode. Baseline curve. Tilted curves at B = 70, 60, 45, 30.
- [ ] On the two-peak curve: P&O, Scan&Track, PSO, then the seed test.
- [ ] Stop test. Screenshots S6 (tilt form) and S7 (tilted panes).

## The page (after each session)

- [ ] `docs/workbench_guide.md`, in `mkdocs.yml` nav, linked from
      `docs/index.md` and `docs/measurement_procedure.md`. Link the
      checklist, do not copy it.
- [ ] Each step has **Do**, **You should see**, **If not**. `!!! danger`
      before the first energized step, `!!! warning` before the first run.
- [ ] v1 sections: what you will do, what you need, safety, setup, connect,
      light check, baseline, run algorithms, compare, stop a run, Demo mode,
      if something goes wrong, next.
- [ ] v2 adds the tilted series and local against global trackers.
- [ ] `scripts/docs_workbench_figures.py`: reads the data directory, writes
      the graphs. SVG, white background, units on the axes.
  - v1: setup diagram, baseline I-V and P-V, power over time for all runs,
    duty and voltage over time, stopped run.
  - v2: tilted P-V overlay, local against global, seed test.
- [ ] Session data in `docs/assets/workbench/data/` so the graphs rebuild.

## Before committing (the repo is public)

- [ ] Crop screenshots to the page (no address bar), `exiftool -all=`.
- [ ] Labels and notes have no place names or serials.
- [ ] `grep -rE "192\.168|\.local|/home/" docs/` is empty.
- [ ] `uv run mkdocs build --strict` and markdownlint pass.
- [ ] A teammate follows the page alone, in Demo mode, then on the bench.

## Stop if

- A sweep aborts at a cutoff: reduce the light. Never raise the cutoffs.
- The first run misbehaves (noise that does not settle, hot Q3, collapsed
  voltage, duty stuck): stop, record it in plan 040. The page waits.
- No second peak in Session 2: check the bypass diodes and the tilt first.
- **V out** disagrees with the meter: do not quote its value.
