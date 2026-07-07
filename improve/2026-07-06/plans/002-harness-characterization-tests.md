# Plan 002: Characterization tests for the cyclic-harness profile machinery

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6af6609..HEAD -- harness/compare_cyclic.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: 001 (so these tests also run in CI)
- **Category**: tests
- **Planned at**: commit `6af6609`, 2026-07-06

## Why this matters

Every efficiency table in the thesis paper flows through four functions in
`harness/compare_cyclic.py`: `make_profile` (the reproducible pseudo-random
shading schedule), `_ramp_chunks` (quantized irradiance ramps),
`plateau_spans` (mapping plateaus onto the flat power trace) and
`segment_stats` (per-plateau settling and final efficiency). None of them has
a single test. A silent off-by-one in `plateau_spans` would corrupt every
"trapped" count in the paper without failing anything. These functions are
pure and deterministic, so the tests are cheap - and they are the safety net
required before the harness consolidation refactor (plan 004) touches this
file.

## Current state

- `harness/` is an importable package (`harness/__init__.py` exists); scripts
  already do `from harness.panel_config import ...`, so
  `from harness.compare_cyclic import make_profile` works from the repo root.
- Importing `harness.compare_cyclic` pulls `mpp_sdk`, matplotlib (it calls
  `matplotlib.use("Agg")` at import, safe headless) and
  `harness.panel_config`, which imports `PvlibPanelModel` at module level.
  **So the test file must `importorskip("pvlib")`** like
  `tests/test_scan_and_track.py:8` does.
- The functions under test (signatures as of `6af6609`):

  ```python
  # harness/compare_cyclic.py:133  _ramp_chunks(start, end, n_steps)
  #   -> [(irr_pair, n_steps, None), ...] on the RAMP_QUANTUM (50.0) grid
  # harness/compare_cyclic.py:157  make_profile(seed=1, n_segments=30)
  #   -> (plateaus, schedule)
  #      plateaus: [(label, irr_pair, n_steps), ...], first is
  #                ("1000/1000", (1000.0, 1000.0), 800)   # COLD_START_STEPS
  #      schedule: [(irr_pair, n_steps, plateau_idx_or_None), ...]
  # harness/compare_cyclic.py:239  plateau_spans(schedule)
  #   -> [(start_index_in_flat_trace, n_steps, irr_pair), ...]
  # harness/compare_cyclic.py:250  segment_stats(powers, spans, conditions)
  #   -> (times, finals)  # settling_time and final_efficiency per plateau
  #      conditions maps irr_pair -> (panel, p_mpp); only [1] is used here
  ```

- Module constants the assertions can use: `PROFILE_SEED = 1`,
  `N_SEGMENTS = 30`, `LEVELS = (200.0, 400.0, 600.0, 800.0, 1000.0)`,
  `BRIGHT = (800.0, 1000.0)`, `SHADE = (200.0, 400.0)`,
  `MIN_SEG_STEPS, MAX_SEG_STEPS = 400, 1500`, `COLD_START_STEPS = 800`,
  `RAMP_QUANTUM = 50.0`, `BAND = 0.05`, `LAST_N = 100`.
- Test conventions: plain pytest functions, section comments, one file per
  module - model after `tests/test_restart.py` and `tests/test_incond.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Sync | `uv sync --group dev --extra pvlib` | exit 0 |
| New tests only | `uv run pytest tests/test_harness_cyclic.py -q` | all pass |
| Full suite | `uv run pytest -q` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Scope

**In scope**:

- `tests/test_harness_cyclic.py` (create)

**Out of scope** (do NOT touch):

- `harness/compare_cyclic.py` itself - this plan characterizes current
  behavior; if a test reveals a real bug, STOP and report it.
- `harness/compare_bank.py`, `compare_noise.py` - covered indirectly once
  plan 004 consolidates them onto these functions.

## Git workflow

- Branch: `test/harness-cyclic-characterization`
- Single-line conventional commit, e.g.
  `test(harness): characterize cyclic profile machinery`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create the test file skeleton

Create `tests/test_harness_cyclic.py` starting with:

```python
"""Characterization tests for harness/compare_cyclic.py profile machinery."""

