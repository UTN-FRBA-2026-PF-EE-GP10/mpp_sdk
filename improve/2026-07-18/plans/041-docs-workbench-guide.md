# Plan 041: One-page guide - the full two-panel setup with the workbench

> **Executor instructions**: **Part A is bench work** that only an operator
> at the bench can do: it produces the data and the screenshots. **Part B
> writes the page** from those, and any agent can do it. Do not write Part B
> from memory or from Demo mode: every number and every screenshot on the
> page must come from the Part A sessions.

## Status

- **Priority**: P1 - the workbench does everything the thesis needs, but
  only the people who built it know how to drive it.
- **Effort**: L (two bench sessions, and the page in two versions).
- **Schedule**: **Session 1, panel A alone: Saturday 2026-09-19** -> page
  v1. **Session 2, panels A and B: the week after** -> page v2.
- **Risk**: LOW for the page. Part A drives the real converter at the full
  two-panel voltage: it carries plan 040's risks and follows its safety
  rules.
- **Depends on**: plan 040 Step 0 (meter check of `ADC_VOUT`) before the
  page quotes any output voltage. Session 1 can double as plan 040 Steps
  1-3.
- **Category**: documentation.
- **Planned at**: 2026-09-18, after PRs #98-#101 landed.

## Why this matters

`docs/measurement_procedure.md` is a checklist for someone who already
knows the workbench. No page takes a new person from "two panels and a
board on the desk" to the thesis's actual experiment: a baseline curve, a
tilted series that emulates partial shading, and algorithm runs on each,
with the graphs to read the results. The goal is one page in the docs site
(MkDocs Material, published to GitHub Pages) that a teammate can follow
alone and get the same result.

## The setup the page describes

- **Two panels, A and B, in series** on the board's input, one bypass
  diode across each panel.
- **Panel A fixed at 90°** (facing the light squarely). **Panel B tilted**
  through 90, 70, 60, 45 and 30 degrees (`PANEL_B_TILT_OPTIONS_DEG` in
  `frontend/src/types.ts`). Equal tilts are the **Baseline** kind; any B
  below 90 is the **Tilted** kind.
- Why tilting B matters: B then delivers less current than A. With a bypass
  diode across B, the string's P-V curve gets **two peaks**. A local
  tracker (P&O, InCond, Fuzzy) can settle on the lower one; a global
  tracker (Scan&Track, PSO) should find the higher one. That comparison is
  the result the page leads the reader to.

## Limits that change with two panels (verified in the code)

| Limit | Value | Where | Consequence |
|-------|-------|-------|-------------|
| On-chip ADC full scale, `Low` range | ~27.3 V | firmware README, divider table | Two panels reach ~34 V open circuit. **Switch the jumpers and `ADC_DIVIDER_RANGE` to `Mid` (~51.5 V)** before the first two-panel sweep, or `ADC_PWR`/`ADC_VOUT` saturate. |
| Curve-tracer current cutoff | 700 mA | `TRACER_I_MAX_MA`, `firmware/safety-checks/src/lib.rs` | The panels' datasheet Isc is 0.79 A. In strong light the sweep aborts. |
| Curve-tracer power cutoff | 16.1 W | `TRACER_P_MAX_MW`, same file | Two panels are rated 20 W. Weaker than full sun is required. |
| Run limits (defaults) | 40 V / 1 A | `scripts/curve_tracer_server.py` | Covers ~34 V Voc. Do not raise them. |

So: **the light must stay below about 0.7 A and 16 W at the panels.** The
first action of every session is one sweep at low light to check this,
before anything else.

## Part A: the bench work (operator)

### Session 1: panel A alone (Saturday 2026-09-19) -> page v1

Panel A alone on the input. This is also the first closed-loop run on the
real converter (plan 040 Steps 0-4): go slowly, and treat any abort as a
finding.

#### Session 1 setup

- [ ] Panel A alone on the input, facing the light squarely.
- [ ] ADC range stays **`Low`** (~27.3 V full scale covers one panel's
      ~17-19 V). The boot log prints the range.
- [ ] Firmware on `main`: `FIRMWARE_MODE = MppTracker`,
      `MAX31865_ENABLED = false`. The log shows V and I every second and
      `T=n/a`.
