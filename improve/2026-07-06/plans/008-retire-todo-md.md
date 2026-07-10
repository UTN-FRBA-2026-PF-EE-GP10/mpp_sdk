# Plan 008: Retire TODO.md - migrate its content into PLAN.md, AGENTS.md and docs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Preconditions (run first)**:
>
> 1. `git merge-base --is-ancestor e77ca9a HEAD && echo merged` prints
>    `merged` (the rescan/seeds branch is in; TODO.md is at its final
>    version).
> 2. Plan 007 status is DONE in `improve/2026-07-06/plans/README.md`
>    (the findings recorded in TODO.md's "Next" section already live in
>    `docs/` - without that, deleting TODO.md loses them).
>
> **Drift check**: `git diff --stat c647b61..HEAD -- TODO.md PLAN.md AGENTS.md`
> The e77ca9a merge changes TODO.md (expected); any PLAN.md/AGENTS.md drift
> means line references below shifted - re-locate by heading text, and on
> real contradiction treat as STOP.

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: LOW-MED (content migration; the risk is silently losing a
  backlog item, not breaking code)
- **Depends on**: merge of `feat/rescan-sweep-seed-stats` (`e77ca9a`),
  plan 007
- **Category**: tech-debt / docs
- **Planned at**: commit `c647b61`, 2026-07-06

## Why this matters

The operator decided to retire TODO.md as a tracking document (recorded in
the plans index). Its content is three different things stapled together:
completed-work findings (whose home is `docs/`, handled by plan 007), a
simulation backlog (whose home is the PLAN.md Roadmap the repo already
maintains), and a per-module definition of done (whose home is AGENTS.md's
process expectations). Six places in the repo reference TODO.md and would
dead-end after deletion - including `AUDIT_FOR_SEPTEMBER.md`, which an
audit agent will follow in September 2026.

## Current state

- `TODO.md` (post-merge version, from commit `e77ca9a`) has four parts:
  1. Header blockquote: scope note + "Done so far" inventory + "Findings
     so far live in docs/algorithms/".
  2. `## Next`: three items, all `[x]` done, each carrying its findings
     prose (NoisySource, rescan sweep, seed statistics).
  3. `## Backlog (simulation)`: the open items (see migration map below).
  4. `## Definition of done (per module)`: 3 numbered rules (unit tests
     under `tests/`, demo under `examples/` or harness entry, integration
     in the comparison harness).
- `PLAN.md` has a `## Roadmap` section with phases:
  `### Phase 2 - Realistic models` (line ~178), `### Phase 3 - Algorithm
  zoo` (~221), `### Phase 4 - Algorithm comparison harness` (~233),
  `### Phase 5 - Hardware demonstrator` (~276), `### Phase 6 - Paper /
  thesis` (~319). Locate by heading text, not line number.
- `AGENTS.md` has a `## Process expectations` section (near the end) with
  bullets like "Demos and the harness are living documentation".
- References to TODO.md outside it (verified by grep at planning time):
  - `harness/compare_bank.py:25` and `:100` - "per the sim-to-real
    protocol in TODO.md" (module docstring and METRICS_GUIDE string).
  - `scripts/export_iv_plecs.py:11` and `:54` - same protocol reference.
  - `data/plecs/README.md:18` - same.
  - `AUDIT_FOR_SEPTEMBER.md:134` - "Expected by week 16 (all were in
    `TODO.md` *Next* / *Backlog* in June)".
  The sim-to-real protocol these all point at is fully documented in
  `docs/methodology.md`, section "Sim-to-real: the three-layer comparison".

## Migration map (follow exactly; every Backlog item must land somewhere)

| TODO.md item | Destination | Note |
|--------------|-------------|------|
| Header "Done so far" + findings pointer | drop | inventory duplicated by README/PLAN status; findings in docs (plan 007) |
| Next: NoisySource, rescan sweep, seed stats (all done) | drop | findings live in `docs/methodology.md` + `docs/algorithms/` after plan 007 |
| Adaptive-step P&O | PLAN.md Phase 3 | add as an unchecked roadmap bullet if not already present |
| Own algorithm (model-informed candidate scan + cumulative-drift trigger) | PLAN.md Phase 3 | keep the "prototype after noise + rescan exist" rationale in one sentence |
| Harness test cases (isolated irradiance-ramp case missing) | PLAN.md Phase 4 | note cold start / steps / Voc trap already live in `compare_bank.py` |
| Sim-to-real comparison protocol (long item) | drop, reference | fully documented in `docs/methodology.md`; ensure PLAN.md Phase 4/5 mentions "protocol: docs/methodology.md" once |
| Robustness vs sample rate | PLAN.md Phase 4 | TODO itself says it is already in PLAN Phase 4 - verify present, else add |
| 3- and 4-peak shading patterns (3+ panel string config) | PLAN.md Phase 4 | keep the "panel_config only builds 2 panels" evidence |
| Implementation-cost metrics (state size, per-step compute) | PLAN.md Phase 5b | it exists for the MCU story |
| Auto-generated paper figures | PLAN.md Phase 6 | note it builds on `harness/common.py` once plan 004 lands |
| `SingleDiodeWithLosses` (low priority) | PLAN.md Phase 2 | likely already listed there ("in-tree" model) - verify, do not duplicate |
| Definition of done (3 rules) | AGENTS.md, Process expectations | as a "Definition of done for a new module" bullet list, same 3 rules verbatim |

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Reference sweep | `grep -rn "TODO.md" --include="*.py" --include="*.md" . \| grep -v ".git/\|improve/\|entregables/"` | empty after step 3 |
| Tests | `uv run pytest -q` | all pass (docstring edits cannot break them, prove it) |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Docs build | `uv run --group docs mkdocs build --strict` | exit 0 |
| Markdown lint | `uv run pre-commit run markdownlint-cli2 --all-files` | Passed |

