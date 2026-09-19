# Plan 041: One-page guide - measure one panel with the workbench

> **Executor instructions**: two parts. **Part A is a bench exercise** that
> only an operator at the bench can do: it produces the data and the
> screenshots. **Part B writes the page** from those, and any agent can do
> it. Do not write Part B from memory or from Demo mode: every number and
> every screenshot on the page must come from the Part A session.

## Status

- **Priority**: P1 - the workbench now does everything the thesis needs on
  the bench, but only the people who built it know how to drive it.
- **Effort**: M (one bench session of about 1 h, then the page).
- **Risk**: LOW for the page. Part A drives the real converter: it carries
  plan 040's risks, and follows plan 040's safety rules.
- **Depends on**: plan 040 Step 0 (meter check of `ADC_VOUT`) before the
  page quotes any output voltage. Part A can double as plan 040 Steps 1-3
  on one panel.
- **Category**: documentation.
- **Planned at**: 2026-09-18, after PRs #99-#101 landed.

## Why this matters

`docs/measurement_procedure.md` is a checklist for someone who already
knows the workbench. There is no page that takes a new person from "board
on the desk" to "a saved curve and a saved run, and I understand the
graphs". The goal is one page in the docs site (MkDocs Material, published
to GitHub Pages) that a teammate can follow alone, step by step, and get
the same result.

## What the page must be

- **One page**: `docs/workbench_guide.md`, titled "Measure one panel with
  the workbench". Added to `mkdocs.yml` `nav` next to "Measurement
  Procedure", and linked from `docs/index.md` "Start here" and from the top
  of `docs/measurement_procedure.md` (the checklist stays; the guide is the
  walkthrough - do not copy the checklist into the guide, link to it).
- **Extremely clear instructions.** Every step has the same three parts:
  1. **Do**: one action, with the exact label of the button or field in
     bold, as the UI shows it (for example **Start Measurement**).
  2. **You should see**: the expected result, with a screenshot or a graph.
  3. **If not**: the most likely cause and what to do.
  Short sentences, active voice, one idea per sentence (ASD-STE100 style,
  as the rest of `docs/`). Plain hyphens, no em dashes.
- **Clear graphs.** Generated from the real saved JSON by a script (below),
  never drawn by hand, so they can be regenerated.
- **Safety first, visibly.** A `!!! danger` admonition before the first
  step that energizes anything, and a `!!! warning` before the run.

## Part A: the bench exercise (operator)

### Setup

- [ ] One panel on the input (the page is written for one panel; two in
      series is a later page).
- [ ] **Light: the lamp, not full sun.** One panel's datasheet short-circuit
      current is 0.79 A, and the curve tracer's safety cutoff is 700 mA
      (`TRACER_I_MAX_MA` in `firmware/safety-checks/src/lib.rs`). In strong
      sun the sweep aborts at the cutoff. The bright lamp setting measured
      about 0.61 A. Record the light source, the distance and the lamp
      setting.
- [ ] Heatsink on Q3, or keep the run short (plan 040 Preconditions).
- [ ] Firmware on `main`, with `FIRMWARE_MODE = MppTracker`,
      `ADC_DIVIDER_RANGE` matching the jumpers, `MAX31865_ENABLED = false`.
