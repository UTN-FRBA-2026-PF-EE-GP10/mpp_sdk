# Plan 007: Document the restart policy and the rescan/seed findings in docs/

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Precondition (run first)**:
> `git merge-base --is-ancestor e77ca9a HEAD && echo merged` must print
> `merged` - this plan documents findings produced by
> `harness/compare_rescan.py` and `harness/compare_seeds.py`, which land
> with that commit (branch `feat/rescan-sweep-seed-stats`). If not merged
> yet, STOP.
>
> **Drift check**: `git diff --stat c647b61..HEAD -- docs/ mkdocs.yml`
> (changes brought in by the e77ca9a merge itself do not touch `docs/`;
> any other diff means the docs moved since planning - compare excerpts
> before proceeding.)

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (docs only)
- **Depends on**: merge of `feat/rescan-sweep-seed-stats` (commit `e77ca9a`)
- **Category**: docs
- **Planned at**: commit `c647b61`, 2026-07-06

## Why this matters

The two newest experimental results - the rescan-period expected-loss model
(a derived-then-measured validation of the trigger policy) and the PSO seed
statistics (which crown Scan&Track as the MCU candidate) - exist only in
TODO.md prose and script output. Docs are the project's findings record
("Findings so far live in docs/algorithms/", TODO.md header), and plan 008
retires TODO.md, so these findings must land in docs first or they are
lost. Separately, `mpp_sdk/algorithms/restart.py` (`PowerChangeDetector`)
is the only algorithms module without a documentation page: its behavior is
described three times, partially, in three different pages.

## Current state

- `docs/algorithms/` has one page per algorithm: `perturb_observe.md`,
  `incremental_conductance.md`, `fuzzy_logic.md`, `scan_and_track.md`,
  `particle_swarm.md`. All share the same pandoc frontmatter pattern
  (copy it for any new page):

  ```yaml
  ---
  title: "Scan-and-Track (Global MPPT)"
  subtitle: "MPPT algorithm reference"
  geometry: "margin=2.2cm"
  fontsize: 11pt
  header-includes:
    - \usepackage{amsmath}
  ---
  ```

- The restart policy is currently described in three partial places:
  - `docs/algorithms/scan_and_track.md`, section "Re-scanning" (change
    detector + periodic re-scan, arming behavior).
  - `docs/algorithms/particle_swarm.md`, section "Restart on shading
    change" (same mechanisms from PSO's angle).
  - `docs/methodology.md`, section "Why global trackers need a trigger
    policy" (threshold 20 %, 3 samples, backstop rationale, measured trap
    numbers 44-67 %).
- Source of truth for detector behavior: the `PowerChangeDetector`
  docstring, `mpp_sdk/algorithms/restart.py:7-53` (arming after reset,
  in-band EMA reference with `smoothing` default 1.0, step-detector-only
  semantics, four-scalar MCU-portable state).
- `docs/methodology.md` "Three harnesses, three questions" table
  (lines 19-23) lists `compare_cyclic.py`, `compare_bank.py`,
  `compare_noise.py` - it predates `compare_rescan.py` and
  `compare_seeds.py`.
- `mkdocs.yml` nav lists the five algorithm pages (lines 33-37).
- The findings to document, verbatim numbers (authoritative source: the
  merged TODO.md "Next" section at commit `e77ca9a`, and each script's
  printed output - re-runnable with `uv run harness/compare_rescan.py` /
  `uv run harness/compare_seeds.py`, several minutes each):
  - **Rescan sweep** (`harness/compare_rescan.py`): eta energy and trapped
    count vs `rescan_period` in {250, 500, 1000, 2000, off} for the global
    trackers on the cyclic schedule. Expected-loss model:
    `L(P) = A/P + B*P` where A = search energy tax per re-scan (measured in
    a steady-full-sun calibration run) and B = trap exposure rate (from the
    backstop-off run over the mean plateau length). Derived optimum
    `P* = sqrt(A/B) ~ 1034` control steps lands on the empirical best
    (Scan&Track eta peaks at 95.0 % at period 1000). Over-frequent
    re-scanning (period 250) traps MORE often, not less - each sweep is
    itself a window for mid-scan changes.
  - **Seed statistics** (`harness/compare_seeds.py`): PSO over 30 seeds on
    the cyclic schedule gives eta 93.9 % +/- 0.7 and trapped plateaus
    7.9 +/- 1.7, vs the deterministic Scan&Track at 95.0 % and 5 traps -
    Scan&Track beats PSO's mean on both metrics with zero variance,
    reinforcing it as the MCU deployment candidate.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Docs build | `uv run --group docs mkdocs build --strict` | exit 0 |
| Markdown lint | `uv run pre-commit run markdownlint-cli2 --files docs/algorithms/*.md docs/methodology.md mkdocs.yml` | Passed |
| Optional: regenerate numbers | `uv run harness/compare_rescan.py` (needs `uv sync --extra pvlib`) | table incl. P* and per-period eta |

## Scope

**In scope**:

- `docs/algorithms/restart_policy.md` (create)
- `docs/algorithms/scan_and_track.md`, `docs/algorithms/particle_swarm.md`
  (add findings + cross-link; trim only what the new page fully absorbs)
- `docs/methodology.md` (harness table + trigger-policy section update)
- `mkdocs.yml` (one nav entry)

**Out of scope** (do NOT touch):

- `TODO.md` - plan 008 retires it; this plan only copies findings out.
- Code under `mpp_sdk/` and `harness/` - docs only.
- `entregables/` - frozen deliverables.
- `docs/algorithms/perturb_observe.md`, `incremental_conductance.md`,
  `fuzzy_logic.md` - local trackers have no restart policy.