## Scope

**In scope**:

- `TODO.md` (delete, last step)
- `PLAN.md` (Roadmap bullets per the map)
- `AGENTS.md` (definition-of-done bullets)
- `harness/compare_bank.py`, `scripts/export_iv_plecs.py`,
  `data/plecs/README.md` (reference strings only - no logic)
- `AUDIT_FOR_SEPTEMBER.md:134` (one sentence)

**Out of scope** (do NOT touch):

- `entregables/` and `improve/` mentions of TODO.md - historical records.
- Any code logic; in the two Python files you edit only docstring/guide
  strings.
- `docs/` - plan 007 owns the findings content.

## Git workflow

- Branch: `docs/retire-todo`
- Single-line conventional commit, e.g.
  `docs: retire TODO.md into PLAN.md roadmap and AGENTS.md`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Migrate the backlog into PLAN.md and AGENTS.md

Work through the migration map row by row against the LIVE TODO.md
(post-merge). For each PLAN.md destination, find the phase heading by text
and append the bullet in the phase's existing style; check first whether an
equivalent bullet already exists (Phase 2 and the sample-rate item likely
do) - annotate rather than duplicate. Add the definition-of-done rules to
AGENTS.md under "Process expectations".

**Verify**: every Backlog item of TODO.md appears (by keyword grep) in
PLAN.md or AGENTS.md, e.g. `grep -n "Adaptive-step\|candidate scan\|3- and
4-peak\|Implementation-cost\|paper figures" PLAN.md` hits all of them.

### Step 2: Repoint the six references

Replace "TODO.md" with "docs/methodology.md (sim-to-real comparison
protocol)" in: `harness/compare_bank.py:25`, `:100`;
`scripts/export_iv_plecs.py:11`, `:54`; `data/plecs/README.md:18`.
In `AUDIT_FOR_SEPTEMBER.md:134`, keep the historical truth and add the new
location, e.g.: "(all were in `TODO.md` *Next* / *Backlog* in June;
TODO.md has since been retired - the open backlog now lives in `PLAN.md`
*Roadmap*, the findings in `docs/`)".

**Verify**: the reference-sweep grep (Commands table) returns ONLY
TODO.md's own self-references (which disappear in step 3).

### Step 3: Delete TODO.md and run the full gate

`git rm TODO.md`, then run: reference sweep (now empty), `uv run pytest -q`,
ruff check + format, `mkdocs build --strict`, markdownlint all-files.

**Verify**: all commands green; `test -f TODO.md` fails.

## Test plan

No new tests. The full suite run in step 3 proves the two touched Python
files still import and pass (their only changes are string literals).

## Done criteria

- [ ] `TODO.md` deleted; reference sweep grep returns nothing outside
      `entregables/`, `improve/` and git history
- [ ] Every migration-map row landed (step 1 grep evidence in your report)
- [ ] AGENTS.md carries the 3 definition-of-done rules
- [ ] `AUDIT_FOR_SEPTEMBER.md` names the backlog's new home
- [ ] pytest, ruff, mkdocs --strict, markdownlint all green
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- Either precondition fails (branch not merged, plan 007 not DONE).
- The live TODO.md contains an item NOT covered by the migration map
  (something was added after planning) - report it; do not decide its
  destination yourself.
- A PLAN.md phase heading from the map cannot be found by text search.

## Maintenance notes

- After this lands, the backlog's single home is PLAN.md's Roadmap; new
  simulation ideas go there directly. The improve plans index tracks only
  audit-derived work, not the research roadmap.
- `AUDIT_FOR_SEPTEMBER.md` (to be executed ~2026-09-17) will follow the
  updated pointer; whoever edits PLAN.md's Roadmap before then should keep
  the phase structure so the audit's expectations stay resolvable.
