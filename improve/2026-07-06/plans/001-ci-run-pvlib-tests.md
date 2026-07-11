# Plan 001: Make CI actually run the pvlib-dependent half of the test suite

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6af6609..HEAD -- .github/workflows/ci.yml tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests / dx
- **Planned at**: commit `6af6609`, 2026-07-06

## Why this matters

5 of the 10 test files skip themselves entirely when the `pvlib` extra is not
installed, and the CI test job installs only the dev group. The result: the
full test suites for `ScanAndTrack`, `ParticleSwarm`, `FuzzyLogic`, `PvString`
and `PvlibPanelModel` never run in CI. A regression in the global MPPT
trackers - the thesis's core deliverable - would pass CI green today. The fix
is one flag in the workflow.

## Current state

- `.github/workflows/ci.yml` - the `test` job syncs without extras:

  ```yaml
  # .github/workflows/ci.yml (test job)
      - name: Sync project + dev deps
        run: uv sync --group dev
  ```

- Five test files gate on pvlib at import time:

  ```python
  # tests/test_scan_and_track.py:8 (same line in test_particle_swarm.py:8,
  # test_fuzzy.py:10, test_string.py:10, test_pvlib_model.py:10)
  pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402
  ```

- `pyproject.toml` defines the extra under `[project.optional-dependencies]`
  with key `pvlib`. Local installs use `uv sync --extra pvlib`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Sync with extra | `uv sync --group dev --extra pvlib` | exit 0 |
| Tests | `uv run pytest -q` | all pass, `0 skipped` |
| Lint | `uv run ruff check .` | exit 0 |

## Scope

**In scope** (the only file you should modify):

- `.github/workflows/ci.yml`

**Out of scope** (do NOT touch):

- `.github/workflows/docs.yml`, `firmware.yml`, `hardware.yml`,
  `entregables.yml`, `markdownlint.yml` - unrelated pipelines.
- The `lint` job in `ci.yml` - ruff does not need pvlib.
- The `importorskip` lines in `tests/` - they are correct; local installs
  without the extra should still skip gracefully.

## Git workflow

- Branch: `ci/run-pvlib-tests`
- Single commit, single-line conventional message, e.g.
  `ci: install pvlib extra so global-tracker tests run` (match the style in
  `git log --oneline`, e.g. `feat(simulation): NoisySource measurement-noise (#17)`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the extra to the test job's sync

In `.github/workflows/ci.yml`, in the `test` job only, change:

```yaml
      - name: Sync project + dev deps
        run: uv sync --group dev
```

to:

```yaml
      - name: Sync project + dev deps
        run: uv sync --group dev --extra pvlib
```

**Verify**: `grep -n 'uv sync' .github/workflows/ci.yml` shows the lint job
unchanged (`uv sync --group dev`) and the test job with `--extra pvlib`.

### Step 2: Prove the suite runs fully with that exact sync

```sh
uv sync --group dev --extra pvlib
uv run pytest -q
```

**Verify**: the final line reports all tests passed and does NOT contain
`skipped`. Record the total count in your report (expected: 122 at planning
time).

## Test plan

No new tests. The deliverable is that the existing 5 skipped files execute.

## Done criteria

- [ ] `test` job in ci.yml syncs with `--extra pvlib`; `lint` job unchanged
- [ ] `uv run pytest -q` locally: all pass, zero skipped
- [ ] `git status` shows only `.github/workflows/ci.yml` modified
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- `uv sync --group dev --extra pvlib` fails to resolve (pvlib/pandas/scipy
  pin conflict) - report the resolver error instead of changing pins.
- Any test fails with pvlib installed - those tests have never run in CI;
  a real failure here is a finding to report, not something to patch inside
  this plan.

## Maintenance notes

- pvlib pulls pandas and scipy; the CI test job will take noticeably longer
  on a cold cache. `setup-uv` caching absorbs this after the first run.
- If a future harness smoke job is added to CI (see plan 004 maintenance
  notes), it needs this same `--extra pvlib` sync.
