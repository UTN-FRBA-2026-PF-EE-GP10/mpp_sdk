# Plan 040: Drive the converter from the web UI, on the bench

> **Executor instructions**: this is a **bench plan**, not a code change.
> It cannot be completed without the board, a lit panel and someone
> watching it. Every step that energises the converter has a stated abort
> condition; if one fires, stop and record what happened rather than
> retrying with the limits widened.
>
> **Read `docs/measurement_procedure.md` first.** This plan extends it
> with the run case.

## Status

- **Priority**: P1 - this is the last unverified path in the whole
  measurement stack, and the only one that can damage hardware.
- **Effort**: M (bench), plus however long the first abort takes to
  understand.
- **Risk**: **HIGH**. This is the first time an algorithm drives the SEPIC
  continuously from a browser click. Everything before it was either a
  bounded sweep or a simulation.
- **Depends on**: a powered Pico (see "Preconditions"), and see "The open
  defect underneath this" below.
- **Category**: on-target verification.
- **Planned at**: 2026-09-15, after the live-run feature landed and was
  verified in simulation only.

## Why this matters

The live-run feature is complete and tested, and **none of it has touched
hardware**. What has been proven, on this bench:

- A simulated P&O run against a real captured curve converged to within
  0.3% of that curve's measured MPP (3.064 W against 3.072 W), with no
  algorithm changes. The `SignalSource` substitution works.
- The API, provenance, save path, abort plumbing and UI all behave in
  simulation and under unit test.

What has **not** been proven is the only part that matters for the thesis
claim: that the same algorithm holds a real panel at its maximum power
point through a real converter. Plan 034 scoped this as its Step 7 and it
has never been run.

## The open defect underneath this

**Plan 039** (PIO SPI slave cannot recover from an idle frame timeout) is
open, with a workaround rather than a fix: the Pi polls faster than the
firmware's 100 ms frame timeout so the broken recovery path never runs.

A live run makes that workaround load-bearing in a new way. The control
loop exchanges frames continuously with no sleep, so it stays well inside
the timeout while running - but **any pause longer than 100 ms** (a
scheduler hiccup on the Pi, a slow request handler, the operator switching
panes) re-enters exactly the state 039 describes. The run's link-down
abort should catch it, which is the mitigation, but that threshold is
itself unverified - see the next section.

**Decide before starting**: either accept that risk with the abort as the
net, or fix 039 first. This plan assumes the former and treats any
link-down abort as a real finding to be recorded, not a nuisance.

## The unverified number

`run_control_loop`'s `max_consecutive_bad_frames` is set to 300 for the
live-run path, scaled arithmetically from the curve tracer's 8 because
the control loop has no sleep between exchanges. **Nobody has measured
the real per-step rate.** At 1 ms per step that is 0.3 s of driving a
converter against telemetry that may be stale; at 10 ms it is 3 s.

Step 2 below measures the real step rate. Once known, this number should
be re-derived from it rather than left as arithmetic.

## The output voltage is unverified

The live-run view shows **V out** beside V in. They are not equally
trustworthy:

- **V in** comes from the INA229 and is calibrated. Trust it.
- **V out** comes from the RP2040's on-chip ADC through a divider whose
  ratio is applied from theory. It has **never been checked against a
  reference**, because there is nothing on the board to check it against:
  the INA229 sits on the panel input, not the converter output.

Plan 010's ~9% figure is often quoted here, but that was `ADC_PWR`, and
switching to the `Low` divider range brought it to about 0.03% against the
INA229. `ADC_VOUT` got no such verification because it had no reference to
be verified against.

So the number now displayed during a run - and the one an operator will
naturally read as "what the converter is producing" - is unconfirmed.

**Do Step 0 before anything else.** If V out turns out to be off, every
run recorded before that is fine (the samples hold V, I and duty from the
INA229, not V out), but any conclusion drawn from the displayed output
voltage is not.

### Step 0: put a meter on the converter output

- [ ] With the converter running at a known steady duty (the
      `power_supply` firmware mode, or a short fixed-duty test), measure
      the real output voltage with a multimeter.
- [ ] Compare against `ADC_VOUT` as reported by `GET /api/data` and in the
      live-run readout.
- [ ] Record the error. If it is small, note it and move on. If it is not,
      correct the divider constant in the firmware before running anything
      whose output voltage you intend to cite.
- [ ] Check it at more than one output voltage if you can - a divider
      error scales, an ADC offset error does not, and the two are
      distinguishable only with two points.

This closes the part of plan 010 that plan 010 could not close, because
until now nothing displayed `ADC_VOUT` where it mattered.

## Preconditions

- [ ] Pico powered and responding. The connection indicator must read
      **PICO connected**. If it reads "PICO not connected", stop - the
      board-absence detection is telling the truth, and a run started
      against a dead link is exactly what it exists to prevent.