import numpy as np
import pytest

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from harness.compare_cyclic import (  # noqa: E402
    BAND,
    COLD_START_STEPS,
    LEVELS,
    N_SEGMENTS,
    RAMP_QUANTUM,
    _ramp_chunks,
    make_profile,
    plateau_spans,
    segment_stats,
)
```

**Verify**: `uv run pytest tests/test_harness_cyclic.py -q` collects 0 tests,
exits without import errors.

### Step 2: make_profile tests

Write tests asserting, for the default seed:

1. **Determinism**: two calls with `seed=1` return equal plateaus and equal
   schedules (compare with `==`).
2. **Seed sensitivity**: `make_profile(seed=2)[0] != make_profile(seed=1)[0]`.
3. **Cold start**: `plateaus[0] == ("1000/1000", (1000.0, 1000.0), COLD_START_STEPS)`.
4. **Plateau count**: `len(plateaus) == N_SEGMENTS`.
5. **No repeated conditions**: consecutive plateau irradiance pairs differ.
6. **Vocabulary**: every plateau irradiance value is in
   `set(LEVELS) | {1000.0}` (BRIGHT and SHADE are subsets of LEVELS).
7. **Schedule/plateau consistency**: schedule entries with `idx is not None`
   appear in order 0..N_SEGMENTS-1, and each one's `(irr, n_steps)` matches
   `plateaus[idx][1:]`.

**Verify**: `uv run pytest tests/test_harness_cyclic.py -q` -> all pass.

### Step 3: _ramp_chunks tests

1. **Grid**: every irradiance value in every chunk is a multiple of
   `RAMP_QUANTUM`.
2. **Step conservation**: the chunk step counts sum to the requested
   `n_steps` (e.g. `_ramp_chunks((1000.0, 1000.0), (200.0, 400.0), 300)`).
3. **Terminal value**: the last chunk's pair equals the quantized end pair.
4. **Plateau-idx tag**: every chunk's third element is `None`.
5. **Degenerate ramp**: start == end produces a single chunk of `n_steps`.

**Verify**: same command, all pass.

### Step 4: plateau_spans tests

Use a hand-built schedule, no RNG:

```python
schedule = [((1000.0, 1000.0), 5, 0), ((900.0, 900.0), 3, None), ((800.0, 200.0), 7, 1)]
```

Assert spans are `[(0, 5, (1000.0, 1000.0)), (8, 7, (800.0, 200.0))]`: ramps
excluded, offsets cumulative over ALL entries.

**Verify**: same command, all pass.

### Step 5: segment_stats tests with synthetic powers

Build `conditions = {(1000.0, 1000.0): (None, 10.0)}` (the panel slot is
unused by `segment_stats`) and one span `[(0, 200, (1000.0, 1000.0))]`:

1. Powers constant at `10.0` -> settling time `0.0`, final efficiency `1.0`.
2. Powers constant at `5.0` (below the 5 % band) -> settling `None`, final
   `pytest.approx(0.5)`.
3. Powers that step from `5.0` to `10.0` at sample 100 -> settling
   `pytest.approx(100 * 1.0)` (dt is `CONTROL_PERIOD_MS = 1.0`), final `1.0`.

**Verify**: `uv run pytest tests/test_harness_cyclic.py -q` -> all pass;
then full `uv run pytest -q` -> all pass; then lint/format.

## Test plan

The steps above are the test plan (roughly 15 tests). Model structure and
naming after `tests/test_restart.py` (plain functions, section comment bars).

## Done criteria

- [ ] `tests/test_harness_cyclic.py` exists with tests covering all four
      functions, including at least one hand-built-schedule test that does
      not depend on the RNG
- [ ] `uv run pytest -q` all pass, no new skips beyond the existing pvlib gate
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0
- [ ] Only `tests/test_harness_cyclic.py` created; nothing else modified
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- Any characterization test fails against the CURRENT code: that is a real
  bug in the paper's data pipeline. Report the exact mismatch; do not
  "fix" either side silently.
- Importing `harness.compare_cyclic` fails for a reason other than missing
  pvlib.

## Maintenance notes

- Plan 004 moves these functions into `harness/common.py` with re-exports
  from `compare_cyclic`; these tests import from `harness.compare_cyclic`
  on purpose so the re-export path stays covered after that refactor.
- If `PROFILE_SEED`, `N_SEGMENTS` or the level sets change for a new
  experiment, the vocabulary/count tests will fail by design - update them
  together with the paper numbers.