- [ ] Server on `main`; the pill reads **PICO connected**.
- [ ] **Light below 700 mA**: one panel's datasheet Isc (0.79 A) is above
      the tracer's cutoff, so use the lamp or weak sun (power is not a
      limit for one panel: ~10 W against 16.1 W). Record the source,
      setting, distance, or time and sky.
- [ ] Heatsink on Q3, or keep runs short. Someone able to cut power.
- [ ] A multimeter for Step 0.
- [ ] Browser at desktop width, **light theme**, units **A/W**, zoom 100 %.

#### Session 1 steps

0. **Meter check (plan 040 Step 0).** At a fixed duty, compare the meter
   on the converter output with the **V out** readout. Write down both.
1. **Light check.** One sweep. Isc must read below 700 mA; if not,
   reduce the light.
2. **Curve.** Save it as **Baseline** (the panel fields describe the
   two-panel rig; with A alone, write "panel A alone" in the notes).
3. **First run.** **P&O**, 10 s, starting duty 0.5, the curve as
   **Reference curve**, default limits. Watch the bench, not the screen.
4. **Same curve, the other algorithms.** InCond, Fuzzy, Scan&Track and PSO,
   same settings. On one panel there is one peak: all five should end near
   the same power. The global trackers sweep away first; that is expected.
5. **Seed test.** P&O once from starting duty 0.85. On one peak it should
   still climb back; the page contrasts this with the two-peak case in v2.
6. **A stopped run.** One short run, **Stop run** halfway.
7. **Link-down (plan 040 Step 4).** One short run, SPI cable out halfway.
   It must abort `link-down` with the duty at 0.

#### Session 1 screenshots

The Session 2 screenshot table below, except S6 and S7 (tilt). In S8 use P&O on the
panel-A curve.

#### Session 1: keep

The same as Session 2, plus the meter readings and the run's samples per
second (plan 040 needs that number).

### Session 2: the full setup

#### Session 2 setup

