# Plan 007: Characterization tests for harness/common.py

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- harness/common.py`
> On any change, compare the API excerpt below against the live code;
> mismatch = STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (additive test code only)
- **Depends on**: none (but plan 008 depends on THIS landing first)
- **Category**: tests
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

`harness/common.py` is a fresh consolidation that every harness script now
routes through (6 importers: `compare_static`, `compare_dynamic`,
`compare_cyclic`, `compare_bank`, `compare_noise`, `animate` - and
`snapshot` via `animate`). It has ZERO direct tests: no test file imports
`harness.common`. A regression in its run loop, roster, or noise plumbing
silently corrupts every published harness result and is caught only by a
human eyeballing a plot. These characterization tests are also the safety
net plan 008 (NoisySource semantics change) requires before it can land.

## Current state

`harness/common.py` public API (the whole module is 127 lines - read it):

- `AlgorithmSpec(NamedTuple)`: `label: str`, `color: str`,
  `make: Callable[[float], object]`.
- `algorithm_specs(rescan_period: int | None = None, pso_particles: int = 5)
  -> list[AlgorithmSpec]` - returns exactly 5 entries labeled
  `"P&O", "InCond", "Fuzzy", "Scan&Track", "PSO"` (that order); the last
  two thread `rescan_period` through only when it is not None, and PSO
  gets `n_particles=pso_particles`.
- `build_conditions(irradiance_pairs) -> dict[pair, (TabulatedPanel, p_mpp)]`
  - tabulates each DISTINCT pair once (`harness/common.py:65-72`).
- `run_schedule(make_ctl, schedule, conditions, *, initial_duty,
  noise_v_std=0.0, noise_i_std=0.0, noise_seed=0)` - builds a
  `DynamicSimulatedSource` (`load_resistance=10.0`, `tabulate=False`),
  swaps panels per segment via `set_panel`, loop body
  (`harness/common.py:117-123`):

  ```python
  v_true, i_true = inner.read()
  v_ctl, i_ctl = noisy.read() if noisy is not None else (v_true, i_true)
  d = ctl.step(v_ctl, i_ctl)
  inner.write(d)
  vs[k], is_[k], ds[k] = v_true, i_true, d
  ```

  Returns TRUE (noise-free) `(vs, is_, ds)` arrays of length
  `sum(n for _, n, _ in schedule)`; a schedule entry is `(irr_pair,
  n_steps, _label)`.

Conventions: tests are plain pytest functions in `tests/`, one file per
module, public API only. `build_conditions` needs pvlib (the string model
is the pvlib panel), so gate the module with
`pytest.importorskip("pvlib")` exactly like `tests/test_harness_cyclic.py`
does. Model the file structure on `tests/test_harness_cyclic.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev --extra pvlib` | exit 0 |
| Focused | `uv run pytest -q tests/test_harness_common.py` | all pass |
| Full | `uv run pytest -q` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Scope

**In scope**:

- `tests/test_harness_common.py` (create)

**Out of scope** (do NOT touch):

- `harness/common.py` itself - these are CHARACTERIZATION tests: they pin
  today's behavior, they do not "fix" anything. If a test you write fails,
  you found either a wrong expectation or a real bug - STOP and report,
  do not adjust the module.
- Every other harness script and test file.

## Steps

### Step 1: Roster tests

In `tests/test_harness_common.py`:

- `test_roster_labels_and_order`: `algorithm_specs()` returns 5 specs with
  the exact labels/order above; each `.make(0.5)` returns an
  `mpp_sdk.MPPTAlgorithm` instance whose first `step(1.0, 0.1)` returns a
  float.
- `test_roster_rescan_plumbing`: with `algorithm_specs(rescan_period=7)`,
  the Scan&Track and PSO instances differ in behavior from
  `rescan_period=None` ones - assert via public behavior: step a
  `rescan_period=7` Scan&Track instance with constant `(V, I)` well past
  its initial scan and assert it re-enters scanning (duty leaves the
  tracked neighborhood) within ~2*7 steps of scan completion, while the
  `None` variant holds steady over the same horizon. Keep the assertion
  loose (a window, not an exact step index).

**Verify**: `uv run pytest -q tests/test_harness_common.py` -> pass.

### Step 2: Conditions and run-loop tests

- `test_build_conditions_dedupes`: passing the same pair twice yields one
  dict entry; `p_mpp > 0`.
- `test_run_schedule_shapes_and_panel_swap`: 2-segment schedule with two
  different irradiance pairs, a stub controller (`step` returns a fixed
  duty, e.g. `lambda`-free tiny class), assert returned arrays have length
  `n1+n2` and that mean power in segment 2 differs from segment 1 (the
  `set_panel` swap took effect).
- `test_run_schedule_noise_isolation`: SAME stub fixed-duty controller run
  twice - once with `noise_v_std=0`, once with `noise_v_std=0.5` - returns
  IDENTICAL `vs/is_` arrays (the plant sees only the duty, which the stub
  fixes; the returned traces are the true values). This pins the
  true-vs-noisy split AND documents that noise only reaches the plant
  through the controller's reaction.

**Verify**: `uv run pytest -q tests/test_harness_common.py` -> all pass;
then the full suite `uv run pytest -q` -> all pass.

## Test plan

This plan IS the test plan. New file `tests/test_harness_common.py`, ~5
tests listed above, patterned on `tests/test_harness_cyclic.py`.

## Done criteria

- [ ] `tests/test_harness_common.py` exists with the 5 tests above
- [ ] `uv run pytest -q` exits 0; lint/format clean
- [ ] `harness/common.py` untouched (`git diff --stat` shows only the new
      test file)
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- Any characterization test fails against current behavior - that is a
  bug discovery, not a test bug; report it with the failing observation.
- The API excerpt above no longer matches `harness/common.py`.

## Maintenance notes

- Plan 008 (NoisySource cached-read) will make `noisy.read()` idempotent;
  `test_run_schedule_noise_isolation` should still pass unchanged (it
  asserts on true traces with a fixed-duty stub). If it breaks under plan
  008, that plan's executor must report, not weaken this test.
- When an algorithm is added to `algorithm_specs`, `test_roster_labels_and_order`
  is the intended tripwire - update the expected label list deliberately.
