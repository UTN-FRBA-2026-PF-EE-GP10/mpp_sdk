# Plan 025: Add CI coverage for `frontend/` (typecheck, lint, build)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> .github/workflows/ frontend/`. If any in-scope file changed since this
> plan was written, compare the "Current state" excerpts against the live
> code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW - net-new workflow, path-scoped, cannot affect the Python
  or firmware CI jobs
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`frontend/` (React + TypeScript + Vite, ~15 source files, wired to a real
FastAPI backend) is a third first-class surface in this repo, comparable in
size and importance to the firmware crate. Firmware has its own CI job
(`.github/workflows/firmware.yml`, path-scoped, runs `cargo build` +
`clippy` + `fmt --check`) and Python has `ci.yml` (`ruff` + `pytest`), but
**nothing runs `tsc`, `oxlint`, or `pnpm build` for the frontend** - found
via the `improve` skill's September 2026 audit (finding DX-01, confirmed by
reading every file under `.github/workflows/`, none of which references
`frontend`, `pnpm`, `tsc`, `oxlint`, or `vite`).

Because the frontend's production build output
(`scripts/curve_tracer_web/`) is committed to git and manually regenerated
(`pnpm build`, by design - see `frontend/README.md`, "the Pi serves
prebuilt static files ... must not need Node installed at runtime"), a
broken `tsc -b`, a `pnpm-lock.yaml` drifted from `package.json`, or an
oxlint regression can land on `main` completely undetected until someone
happens to run the build locally.

## Current state

- `.github/workflows/firmware.yml` - the pattern to mirror. Full file
  reproduced below (also read it live - it is short):

  ```yaml
  name: Firmware

  on:
    push:
      branches: [main]
      paths: [firmware/**]
    pull_request:
      branches: [main]
      paths: [firmware/**]

  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

  jobs:
    build:
      name: cargo build --release
      runs-on: ubuntu-latest
      defaults:
        run:
          working-directory: firmware/pipico_board

      steps:
        - uses: actions/checkout@v4

        - name: Install Rust + thumbv6m target
          uses: dtolnay/rust-toolchain@stable
          with:
            targets: thumbv6m-none-eabi
            components: rustfmt, clippy

        - name: Cache cargo registry and build artefacts
          uses: Swatinem/rust-cache@v2
          with:
            workspaces: firmware/pipico_board

        - name: Format check
          run: cargo fmt --check

        - name: Build (release)
          run: cargo build --release --locked

        - name: Clippy
          run: cargo clippy --release --locked -- -D warnings
  ```

- `frontend/package.json`'s relevant scripts: `"build": "tsc -b && vite
  build"`, `"lint": "oxlint"`. Package manager is `pnpm` (there is a
  `frontend/pnpm-lock.yaml`, no `package-lock.json`/`yarn.lock`).
- `frontend/vite.config.ts` sets `build.outDir: '../scripts/curve_tracer_web'`
  and `emptyOutDir: true` - **running `pnpm build` on a CI runner
  overwrites `scripts/curve_tracer_web/` in the checkout**. This is fine
  (it's a throwaway checkout, not the developer's working tree) but means
  the workflow must NOT try to commit or diff that directory - it's purely
  a build-succeeds check, not a "is the committed output up to date" check
  (that would be a separate, larger plan - out of scope here, see
  "Maintenance notes").
- No `.nvmrc` or `engines` field exists anywhere specifying a required
  Node version - check `frontend/package.json` yourself to confirm this is
  still true; if an `engines.node` field has been added since this plan was
  written, use that version instead of guessing one.
- AGENTS.md / plan 023's original design explicitly required: "this one
  must not make the Python CI depend on a JS build" - a **separate,
  path-scoped** workflow satisfies that; it does not prohibit frontend CI
  entirely. Do not add anything to `.github/workflows/ci.yml`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install (local check) | `cd frontend && pnpm install --frozen-lockfile` | exit 0 |
| Lint | `cd frontend && pnpm lint` | exit 0 (pre-existing warnings in `src/components/ui/*.tsx` are fine - oxlint warnings, not errors, do not fail the command) |
| Build | `cd frontend && pnpm build` | exit 0, writes `scripts/curve_tracer_web/` |
| YAML sanity | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/frontend.yml'))"` | no exception |

## Scope

**In scope**:

- `.github/workflows/frontend.yml` (create)

**Out of scope**:

- `.github/workflows/ci.yml` - do not add any frontend/Node step to it.
- Any change under `frontend/src/` or `scripts/curve_tracer_web/` - this
  plan adds a CI gate, it does not fix anything the gate might find.