- [ ] Panels A and B in series. **Check a bypass diode across each panel**
      (on the panel's junction box, or a meter in diode mode). Without it
      there is no second peak, and the tilted series shows nothing.
- [ ] Jumpers and `ADC_DIVIDER_RANGE` set to **`Mid`**. The boot log
      prints the range: check it says `Mid`.
- [ ] Firmware on `main`: `FIRMWARE_MODE = MppTracker`,
      `MAX31865_ENABLED = false`.
- [ ] Heatsink on Q3 (Q3 dissipates the whole sweep; two panels is the
      ~16 W case).
- [ ] Light source recorded: lamp setting and distance, or sun with time
      and sky. **Both panels must see the same light at B = 90°**: check
      that the baseline curve has one clean knee, not two.
- [ ] Server on `main`. Browser at desktop width, **light theme**, units
      **A/W**, zoom 100 %.
- [ ] A multimeter (plan 040 Step 0, if not done yet).

#### Session 2 steps

1. **Light check.** One sweep at B = 90°. Isc must read below 700 mA and
   P at MPP below 16 W. If not, reduce the light and repeat.
2. **Baseline.** Save the B = 90° curve as **Baseline**.
3. **Tilted series.** For B = 70, 60, 45, 30: tilt B, pick the angle in
   **Panel B tilt**, sweep, save as **Tilted**. Keep A at 90° and the light
   unchanged for the whole series; note the time of each sweep.
4. **Runs.** On the baseline curve: one **P&O** run (10 s, starting duty
   0.5). On the most tilted curve that shows two clear peaks (probably
   45° or 30°): **P&O**, then **Scan&Track** and **PSO**, same duration
   and starting duty, each with that curve as **Reference curve**.
5. **Seed test.** On that same two-peak curve, P&O once from a starting
   duty that puts it near the lower peak. The page uses it to show why the
   starting duty matters.
6. **A stopped run.** One short run stopped with **Stop run** halfway.

#### Session 2 screenshots (name them exactly; PNG)

| # | UI state | File |
|---|----------|------|
| S1 | Header: the pill reading **PICO connected** (green) | `s1-connected.png` |
| S2 | Pill menu open, showing the three modes | `s2-modes.png` |
| S3 | **Measure > Capture a curve**, kind **Baseline**, before Start | `s3-capture-ready.png` |
| S4 | Mid-sweep, points appearing | `s4-sweeping.png` |
| S5 | Save form filled, just before **Save curve** | `s5-save.png` |
| S6 | Kind **Tilted**, **Panel B tilt** set to 45°, before Start | `s6-tilted-ready.png` |
| S7 | **Curves > Tilted**, the four tilted panes side by side | `s7-tilted-panes.png` |
| S8 | **Measure > Run an algorithm**, form filled for PSO on the two-peak curve | `s8-run-form.png` |
| S9 | The confirm dialog before a real run | `s9-confirm.png` |
| S10 | A run live, halfway: grey reference, trail, readouts | `s10-run-live.png` |
| S11 | The finished run, **Completed** | `s11-run-done.png` |
| S12 | **Open in player**, scrubbed to the end | `s12-player.png` |
| S13 | The pill red (**PICO not connected**): SPI cable out, nothing running | `s13-disconnected.png` |

#### Session 2: keep

- [ ] Download every curve and run (JSON), and keep the originals from the
      Pi's `data/curves/` and `data/runs/`.
- [ ] Write down, per curve: Voc, Isc, P at MPP (both peaks on the tilted
      ones). Per run: samples per second, the power held at the end.

### Scrub before anything is committed

The repo is public (AGENTS.md "What not to commit").

- [ ] **Crop every screenshot to the page content.** The browser address
      bar shows the Pi's hostname or IP and must not appear. No tabs, no
      bookmarks, no desktop.
- [ ] `exiftool -all= docs/assets/workbench/*.png`.
- [ ] Check the `label` and `notes` you typed: no place names or serials.

## Part B: write the page (any agent)

**Two versions of one page.** **v1** (after Session 1) covers panel A
alone: outline items 1-3, 5-7, 9-10, 12-15 below, with "Step 4: the
tilted series" and the two-peak comparison left out, and a note at the
top: "Two panels (A and B): coming after the next session". **v2** (after
Session 2) switches the page to the two-panel rig and adds the tilted
series and the local-vs-global comparison. Graphs for v1: F1 (one panel),
F3, F5, F7 (five runs on one peak), F9, F10, plus a run-trajectory graph
on the single-peak curve. v2 adds F2, F4, F6, F8.

The figure script is written once, for both versions: it takes the data
directory as input, so v2 only adds data.

### Files

- `docs/workbench_guide.md` - the page, titled "Measure with the workbench:
  two panels, A and B". In `mkdocs.yml` `nav` next to "Measurement
  Procedure"; linked from `docs/index.md` "Start here" and from the top of
  `docs/measurement_procedure.md`. The checklist stays; the guide is the
  walkthrough - link to the checklist, do not copy it.
- `docs/assets/workbench/` - scrubbed screenshots and generated graphs.
- `docs/assets/workbench/data/` - the curves and runs the graphs use, so
  they regenerate.
- `scripts/docs_workbench_figures.py` - reads that data and writes the
  graphs. Uses `mpp_sdk.curves.library.load`, `mpp_sdk.runs.library.load`
  and `MeasuredPanel`; matplotlib for drawing. Runs with
  `uv run python scripts/docs_workbench_figures.py`.

### Writing rules

- **Every step has three parts**: **Do** (one action, the exact UI label in
  bold), **You should see** (the result, with a screenshot or a graph),
  **If not** (the likely cause and the fix).
- Short sentences, active voice, one idea per sentence (ASD-STE100, as the
  rest of `docs/`). Plain hyphens.
- `!!! danger` before the first step that energizes anything; `!!! warning`
  before the first run.

### The graphs

All: SVG, **white background** (the site has a dark theme; a transparent
plot disappears on it), 700-800 px wide, axis labels with units, a title
that says what to look at, at most one annotation per idea. The reference
curve in grey, as in the workbench.

| # | Graph | What it must show |
|---|-------|-------------------|
| F1 | Setup diagram (Mermaid, in the page) | Panels A and B in series, each with its bypass diode -> board (INA229, SEPIC, curve-tracer relay) <-SPI-> Pi (server) <-> browser. Which box measures, which runs the algorithm. |
| F2 | Tilt geometry sketch | A at 90° to the light, B at an angle; why a smaller angle means less current from B. |
| F3 | The baseline curve: I-V and P-V | Voc, Isc and the MPP marked with their values; the knee where the sweep adds points. |
| F4 | The tilted series overlaid | P-V for B = 90, 70, 60, 45, 30 in one plot: the single peak splitting into two as B tilts. Both peaks marked on the most tilted curve. This is the key graph of the page. |
| F5 | Reading a curve: good vs. bad | The baseline beside a noisy and a truncated sweep, one-line cause each. Only real sweeps from the sessions; leave it out rather than fake one. |
| F6 | Local vs. global on the two-peak curve | The grey P-V reference with the P&O, Scan&Track and PSO trajectories on it: where each one ended. |
| F7 | Power over time, all three runs | P(t) against the global MPP (dashed); time to 95 %; final percentage per algorithm. |
| F8 | The starting duty matters | The seed-test P&O run from step 5 stuck on the lower peak, against the one from 0.5. |
| F9 | Duty and voltage over time | D(t) and V(t) for one run; an inset on P&O's steady back-and-forth. |
| F10 | The stopped run | P(t) ending at the Stop press, duty dropping to 0. |

Mermaid needs `pymdownx.superfences` custom fences in `mkdocs.yml`
(Material's documented setting). Keep `mkdocs build --strict` green.

### Page outline

1. **What you will do** - the experiment in three sentences; what you end
   with (a baseline, a tilted series, runs compared). Time: about 1.5 h.
2. **What you need** - the Session 2 setup list, for a reader.
3. **Safety** (`!!! danger`) - the unauthenticated server stays on the lab
   network, never exposed; Q3 gets hot; the light limits above and why;
   how to stop (**Stop run**, the power switch).
4. **The setup** - F1, F2, the limits table in plain words.
5. **Step 1: connect** - S1, S2, S13; the three modes in a short table;
   only **PICO connected** measures.
6. **Step 2: check the light** - one sweep, the two numbers to read.
7. **Step 3: the baseline** - S3, S4, S5, F3.
8. **Step 4: the tilted series** - S6, S7, F4. How to read two peaks.
9. **Reading a curve** - F5.
10. **Step 5: run the algorithms** (`!!! warning` first) - S8, S9, S10,
    S11, S12.
11. **Step 6: compare them** - F6, F7, F8, F9. The numbers from the
    session, and the simulation's result for the same curve for
    comparison (re-run it in Demo mode against the saved curve).
12. **Stopping a run** - F10.
13. **Try it without the board** - Demo mode, two sentences.
14. **If something goes wrong** - symptom, cause, fix. At least: red pill;
    sweep ends early (light too strong for the cutoff); one knee where two
    were expected (no bypass diode, or B not tilted enough); noisy curve;
    V readings flat near 27 V (ADC range still `Low`); run aborted
    `link-down`; run aborted `overcurrent`; grey reference missing.
15. **Next** - `measurement_procedure.md`, the algorithm pages, plan 040's
    remaining steps.

### Verification

- [ ] `uv run mkdocs build --strict` passes; the PR's docs preview renders
      every image in the light and the dark theme.
- [ ] `uv run pre-commit run markdownlint-cli2 --files docs/workbench_guide.md`.
- [ ] The figure script regenerates every graph from the committed data
      with no manual step.
- [ ] No hostname, IP, username or local path in the page, the images or
      the data (`grep -rE "192\.168|\.local|/home/" docs/`).
- [ ] **A teammate who has not used the workbench follows the page alone**,
      in Demo mode first and then on the bench, and gets the baseline, one
      tilted curve and one run. Every place they hesitate is a fix.

## Done criteria

- [ ] The page is live on the docs site and in the nav.
- [ ] Every step has Do / You should see / If not.
- [ ] Every graph comes from committed data via the script.
- [ ] A new reader completed it unaided.

## STOP conditions

- **A sweep aborts at a cutoff** - reduce the light. Do not raise
  `TRACER_I_MAX_MA` or `TRACER_P_MAX_MW` to make the page work.
- **Session 1: the first run behaves unexpectedly** (the converter makes
  a noise that does not settle, Q3 too hot to touch, the panel voltage
  collapses and stays there, duty stuck at a rail) - stop, record it in
  plan 040. Page v1 waits for a clean run.
- **The tilted curves never show two peaks** - check the bypass diodes and
  the tilt before anything else. The page's central graph (F4) depends on
  it; do not write Step 4 without it.
- **A run does not converge, or aborts on its own** - that is a plan 040
  finding, not a docs problem. Record it there; write the page only once
  clean runs exist.
- **`ADC_VOUT` disagrees with the meter** - the page may show the V out
  readout but must not quote its value until it is fixed.
