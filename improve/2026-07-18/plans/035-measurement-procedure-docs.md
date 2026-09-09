# Plan 035: Measurement-procedure checklist page (curves, tilt steps, runs)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard dependency check (run first)**: `grep -n "run-algorithm" harness/cli.py`.
> **If this returns nothing, STOP and report** - this plan's "Closed-loop
> runs" section (Step 4) documents `mpp-sdk run-algorithm`/`plot-run`,
> which do not exist until plan 034
> (`improve/2026-07-18/plans/034-hardware-mppt-runs.md`) is executed. Do
> not write that section against the plan's *design* without the real,
> shipped CLI to verify flag names/output against - that is exactly the
> "docs describe something that hasn't shipped" failure mode this plan
> exists to avoid elsewhere.
>
> **Drift check (after confirming the dependency)**: `git diff --stat
> 742e9e7..HEAD -- frontend/src/components/CurveWorkbench.tsx
> mpp_sdk/curves/record.py scripts/curve_tracer_server.py mkdocs.yml`. If
> any of these changed, re-read them before writing the corresponding
> section - this plan cites exact UI field names and CLI commands that
> must match what actually exists.

## Status

- **Priority**: P2 - the project has real curves and (once plan 034 lands)
  real runs on real hardware, and zero written-down procedure for how to
  capture either one. That knowledge currently lives only in this
  session's conversation history and the plan files themselves - neither
  is where a bench operator would look.
- **Effort**: M - one new documentation page, no code.
- **Risk**: LOW - docs only.
- **Depends on**: **034 (hard, for Step 4 only)** - see the dependency
  check above. Steps 1-3 (curve capture, tilt-sweep procedure) have no
  dependency and can be written and shipped independently if 034 is not
  ready yet - see "Partial execution" below.
- **Category**: docs.
- **Planned at**: commit `742e9e7`, 2026-09-08.

## Why this matters

Three real, already-usable-or-soon-to-be-usable workflows have **no
operator-facing procedure written down anywhere**:

1. **Capturing a curve** with the web workbench
   (`scripts/curve_tracer_server.py`, `frontend/`) - the *protocol* is
   documented in exhaustive technical detail
   (`firmware/pipico_board/README.md`'s "Curve tracer" section: auto-
   ranging, safety cutoffs, the SPI handshake), but nothing says, in plain
   steps, "here is how you actually run a capture session" - what to
   click, what to type into which field, in what order.