- Checking whether the *committed* `scripts/curve_tracer_web/` output is
  up to date with `frontend/src/` (i.e. failing CI if `pnpm build` produces
  a diff against the committed files) - that is a meaningfully different,
  stricter check with its own false-positive risks (non-deterministic
  build hashes, etc.) and deserves its own plan if wanted later. This plan
  only asserts "the frontend still typechecks, lints, and builds."

## Git workflow

- Branch: `chore/frontend-ci` (matches this session's established
  `<type>/<slug>` convention - see recent `git log --oneline` for examples
  like `chore/pin-ci-tool-versions`, `docs/curve-tracer-and-mkdocs`).
- One commit for the new workflow file.
- Do not push or open a PR unless the operator instructed it - check with
  them first if this plan was handed to you without that instruction.

## Steps

### Step 1: write the workflow file

Create `.github/workflows/frontend.yml`:

```yaml
name: Frontend

on:
  push:
    branches: [main]
    paths:
      - "frontend/**"
      - ".github/workflows/frontend.yml"
  pull_request:
    branches: [main]
    paths:
      - "frontend/**"
      - ".github/workflows/frontend.yml"

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    name: pnpm build
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend

    steps:
      - uses: actions/checkout@v4

      - uses: pnpm/action-setup@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml

      - name: Install (frozen lockfile)
        run: pnpm install --frozen-lockfile

      - name: Lint
        run: pnpm lint

      - name: Build (typecheck + vite build)
        run: pnpm build
```

Node 22 is a reasonable current LTS choice absent an `.nvmrc`/`engines`
pin - if you found one in "Current state", use that version instead.

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/frontend.yml'))"`
→ no exception.

### Step 2: confirm it matches what actually runs locally

**Verify**: from a clean checkout,

```bash
cd frontend
pnpm install --frozen-lockfile   # exit 0
pnpm lint                        # exit 0
pnpm build                       # exit 0, writes scripts/curve_tracer_web/
```

This is exactly what the new job runs - confirming it locally first means
a CI failure on first push is a real problem, not a workflow-authoring
mistake.

### Step 3: verify the job actually triggers

Push the branch and open the PR (per the "Git workflow" section - only
after operator confirmation). Confirm in the PR's checks list that a job
named "Frontend / pnpm build" appears and passes. Including the workflow
file itself in `paths` makes this introducing PR exercise the new job.
Confirm that the job does NOT
appear on a PR that touches only Python files (path-scoping working
correctly) - you can confirm the latter by checking that this repo's
*previous* PRs (which touched `scripts/`, `mpp_sdk/`, etc. but not
`frontend/`) did not trigger a `firmware.yml`-style job for an unrelated
path, by analogy; or simply trust the `paths:` filter, which GitHub Actions
enforces natively.

## Test plan

This plan adds infrastructure, not application code - there is no new unit
test. The test is the workflow itself succeeding on its own PR. Its path
filter includes both `frontend/**` and `.github/workflows/frontend.yml`,
so the introducing PR triggers the job without a meaningless frontend
source edit.

## Done criteria

- [ ] `.github/workflows/frontend.yml` exists and is valid YAML
- [ ] The introducing PR runs and passes `Frontend / pnpm build`
- [ ] Local `pnpm install --frozen-lockfile && pnpm lint && pnpm build`
      (from `frontend/`) all exit 0
- [ ] `.github/workflows/ci.yml` is unchanged (`git diff` shows it untouched)
- [ ] `git status` shows no files outside `.github/workflows/frontend.yml`
      modified
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `frontend/package.json` has gained an `engines.node` field that
  conflicts with the Node 22 default above - use the pinned version
  instead, but report the discrepancy.
- `pnpm install --frozen-lockfile` fails locally (lockfile drift) - this
  is a separate, pre-existing problem this plan should surface, not fix.
- Wiring the job in reveals `pnpm build` is not actually reproducible /
  idempotent from a clean checkout (e.g. it depends on some local-only
  state) - that is a bigger finding than this plan scoped for.

## Maintenance notes

- This job only proves the frontend *can* build, not that the *committed*
  `scripts/curve_tracer_web/` output matches current `frontend/src/`. If
  someone edits `frontend/src/` and forgets to run `pnpm build` before
  committing, this CI job will still pass (it builds fresh, in a throwaway
  checkout) while the Pi keeps serving stale assets. A follow-up plan could
  add a "build then `git diff --exit-code scripts/curve_tracer_web/`" check
  if that failure mode becomes a real problem - deliberately not done here
  to keep this plan's risk at LOW (a diff-check job is more prone to
  false positives from non-deterministic build output, e.g. content
  hashes in filenames, which is expected and fine here since Vite's
  hash-in-filename behavior means every build produces different asset
  filenames even with no source change).
- If `frontend/` ever adds a test suite (see the separate plan for
  `useLiveSweep`/`useConnectionStatus` hook tests, if selected), add a
  `pnpm test` step to this same job rather than a new workflow.