- [ ] Server on the Pi on `main`, started with `mpp-sdk curve-tracer-web`.
- [ ] Browser at desktop width, **light theme**, units in **A/W** (the
      docs' own default). Zoom 100 %.
- [ ] A multimeter, for plan 040 Step 0 if not done yet.

### Capture, in order (do not skip the screenshots)

Name every file exactly as listed. Save screenshots as PNG.

| # | UI state | File |
|---|----------|------|
| S1 | Header only: the connection pill reading **PICO connected** (green) | `s1-connected.png` |
| S2 | Pill menu open, showing the three modes | `s2-modes.png` |
| S3 | **Measure > Capture a curve**, kind **Baseline**, before Start | `s3-capture-ready.png` |
| S4 | The same, mid-sweep, points appearing | `s4-sweeping.png` |
| S5 | Save form filled (label, notes), just before **Save curve** | `s5-save.png` |
| S6 | **Curves > Baseline**, the new pane with its metadata | `s6-curve-pane.png` |
| S7 | **Measure > Run an algorithm**, form filled: **P&O**, the new curve as **Reference curve**, 10 s, starting duty 0.5, 40 V / 1 A | `s7-run-form.png` |
| S8 | The confirm dialog before a real run | `s8-confirm.png` |
| S9 | The run live, halfway: grey reference, trail, readouts | `s9-run-live.png` |
| S10 | The finished run, **Completed**, readouts | `s10-run-done.png` |
| S11 | **Open in player**, scrubbed to the end | `s11-player.png` |
| S12 | The pill red (**PICO not connected**): unplug the board's SPI cable with nothing running | `s12-disconnected.png` |

Then:

- [ ] Run **Stop run** once, mid-run, on a second short run. Keep that run:
      the page shows what an aborted run looks like.
- [ ] Download the curve (JSON) and both runs from the workbench. Keep the
      original files from the Pi's `data/curves/` and `data/runs/` too.
- [ ] Write down, for the page's "what good looks like" numbers: Voc, Isc
      and P at MPP from the curve pane; the run's samples per second
      (samples / duration); the power the run held at the end.

### Scrub before anything is committed

The repo is public (AGENTS.md "What not to commit").

- [ ] **Crop every screenshot to the page content.** The browser address
      bar shows the Pi's hostname or IP: it must not appear. No tabs, no
      bookmarks, no desktop.
- [ ] `exiftool -all= docs/assets/workbench/*.png`.
- [ ] The JSON files hold no location or serial data; check the `notes`
      and `label` fields you typed.

## Part B: write the page (any agent)

### Files

- `docs/workbench_guide.md` - the page.
- `docs/assets/workbench/` - the scrubbed screenshots and the generated
  graphs.
- `docs/assets/workbench/data/` - the curve and the two runs used for the
  graphs (scrubbed), so the graphs regenerate.
- `scripts/docs_workbench_figures.py` - reads those JSON files, writes the
  graphs. Uses `mpp_sdk.curves.library.load`, `mpp_sdk.runs.library.load`
  and `MeasuredPanel` for the MPP, matplotlib for drawing. Run with
  `uv run python scripts/docs_workbench_figures.py`.

### The graphs

All: SVG, **white background** (not transparent - the site has a dark
theme and a transparent plot disappears on it), 700-800 px wide, axis
labels with units, a title that says what to look at, and at most one
annotation arrow per idea. Same colors as the workbench where it makes
sense: current and power series distinct, the reference curve in grey.

| # | Graph | What it must show |
|---|-------|-------------------|
| F1 | System diagram (Mermaid, in the page) | Panel -> board (INA229, SEPIC, curve-tracer relay) <-SPI-> Pi (server) <-> browser. Which box measures V and I, which box runs the algorithm. |
| F2 | The captured curve: I-V and P-V on two y axes | Voc, Isc and the MPP marked and labelled with their values; the knee region, where the sweep puts more points. |
| F3 | Reading a curve: good vs. bad, small multiples | The good curve from Part A beside what a noisy sweep and a truncated sweep look like, each with a one-line cause. Use real bad sweeps if the session produced any; otherwise leave F3 out rather than faking one. |
| F4 | The run over its reference | The P-V reference in grey, the run's (V, P) samples colored by time, the MPP marked. The reader sees the algorithm climb the curve. |
| F5 | Power over time | P(t) with the curve's P at MPP as a dashed line, the time to reach 95 % of it marked, and the final percentage written on the plot. |
| F6 | Duty and voltage over time | D(t) and V(t); an inset zoomed on the end showing P&O's steady back-and-forth. |
| F7 | The aborted run | P(t) that stops at the Stop press, duty dropping to 0. |

Mermaid needs `pymdownx.superfences` custom fences in `mkdocs.yml`
(Material's documented setting). Add it; keep `mkdocs build --strict`
green.

### Page outline

1. **What you will do** - two sentences, and the two results: a saved
   curve and a saved run. Time: about 30 minutes.
2. **What you need** - the Part A setup list, rewritten for a reader.
3. **Safety** (`!!! danger`) - unauthenticated server, keep it on the lab
   network, never expose it; Q3 gets hot; how to stop a run (**Stop run**,
   and the power switch).
4. **How the pieces connect** - F1.
5. **Step 1: connect** - S1, S2, S12. The three modes in one short table:
   what each one drives, and that only **PICO connected** measures.
6. **Step 2: capture a curve** - S3, S4, S5.
7. **Step 3: read the curve** - S6, F2, F3.
8. **Step 4: run an algorithm** (`!!! warning` first: this drives the
   converter) - S7, S8, S9, S10.
9. **Step 5: read the run** - S11, F4, F5, F6. What "good" is: the held
   power as a percentage of the curve's MPP, with the number from Part A
   and the simulation's 99.7 % for comparison.
10. **Stopping a run** - F7 and what the saved run records.
11. **Try it without the board** - Demo mode, two sentences.
12. **If something goes wrong** - a table: symptom, cause, fix. At least:
    red pill; sweep ends early (cutoff - too much light); noisy curve;
    run aborted `link-down`; run aborted `overcurrent`; grey reference
    missing (no curve picked, or a demo curve outside Demo mode).
13. **Next** - links: `measurement_procedure.md` (the checklist, tilted
    series), the algorithm pages, plan 040's remaining steps.

### Verification

- [ ] `uv run mkdocs build --strict` passes; the PR's docs preview renders
      every image in both the light and the dark theme.
- [ ] `uv run pre-commit run markdownlint-cli2 --files docs/workbench_guide.md`.
- [ ] The figure script regenerates every F-graph from the committed data
      with no manual step.
- [ ] No hostname, IP, username or local path in the page, the images or
      the data (`grep -rE "192\.168|\.local|/home/" docs/`).
- [ ] **A teammate who has not used the workbench follows the page alone**,
      in Demo mode first and then on the bench, and gets a saved curve and
      a saved run. Every place they hesitate is a fix to the page.

## Done criteria

- [ ] The page is live on the docs site and in the nav.
- [ ] Every step has Do / You should see / If not.
- [ ] All graphs come from the committed data via the script.
- [ ] A new reader completed it unaided.

## STOP conditions

- **The sweep aborts at the current cutoff** - reduce the light (lamp
  setting or distance). Do not raise `TRACER_I_MAX_MA` to make the page
  work.
- **The run does not converge, or aborts on its own** - that is a plan 040
  finding, not a docs problem. Stop, record it in plan 040, and write the
  page only once a clean run exists.
- **`ADC_VOUT` disagrees with the meter** (plan 040 Step 0) - the page may
  show the V out readout but must not quote its value until it is fixed.