2. **A tilt-sweep series** - `mpp_sdk/curves/record.py`'s
   `MEASUREMENT_KINDS` already seeds `"tilt-sweep"` ("a series varying one
   panel's tilt") and the web UI already has a per-panel `tilt_deg` number
   input (`frontend/src/components/CurveWorkbench.tsx`), but there is no
   written convention for *how* to run a consistent tilt-sweep session
   (what angles, how many curves, how to label them so they group
   sensibly later).
3. **A closed-loop run** (plan 034, `mpp-sdk run-algorithm`/`plot-run`) -
   once that lands, it is a CLI tool with a `--help` string, not a guided
   procedure.

Found via a direct operator request (not the September audit), given
alongside the request that produced plan 034 itself - the docs page this
plan writes is meant to be the *practical companion* to that plan's CLI
tools and the existing web workbench, not a restatement of either.

## Current state

### Where this page's content comes from (existing, real behavior)

**Starting the workbench** (`README.md`'s existing Quickstart section,
"Curve-tracer web workbench" - re-read it, it already has the exact
one-liners):

```bash
uv sync --extra web            # or --extra web --extra hardware on the Pi
mpp-sdk curve-tracer-web        # real hardware
mpp-sdk curve-tracer-web --demo # simulated, any machine, no board
```

**The save form's actual fields**, `frontend/src/components/CurveWorkbench.tsx`
(read it in full before writing Step 1 - only the load-bearing shape is
quoted here): a `label` text field, a `measurement` dropdown (populated
from `GET /api/measurement-kinds`, seeded with
`mpp_sdk.curves.record.MEASUREMENT_KINDS`: `baseline`, `partial-shade`,
`tilt-sweep`, `dimmer`, `other`), a `notes` field, and one `tilt_deg`
number input **per panel** (`DEFAULT_PANELS = [{id: 'A', tilt_deg: 0},
{id: 'B', tilt_deg: 0}]`) - each panel's tilt is entered separately, this
is how a tilt-sweep curve records *which* panel was tilted and by how
much.

**`MEASUREMENT_KINDS`' own seed vocabulary**, `mpp_sdk/curves/record.py`:

```python
MEASUREMENT_KINDS = (
    "baseline",  # all panels same tilt, uniform illumination
    "partial-shade",  # one panel tilted/shaded relative to the other
    "tilt-sweep",  # a series varying one panel's tilt
    "dimmer",  # varying illumination (plan 024)
    "other",
)
```

Curves are grouped by this field on both the web UI (`GET /api/curves`
buckets, `App.tsx`) and in `mpp-sdk compare-measured`
(`library.group_by_measurement`) - the checklist's tilt-sweep section must
tell the operator to actually use `"tilt-sweep"` consistently, or later
grouping/analysis silently misses curves filed under `"other"` instead.

### mkdocs site structure to extend

`mkdocs.yml`'s current `nav`:

```yaml
nav:
  - Home: index.md
  - General Information: general_information.md
  - Rationale: rationale.md
  - Methodology: methodology.md
  - Algorithms:
      - Perturb & Observe: algorithms/perturb_observe.md
      - Incremental Conductance: algorithms/incremental_conductance.md
      - Fuzzy Logic: algorithms/fuzzy_logic.md
      - Scan-and-Track: algorithms/scan_and_track.md
      - Particle Swarm: algorithms/particle_swarm.md
      - Restart policy: algorithms/restart_policy.md
```

Everything here is either conceptual (General Information, Rationale,
Methodology) or algorithm-reference (one page per controller) - there is
no "how do I actually run a bench session" page anywhere in the site.
`frontend/README.md` is developer-facing (build/dev commands, not usage);
`firmware/pipico_board/README.md`'s "Curve tracer" section is a hardware/
firmware protocol reference, not an operator procedure - this plan's page
is neither of those, and should not duplicate either (link to them for
the "why"/"how it works under the hood", keep this page to "what do I do,
in order").

## Scope

**In scope**:

- `docs/measurement_procedure.md` (new).
- `mkdocs.yml` - one new `nav` entry.

**Out of scope**:

- Any change to `frontend/`, `scripts/curve_tracer_server.py`, or
  `mpp_sdk/curves/` - this plan documents existing behavior, it does not
  add a delete/rename UI, a bench-session-planning UI, or any other
  feature (both were raised as *separate*, not-yet-planned direction
  findings in the September audit - do not fold them in here).
- Firmware protocol details (auto-ranging, safety cutoffs, the SPI
  handshake) - already thoroughly documented in
  `firmware/pipico_board/README.md`'s "Curve tracer" section; link to it,
  do not re-explain it.
- A step-by-step for `mpp-sdk compare-measured` itself (already documented
  in `docs/methodology.md`'s "Measured curves: replaying real panel data"
  section) - link to it for "what to do with saved curves afterward"
  rather than re-explaining the harness.

## Partial execution (if plan 034 is not ready)

If you reach the hard-dependency check at the top and `run-algorithm`
does not exist yet: **write and ship Steps 1-3 only** (the curve-capture
and tilt-sweep procedure - fully independent of plan 034), add the page to
the nav, and leave a placeholder in place of Step 4's section:

```markdown
## Closed-loop runs

*(Coming once [plan 034](https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk/blob/main/improve/2026-07-18/plans/034-hardware-mppt-runs.md)
lands - captures a dynamic run of a real algorithm against the live panel,
alongside a paired static curve.)*
```

Mark this plan `IN PROGRESS (Steps 1-3 done, Step 4 blocked on 034)` in
the README rather than TODO or DONE, and open a lightweight follow-up note
in the same README entry once 034 ships so Step 4 doesn't get forgotten.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| mkdocs builds clean | `uv run mkdocs build --strict --site-dir /tmp/mkdocs-check` | exit 0, no warnings (`--strict` turns broken internal links into build failures - this catches a typo'd nav path or a dead link to another doc page) |
| Confirm the nav entry resolves | open the built `/tmp/mkdocs-check/measurement_procedure/index.html` (or just trust `--strict`'s success, which already proves the nav path resolves) | page exists |
| Markdown lint (pre-commit will also run this) | `uv run pre-commit run markdownlint-cli2 --files docs/measurement_procedure.md mkdocs.yml` | passes, or auto-fixes trivial issues (trailing whitespace etc.) - re-stage if it modifies files |

## Git workflow

- Branch: `docs/measurement-procedure`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: pre-flight + baseline curve capture

Write `docs/measurement_procedure.md`, opening with a short intro (one
paragraph: what this page is for, link to `README.md`'s Quickstart for
installing the `web` extra) and a "Before you start" checklist:

- [ ] Board wired and powered (SPI0 CE0, per `firmware/pipico_board/README.md`'s
      wiring section - link it, don't restate the pinout here).
- [ ] Firmware flashed with `FIRMWARE_MODE = MppTracker` (or whichever mode
      the session needs - re-read `firmware/pipico_board/src/main.rs` to
      confirm this is still the constant's exact name before citing it).
- [ ] Panel(s) connected and getting light (a curve tracer sweep on a dark
      panel aborts - `firmware/pipico_board/README.md`'s "Auto-range"
      section explains why, link it).
- [ ] `mpp-sdk curve-tracer-web` running (real board) or
      `mpp-sdk curve-tracer-web --demo` (practice run, any machine, no
      board - useful for rehearsing this exact checklist before a real
      bench session).

Then a numbered "Capture one curve" procedure, written as literal UI
steps against `CurveWorkbench.tsx`'s actual fields (re-read the file
first, per the drift check, to confirm field labels/order haven't
changed):

1. Open `http://<pi-host>:8000/` (or `http://localhost:8000/` for
   `--demo`).
2. Click **Start Sweep**. Wait for the curve to finish plotting (a few
   seconds - the sweep auto-ranges and takes 20 points, per
   `firmware/pipico_board/README.md`).
3. Fill in the save form: **Label** (a short human-readable description -
   suggest a convention, e.g. `"<date> <condition>"` like
   `"2026-09-08 baseline lamp 30cm"`), **Measurement** = `baseline` for an
   ordinary single-condition capture, **Notes** (anything not captured by
   the other fields - lamp distance, ambient light, anything unusual).
   Leave each panel's **tilt** at its physical resting angle (0° if flat).
4. Click **Save**. Confirm it appears in the saved-curves list below.

### Step 2: the tilt-sweep procedure

A new subsection, "Capturing a tilt-sweep series" - this is the part that
did not exist anywhere before this plan. Content:

- **Why**: a tilt-sweep is a series of curves at the same illumination
  with one panel's tilt angle varied - it is what lets
  `mpp-sdk compare-measured` (link `docs/methodology.md`'s "Measured
  curves" section) grade an algorithm's partial-shading behavior against
  a *real*, physically-varying array shape instead of an inferred one.
- **Convention** (pick sensible defaults, but say explicitly that they are
  a starting convention, not a hard rule): sweep the same panel through a
  fixed set of angles (suggest `0°, 15°, 30°, 45°, 60°` as a reasonable
  spread - adjust based on what the mounting hardware can actually hold
  steady), keep every other condition (lighting, the *other* panel's
  tilt) constant across the whole series, and use the same **Label**
  prefix for the whole series with the angle appended (e.g.
  `"2026-09-08 tilt-sweep 30deg"`) so the saved-curves list stays
  readable at a glance.
- **Procedure**: repeat Step 1's four sub-steps once per angle, with two
  changes each time: physically set the panel to the next angle before
  clicking Start Sweep, and in the save form set **Measurement** =
  `tilt-sweep` and that panel's **tilt** field to the actual angle used
  (not just the label - the `tilt_deg` field is what
  `group_by_measurement`/analysis code actually reads).
- **After the series**: point at `mpp-sdk compare-measured` (link
  `docs/methodology.md`) as the next step - it already groups by
  `measurement`, so a consistently-labeled `tilt-sweep` series shows up
  together automatically.

**Verify**: re-read the written section once more against
`CurveWorkbench.tsx` - every UI element you named (button labels, field
names, the measurement-kind value) must match exactly what the code
calls them; a docs page with a wrong button label is worse than no docs
page.

### Step 3: where the files land

A short "Where this data lives" subsection: `data/curves/` (one JSON per
sweep, gitignored - link `data/README.md`), and once plan 034 lands,
`data/runs/` for closed-loop runs. Mention `MPP_SDK_CURVE_DIR`/
`MPP_SDK_RUN_DIR` only if you think a bench operator (not a developer)
would plausibly need to override them - if unsure, leave this to a single
sentence pointing at `data/README.md` rather than re-explaining the env
vars here.

### Step 4: closed-loop runs (only if the hard dependency check passed)

A "Closed-loop runs" subsection, written **against the actual, shipped**
`scripts/run_algorithm.py`/`scripts/plot_run.py` from plan 034 - run
`uv run mpp-sdk run-algorithm --help` and `uv run mpp-sdk plot-run --help`
yourself and write the procedure from their real output, not from plan
034's design section (the plan is a spec for what to build; the shipped
`--help` text is ground truth for what to document).

Structure to follow: a "Before you start" note (a run drives the SEPIC
continuously with a live algorithm - link back to plan 034's "Safety: no
on-target cutoff exists for this today" section for why this matters, or
better, to wherever that safety design ended up documented in the shipped
code's own docstrings/README once it exists), then a numbered procedure:
run `mpp-sdk run-algorithm` with the flags that exist, note what gets
printed/saved, then `mpp-sdk plot-run` to visualize it.

**Verify**: every flag name and example command in this section must
match `--help`'s actual output byte-for-byte - copy-paste from a real
terminal run, don't retype from memory or from the plan.

### Step 5: wire it into the nav and cross-link

Add to `mkdocs.yml`'s `nav`, after `Methodology` and before `Algorithms`
(procedural content belongs near the conceptual "how this is measured"
page, ahead of the algorithm-reference pages):

```yaml
  - Measurement Procedure: measurement_procedure.md
```

Add a one-line pointer from `docs/index.md`'s "Start here" list, matching
the existing bullet style:

```markdown
- **[Measurement Procedure](measurement_procedure.md)** — the checklist
  for capturing a curve, running a tilt-sweep series, and (once available)
  a closed-loop run on the bench.
```

**Verify**: `uv run mkdocs build --strict --site-dir /tmp/mkdocs-check` ->
exit 0, no warnings.

### Step 6: full check

```bash
uv run mkdocs build --strict --site-dir /tmp/mkdocs-check
uv run pre-commit run markdownlint-cli2 --files docs/measurement_procedure.md docs/index.md mkdocs.yml
```

Both clean (re-stage any auto-fix from the second command).

## Test plan

Docs-only - `mkdocs build --strict` is the verification (broken internal
links, malformed nav entries, and bad Markdown all fail it). No unit
tests apply.

## Done criteria

- [ ] `docs/measurement_procedure.md` exists with the four sections above
      (or three plus a placeholder, per "Partial execution")
- [ ] `mkdocs.yml`'s nav includes it; `docs/index.md` links to it
- [ ] `uv run mkdocs build --strict --site-dir /tmp/mkdocs-check` - exit 0
- [ ] Every UI element/CLI flag named in the page was verified against
      the live code/`--help` output, not written from memory
- [ ] `improve/2026-07-18/plans/README.md` status row updated (including
      the partial-execution note if Step 4 was skipped)

## STOP conditions

Stop and report if:

- `run-algorithm` does not exist in `harness/cli.py` (per the hard
  dependency check) - fall back to "Partial execution" rather than writing
  Step 4 against the plan's design.
- `CurveWorkbench.tsx`'s actual save-form fields differ from what's quoted
  in "Current state" (per the drift check) - rewrite Steps 1-2 against the
  live UI, do not ship a checklist that tells an operator to click a
  button that doesn't exist.
- `mkdocs build --strict` fails for any reason - fix the actual issue
  (bad link, bad YAML) rather than dropping `--strict` to make it pass.

## Maintenance notes

- If the tilt-sweep angle convention (Step 2) turns out not to match what
  the bench mounting hardware can actually hold in practice, update this
  page directly - it is a living operator procedure, not a historical
  record like a plan file.
- Once plan 034's dynamic-conditions follow-up (mentioned in its own
  Maintenance notes) lands, this page's "Closed-loop runs" section is the
  right place to add that procedure too, not a new page.