## Git workflow

- Branch: `docs/restart-policy-findings`
- Single-line conventional commit, e.g.
  `docs: restart-policy page and rescan/seed findings`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create docs/algorithms/restart_policy.md

New page with the shared frontmatter (title "Restart Policy (Global MPPT
re-triggering)", subtitle "MPPT algorithm reference"). Sections:

1. **Why a trigger policy** - a global search costs energy, so it cannot
   run continuously; after hand-off the controller is a plain local tracker
   and cannot escape a re-shaded local peak. Condense from
   `docs/methodology.md` "Why global trackers need a trigger policy".
2. **Step detector** (`PowerChangeDetector`) - restart when
   `|dP|/P > threshold` (default 20 %) for `samples` (default 3)
   consecutive steps; arming-after-reset behavior; in-band reference
   follow; fires on steps, blind to slow ramps. Base it on the docstring at
   `mpp_sdk/algorithms/restart.py:7-53` - keep the docstring authoritative,
   the page explanatory.
3. **Periodic backstop** (`rescan_period`) - bounds worst-case trapped time
   to one period at the price of one search per period.
4. **Choosing the period: expected-loss model** - the centerpiece, from the
   "Current state" numbers: `L(P) = A/P + B*P`, what A and B are and how
   each is measured, `P* = sqrt(A/B) ~ 1034` vs empirical best 1000, the
   over-frequent-rescan pathology at 250. State that
   `harness/compare_rescan.py` regenerates the figure and table.
5. **Measured behavior** - trap rates with and without the policy
   (locals trap at 44-67 % of available power, methodology.md numbers) and
   the configured deployment (`rescan_period=1000`, detector on).

Use LaTeX math (`$$ ... $$`) like the sibling pages.

**Verify**: file exists; `uv run pre-commit run markdownlint-cli2 --files
docs/algorithms/restart_policy.md` -> Passed.

### Step 2: Cross-link the existing pages and add the findings

- `docs/algorithms/scan_and_track.md` ("Re-scanning" section): keep the
  two-mechanism summary, add one paragraph with the sweep result (eta peaks
  95.0 % at period 1000, derived P* ~ 1034; period 250 traps more) and a
  "see `restart_policy.md` for the model" pointer.
- `docs/algorithms/particle_swarm.md` ("Restart on shading change" keeps
  its PSO-specific arming/reseeding text plus the same pointer; extend the
  "Implementation" section's swarm-size paragraph with the seed statistics:
  30 seeds, eta 93.9 % +/- 0.7, trapped 7.9 +/- 1.7, vs Scan&Track 95.0 % /
  5 traps with zero variance - the deterministic scan is the stronger MCU
  candidate).
- Do NOT delete the per-page sections; they stay as summaries. Only remove
  sentences that are verbatim duplicated by the new page.

**Verify**: `grep -l "restart_policy" docs/algorithms/*.md` lists
`scan_and_track.md` and `particle_swarm.md`.

### Step 3: Update methodology.md

- "Three harnesses, three questions" table: add two rows -
  `compare_rescan.py` ("What is the right rescan period?" / sim-only,
  feeds the trigger-policy figure) and `compare_seeds.py` ("How
  seed-sensitive is the stochastic tracker?" / sim-only).
- "Why global trackers need a trigger policy": add the measured optimum
  sentence (P* ~ 1034 derived, 1000 empirical) and the pointer to
  `algorithms/restart_policy.md`.
- "Reproducibility": add that stochastic algorithms are reported as
  mean +/- std over 30 seeds (`compare_seeds.py`), never a single seed.

**Verify**: the harness table has 5 rows;
`uv run pre-commit run markdownlint-cli2 --files docs/methodology.md` Passed.

### Step 4: mkdocs nav and strict build

Add `- Restart policy: algorithms/restart_policy.md` to the Algorithms nav
block in `mkdocs.yml` (after Particle Swarm, `mkdocs.yml:37`).

**Verify**: `uv run --group docs mkdocs build --strict` exit 0 (strict mode
fails on nav/link errors, which also validates the new cross-links).

## Test plan

Docs-only: the strict mkdocs build plus markdownlint are the gates. If you
choose to verify the numbers, `uv run harness/compare_rescan.py` and
`uv run harness/compare_seeds.py` must print values matching the page
(several minutes each; requires `uv sync --extra pvlib`).

## Done criteria

- [ ] `docs/algorithms/restart_policy.md` exists, covers detector, backstop
      and the expected-loss model with the P* ~ 1034 / 1000 numbers
- [ ] `particle_swarm.md` carries the 30-seed statistics;
      `scan_and_track.md` carries the sweep optimum
- [ ] `methodology.md` harness table lists all five experiment harnesses
- [ ] `uv run --group docs mkdocs build --strict` exit 0
- [ ] Only the four in-scope files (plus the new page) modified
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- The precondition merge check fails (`e77ca9a` not an ancestor).
- The numbers in the merged TODO.md "Next" section contradict this plan's
  "Current state" numbers - the branch may have been amended after
  planning; report the discrepancy, do not pick one silently.
- `mkdocs build --strict` fails for a reason unrelated to your edits.

## Maintenance notes

- Plan 008 (retire TODO.md) depends on this plan having landed the
  findings; its reference-repointing sends readers to `methodology.md` and
  this new page.
- When the adaptive-step P&O or the own algorithm lands, its restart
  interaction belongs in `restart_policy.md`, not in a fourth scattered
  section.
- Reviewer focus: the A/B definitions in the expected-loss section must
  match what `harness/compare_rescan.py` actually computes (calibration
  run = A, backstop-off run = B), not a paraphrase that drifts.