- [ ] Firmware flashed with `FIRMWARE_MODE = MppTracker` (the default).
- [ ] Panel(s) connected and lit. A dark panel makes a run meaningless -
      the algorithm will hunt a maximum that is not there.
- [ ] **A heatsink on Q3, or a short first run.** Q3 dissipates the sweep
      linearly, worst case at the MPP. A sweep is bounded; a run holds the
      converter at its operating point continuously. Two panels in series
      at full sun is the ~20 W case.
- [ ] `data/runs/` backed up or empty, so the first real run is easy to
      find.
- [ ] Someone physically at the bench, able to cut power.
- [ ] Step 0 below done, or an explicit decision to treat the displayed
      V out as indicative only.

## Steps

### Step 1: capture the ground-truth curve first

Capture a curve under the conditions the run will use, and save it. The
run needs it as `curve_ref` so the player can draw the trajectory over the
real curve, and so the MPP the algorithm found can be compared against the
MPP the sweep measured. That comparison is the entire result.

Record the conditions in the curve's notes - lamp or sun, distance, panel
angles.

### Step 2: the shortest possible run

Start from the UI: **P&O, 10 seconds, the curve from Step 1 as reference,
default limits (40 V / 1 A).**

Watch the bench, not the screen.

Record:

- [ ] Did it start, and how long before the first sample appeared?
- [ ] **The real step rate**: samples divided by duration. This is the
      number the link-down threshold should be re-derived from.
- [ ] Did the operating point converge, and how long did it take?
- [ ] Q3 temperature by hand at the end (carefully), or with a probe.
- [ ] Did it end cleanly, or abort? If aborted, the reason.

**Abort and investigate if**: the converter makes an audible change that
does not settle, Q3 becomes too hot to touch briefly, the panel voltage
collapses and stays collapsed, or the duty saturates at either rail.

### Step 3: compare against the curve

Open the saved run in the player over its reference curve.

- [ ] Does the trajectory sit **on** the measured curve, or beside it? A
      systematic offset means the simulated and real plants disagree, and
      that is a finding worth more than the run itself.
- [ ] What power did it hold, against the curve's measured `p_mpp`?
- [ ] Is the steady-state oscillation the expected three-point P&O cycle?

The simulation reached 99.7% of the curve's MPP. Anything far below that
on hardware points at the converter model, the duty mapping, or the
sampling, and is worth chasing before more algorithms are run.

### Step 4: the aborts, deliberately

Each of these should be provoked once, in a controlled way, while
watching:

- [ ] **Stop**: press it mid-run. Confirm the duty goes to zero and the
      run saves as aborted with reason `stopped`.
- [ ] **Link down**: with a short run going, interrupt the link (the
      cleanest is unplugging the SPI connection, not powering the board
      down mid-drive). Confirm the run aborts with reason `link-down` and
      the duty is zeroed. **This is the most important abort to verify**,
      because it is the one protecting against 039.
- [ ] **Duration backstop**: start with no duration and confirm it stops
      on its own rather than running indefinitely.

Do NOT provoke overvoltage or overcurrent deliberately. Those bounds
protect the board; verify them in simulation, where they already are.

### Step 5: the other algorithms

Only once P&O is clean. Run each of InCond, Fuzzy, Scan&Track and PSO for
the same duration against the same curve, and record what each holds.

Scan&Track and PSO are global trackers and will deliberately sweep away
from the MPP before settling. On a single unshaded panel that looks like
worse tracking; it is not, and the comparison is only fair under partial
shading. Note it rather than concluding from it.

## Done criteria

- [ ] At least one P&O run, on hardware, saved with `source: "hardware"`
      and a `curve_ref`, that converged and did not abort.
- [ ] The measured step rate recorded, and `max_consecutive_bad_frames`
      re-derived from it (or explicitly confirmed as still reasonable).
- [ ] The stop and link-down aborts both observed zeroing the duty.
- [ ] The run's held power compared against its reference curve's
      measured MPP, with the number written down.

## STOP conditions

- **The connection indicator is red.** The board is not answering. Fix
  that first; it is not a UI problem.
- **A run aborts with `link-down` during ordinary operation** (not the
  deliberate test in Step 4). That is plan 039 manifesting under load and
  changes the risk calculus - stop and fix 039 before running more.
- **Q3 gets hot enough to worry about** in a 10 second run. Scale back to
  shorter runs and sort the heatsinking before continuing.
- **The trajectory sits systematically off the measured curve.** Stop and
  understand it. Running four more algorithms against a plant that does
  not match its own measured curve produces four more unusable results.
- **Anything about the converter's behaviour surprises you.** This is the
  first time it has been driven this way.

## Notes for whoever runs this

The simulated path is the reference. If a hardware run behaves oddly,
re-run the same algorithm and duration in demo mode against the same
curve: identical behaviour in simulation and not on hardware isolates the
problem to the plant or the link, not to the algorithm or the UI.
