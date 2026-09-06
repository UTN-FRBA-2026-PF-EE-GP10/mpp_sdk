# Plan 030: Dedup `ScanAndTrack`/`ParticleSwarm`'s shared validation, restart-trigger, and tracker-handoff code

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> mpp_sdk/algorithms/scan_and_track.py mpp_sdk/algorithms/particle_swarm.py
> mpp_sdk/algorithms/restart.py`. If any of these changed since this plan
> was written, re-read the changed file(s) in full before proceeding; this
> plan's diffs are written against exact current line content, and a stale
> excerpt is exactly how this kind of refactor introduces a silent
> behavior change - treat any mismatch as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED - this is pre-existing, working, safety-relevant control
  logic (global MPPT restart behavior); the risk is not that the extraction
  is hard, but that it is easy to *look* correct while subtly changing
  short-circuit evaluation order or argument order. Both algorithms'
  existing, currently-passing test suites are the primary safety net - see
  "Verification strategy" below.
- **Depends on**: none
- **Category**: tech debt
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`ScanAndTrack` (`mpp_sdk/algorithms/scan_and_track.py`) and `ParticleSwarm`
(`mpp_sdk/algorithms/particle_swarm.py`) are two independent global-search
strategies (grid scan vs. swarm optimization) that otherwise share the
exact same surrounding scaffold:

- Identical `min_duty`/`max_duty` range validation.
- Identical "finite positive number" validation, applied to different
  parameter names (`scan_step` in one, implicitly nothing analogous in the
  other beyond `track_step`, which both share).
- Identical `rescan_period` validation.
- Identical `PowerChangeDetector` construction from
  `restart_threshold`/`restart_samples` (`None` threshold -> no detector).
- Identical restart-trigger check: "is the periodic backstop due, or did
  the change detector just fire" - including a **non-obvious short-circuit
  dependency** (see "The short-circuit trap" below) that any naive
  refactor is likely to get wrong.
- Identical handoff to a `PerturbAndObserve` local tracker once the global
  search concludes (`initial_duty=<found duty>`, `step_size=track_step`,
  same `min_duty`/`max_duty`).

This is pre-existing debt (not introduced by any work this session), found
via the `improve` skill's September 2026 audit (finding DEBT-02). It is
real duplication with real risk: a future change to the restart-trigger
semantics (e.g. adding hysteresis) applied to only one of the two files is
exactly the kind of drift this plan prevents.

## Current state

Both files' relevant excerpts, reproduced here so an executor with no
other context can see the duplication directly (do not skip re-reading the
live files per the drift check above - only the load-bearing lines are
quoted).

**Validation + detector construction**, `scan_and_track.py:73-90`:

```python
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if not (math.isfinite(scan_step) and scan_step > 0):
            raise ValueError(f"scan_step must be a finite positive number; got {scan_step=}")
        if not (math.isfinite(track_step) and track_step > 0):
            raise ValueError(f"track_step must be a finite positive number; got {track_step=}")
        if rescan_period is not None and rescan_period <= 0:
            raise ValueError(f"rescan_period must be positive or None; got {rescan_period=}")
        self._min = min_duty
        self._max = max_duty
        self._scan_step = scan_step
        self._track_step = track_step
        self._rescan_period = rescan_period
        self._detector = (
            None
            if restart_threshold is None
            else PowerChangeDetector(threshold=restart_threshold, samples=restart_samples)
        )
```

`particle_swarm.py:86-110` (same three shared checks - `min_duty`/
`max_duty`, `track_step`, `rescan_period` - interleaved with its own
`n_particles`/`max_iterations` checks, plus the identical detector
construction):

```python
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")
        if n_particles < 2:
            raise ValueError(f"n_particles must be >= 2; got {n_particles=}")
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1; got {max_iterations=}")
        if not (math.isfinite(track_step) and track_step > 0):
            raise ValueError(f"track_step must be a finite positive number; got {track_step=}")
        if rescan_period is not None and rescan_period <= 0:
            raise ValueError(f"rescan_period must be positive or None; got {rescan_period=}")
        self._rescan_period = rescan_period
        self._min = min_duty
        self._max = max_duty
        ...
        self._detector = (
            None
            if restart_threshold is None
            else PowerChangeDetector(threshold=restart_threshold, samples=restart_samples)
        )
```

**Restart-trigger check**, `scan_and_track.py:113-120` (inside `step`):

```python
        if not self._scanning:
            rescan_due = (
                self._rescan_period is not None and self._steps_since_scan >= self._rescan_period
            )
            if rescan_due or (
                self._detector is not None and self._detector.update(voltage * current)
            ):
                self._begin_scan()
```

`particle_swarm.py:151-159` (same shape, different counter/method names):

```python
        if not self._optimizing:
            self._steps_tracking += 1
            rescan_due = (
                self._rescan_period is not None and self._steps_tracking >= self._rescan_period
            )
            if rescan_due or (
                self._detector is not None and self._detector.update(voltage * current)
            ):
                self._seed_swarm()  # shading changed (or backstop expired) — re-search
```

### The short-circuit trap

Read both `if rescan_due or (...)` lines above closely: **Python's `or`
short-circuits**, so when `rescan_due` is already `True`,
`self._detector.update(voltage * current)` is **never called** that step -
the detector does not see that sample. This is load-bearing: the detector
is stateful (it tracks a reference power and a consecutive-sample count -
see `PowerChangeDetector.update`'s docstring in `restart.py`), so feeding
it a sample it should have skipped (or skipping one it should have seen)
changes its state for every subsequent call. A refactor that separates
"compute `rescan_due`" from "call `detector.update`" into two unconditional
statements - even one that ends up with the same *return value* - would
silently break this.

**The fix**: extract the check into a single function that performs the
exact same `rescan_due or (detector is not None and detector.update(...))`
expression internally, so the short-circuit is preserved by construction,
not by the caller remembering to replicate it.

**Handoff to `PerturbAndObserve`**, `scan_and_track.py:138-143`:

```python
            self._tracker = PerturbAndObserve(
                initial_duty=best_duty,
                step_size=self._track_step,
                min_duty=self._min,
                max_duty=self._max,
            )
```

`particle_swarm.py:184-189` (identical shape, `self._gbest_x` instead of
`best_duty`):

```python
                self._tracker = PerturbAndObserve(
                    initial_duty=self._gbest_x,
                    step_size=self._track_step,
                    min_duty=self._min,
                    max_duty=self._max,
                )
```

### Where the shared code should live

`mpp_sdk/algorithms/restart.py` already exists specifically as "Restart
trigger shared by the global MPPT controllers" (its own module docstring)
and already holds `PowerChangeDetector`, which both files already import
from it. It is the natural home for these additional shared pieces - no
new module needed. `restart.py` does not currently import
`PerturbAndObserve`, and `perturb_observe.py` imports nothing from
`restart.py` (confirmed: `grep -n "^import\|^from"
mpp_sdk/algorithms/perturb_observe.py` shows only `math` and `.base`) - so
`restart.py` importing `.perturb_observe` introduces no circular import.

Name the new functions with a leading underscore
(`_validate_duty_range`, `_validate_finite_positive`,
`_validate_rescan_period`, `_make_restart_detector`, `_restart_due`,
`_make_local_tracker`) - they are implementation-sharing helpers between
two sibling modules in the same package, not part of the public API
(`mpp_sdk/algorithms/__init__.py` re-exports `PowerChangeDetector` only;
do not add these to it).

## Scope

**In scope**:

- `mpp_sdk/algorithms/restart.py` - add the six private helper functions.
- `mpp_sdk/algorithms/scan_and_track.py` - use them in place of the
  duplicated inline code.
- `mpp_sdk/algorithms/particle_swarm.py` - same.
- A new test file, `tests/test_restart_scaffold.py`, covering the new
  helpers directly (Step 5).

**Out of scope**:

- The scan-grid logic (`_build_scan_grid`, `_begin_scan`, the SCAN-phase
  branch of `step`) and the swarm logic (`_seed_swarm`, `_update_swarm`,
  the optimizing-phase branch of `step`) - these are the two algorithms'
  actual, non-shared strategies. Do not touch them.
- `PowerChangeDetector` itself (`restart.py`'s existing class) - unchanged,
  only new module-level functions are added alongside it.
- Any other algorithm (`PerturbAndObserve`, `IncrementalConductance`,
  `FuzzyLogic`) - they have no restart/global-search scaffold to share.
- Changing any validation error message text - keep messages
  byte-identical to today's (no test currently asserts on message text via
  `match=`, but do not gratuitously change user-facing exception text in a
  refactor plan).

## Verification strategy

This refactor's correctness is verified primarily by **the existing,
unmodified test suites for both classes continuing to pass unchanged** -
`tests/test_scan_and_track.py` and `tests/test_particle_swarm.py` already
exercise construction validation, restart-triggering (via the change
detector), and periodic rescan, end to end, against the real classes. Do
not weaken, skip, or rewrite any existing test in either file to make this
plan land - if an existing test fails after the refactor, that is this
plan revealing a real behavior change, and the fix is to correct the
extraction, not the test.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Both algorithms' existing suites, unchanged | `uv run pytest tests/test_scan_and_track.py tests/test_particle_swarm.py -v` | all pass, same count as before this change |
| New scaffold tests | `uv run pytest tests/test_restart_scaffold.py -v` | all pass |
| Full suite | `uv run pytest -v --tb=short` | all pass |
| Full check | `uv run ruff check . && uv run ruff format --check .` | clean |

## Git workflow

- Branch: `refactor/global-mppt-shared-scaffold`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: add the shared helpers to `restart.py`

Append to `mpp_sdk/algorithms/restart.py` (after the `PowerChangeDetector`
class; add `from .perturb_observe import PerturbAndObserve` to the file's
existing imports, alongside its current `import math`):

```python
def _validate_duty_range(min_duty: float, max_duty: float) -> None:
    if not 0.0 <= min_duty < max_duty <= 1.0:
        raise ValueError(f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}")


def _validate_finite_positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite positive number; got {name}={value!r}")


def _validate_rescan_period(rescan_period: int | None) -> None:
    if rescan_period is not None and rescan_period <= 0:
        raise ValueError(f"rescan_period must be positive or None; got {rescan_period=}")


def _make_restart_detector(
    restart_threshold: float | None, restart_samples: int
) -> "PowerChangeDetector | None":
    return (
        None
        if restart_threshold is None
        else PowerChangeDetector(threshold=restart_threshold, samples=restart_samples)
    )


def _restart_due(
    detector: "PowerChangeDetector | None",
    rescan_period: int | None,
    steps_since_restart: int,
    power: float,
) -> bool:
    """True if the periodic backstop is due, or the change detector fires on
    this sample. Preserves the original short-circuit order deliberately:
    when the backstop already fired, ``detector.update(power)`` is **not**
    called - see this plan's "The short-circuit trap" for why that matters
    (the detector is stateful; skipping or double-feeding a sample changes
    its behavior on every later call). Do not split this into two separate
    statements."""
    rescan_due = rescan_period is not None and steps_since_restart >= rescan_period
    return rescan_due or (detector is not None and detector.update(power))


def _make_local_tracker(
    duty: float, track_step: float, min_duty: float, max_duty: float
) -> PerturbAndObserve:
    return PerturbAndObserve(
        initial_duty=duty, step_size=track_step, min_duty=min_duty, max_duty=max_duty
    )
```

**Verify**: `uv run python -c "import mpp_sdk"` -> no ImportError (confirms
no circular import was introduced).

### Step 2: use the helpers in `scan_and_track.py`

Replace the four validation lines + detector construction
(`scan_and_track.py:73-90`, quoted in full in "Current state") with:

```python
        restart._validate_duty_range(min_duty, max_duty)
        restart._validate_finite_positive("scan_step", scan_step)
        restart._validate_finite_positive("track_step", track_step)
        restart._validate_rescan_period(rescan_period)
        self._min = min_duty
        self._max = max_duty
        self._scan_step = scan_step
        self._track_step = track_step
        self._rescan_period = rescan_period
        self._detector = restart._make_restart_detector(restart_threshold, restart_samples)
```

This requires importing the module itself rather than only the class it
currently imports. Replace
`from .restart import PowerChangeDetector` with `from . import restart`.
After the detector construction moves into `restart.py` there are no
remaining direct `PowerChangeDetector` references in this file; retaining
the old import would be unused and fail Ruff.
(Using the leading-underscore functions via a qualified module import
rather than direct `from .restart import _validate_duty_range` is a
deliberate style choice - it makes every call site visibly say "this comes
from the shared restart-scaffold module," which matters here specifically
because this plan's whole point is making the sharing visible; either style
is a reasonable engineering choice in general, but match this one so both
files read consistently with each other.)

Replace the restart-trigger check (`scan_and_track.py:113-120`) with:

```python
        if not self._scanning:
            if restart._restart_due(
                self._detector, self._rescan_period, self._steps_since_scan, voltage * current
            ):
                self._begin_scan()
```

Replace the tracker handoff (`scan_and_track.py:138-143`) with:

```python
            self._tracker = restart._make_local_tracker(
                best_duty, self._track_step, self._min, self._max
            )
```

**Verify**: `uv run pytest tests/test_scan_and_track.py -v` -> all pass,
same test count as before this step (compare against a run on the
pre-change file if in doubt).

### Step 3: use the helpers in `particle_swarm.py`

Same pattern. Replace the five validation lines that are shared (leave
`n_particles`/`max_iterations` checks exactly where they are, in their
original relative order) in `particle_swarm.py:86-110`:

```python
        restart._validate_duty_range(min_duty, max_duty)
        if n_particles < 2:
            raise ValueError(f"n_particles must be >= 2; got {n_particles=}")
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1; got {max_iterations=}")
        restart._validate_finite_positive("track_step", track_step)
        restart._validate_rescan_period(rescan_period)
        self._rescan_period = rescan_period
        self._min = min_duty
        self._max = max_duty
        ...
        self._detector = restart._make_restart_detector(restart_threshold, restart_samples)
```

(the `...` above stands for whatever unrelated lines already sit between
`self._max = max_duty` and the detector construction in the live file -
read it and keep them exactly as they are, only replacing the detector
construction's own three lines).

As in Step 2, replace this file's existing
`from .restart import PowerChangeDetector` with `from . import restart`.
There are no remaining direct class references after the constructor call
moves into the shared module.

Replace the restart-trigger check (`particle_swarm.py:151-159`) with:

```python
        if not self._optimizing:
            self._steps_tracking += 1
            if restart._restart_due(
                self._detector, self._rescan_period, self._steps_tracking, voltage * current
            ):
                self._seed_swarm()  # shading changed (or backstop expired) — re-search
```

Replace the tracker handoff (`particle_swarm.py:184-189`) with:

```python
                self._tracker = restart._make_local_tracker(
                    self._gbest_x, self._track_step, self._min, self._max
                )
```

**Verify**: `uv run pytest tests/test_particle_swarm.py -v` -> all pass,
same test count as before this step.

### Step 4: confirm the obsolete direct imports are gone

`from .perturb_observe import PerturbAndObserve` in both
`scan_and_track.py` and `particle_swarm.py` is still needed - both files
still reference `PerturbAndObserve` in their type annotations
(`self._tracker: PerturbAndObserve | None`). Confirm with:

```bash
grep -n "PerturbAndObserve" mpp_sdk/algorithms/scan_and_track.py mpp_sdk/algorithms/particle_swarm.py
if grep -n "PowerChangeDetector" mpp_sdk/algorithms/scan_and_track.py mpp_sdk/algorithms/particle_swarm.py; then
    echo "obsolete direct PowerChangeDetector reference remains"
    exit 1
fi
```

Expected: the first grep finds at least one `PerturbAndObserve` reference
in each file; the second grep prints nothing and the shell block exits 0.
Both files should access detector construction through
`restart._make_restart_detector`, with no direct `PowerChangeDetector`
reference or import remaining.

### Step 5: add direct tests for the new shared helpers

Create `tests/test_restart_scaffold.py`:

```python
"""Unit tests for the private validation/restart/handoff helpers shared by
ScanAndTrack and ParticleSwarm (mpp_sdk/algorithms/restart.py). These are
implementation details (leading-underscore, not part of the public API)
but are tested directly because they are exactly the kind of small,
easily-inverted logic (see restart.py's `_restart_due` docstring on the
short-circuit trap) that benefits from isolated coverage on top of the two
algorithms' own end-to-end test suites."""

import pytest

from mpp_sdk.algorithms import restart


def test_validate_duty_range_accepts_valid_range():
    restart._validate_duty_range(0.05, 0.95)  # must not raise


def test_validate_duty_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        restart._validate_duty_range(0.9, 0.1)


def test_validate_finite_positive_rejects_zero():
    with pytest.raises(ValueError) as exc:
        restart._validate_finite_positive("track_step", 0.0)
    assert str(exc.value) == "track_step must be a finite positive number; got track_step=0.0"


def test_validate_finite_positive_rejects_negative():
    with pytest.raises(ValueError):
        restart._validate_finite_positive("track_step", -0.01)


def test_validate_rescan_period_accepts_none():
    restart._validate_rescan_period(None)  # must not raise


def test_validate_rescan_period_rejects_zero():
    with pytest.raises(ValueError):
        restart._validate_rescan_period(0)


def test_make_restart_detector_none_threshold_gives_no_detector():
    assert restart._make_restart_detector(None, 3) is None


def test_make_restart_detector_builds_a_real_detector():
    detector = restart._make_restart_detector(0.2, 3)
    assert isinstance(detector, restart.PowerChangeDetector)


def test_restart_due_true_on_periodic_backstop_without_touching_detector():
    calls = []

    class _SpyDetector:
        def update(self, power):
            calls.append(power)
            return False

    # steps_since_restart (5) >= rescan_period (5): backstop fires. The
    # detector must NOT be consulted - this is the short-circuit this
    # function exists to preserve.
    assert restart._restart_due(_SpyDetector(), 5, 5, 12.3) is True
    assert calls == []


def test_restart_due_consults_the_detector_when_the_backstop_is_not_due():
    class _AlwaysFires:
        def update(self, power):
            return True

    assert restart._restart_due(_AlwaysFires(), 10, 3, 12.3) is True


def test_restart_due_false_when_neither_condition_holds():
    class _NeverFires:
        def update(self, power):
            return False

    assert restart._restart_due(_NeverFires(), 10, 3, 12.3) is False
    assert restart._restart_due(None, None, 3, 12.3) is False


def test_make_local_tracker_returns_a_seeded_perturb_and_observe():
    from mpp_sdk.algorithms.perturb_observe import PerturbAndObserve

    tracker = restart._make_local_tracker(0.42, 0.005, 0.05, 0.95)
    assert isinstance(tracker, PerturbAndObserve)
    assert tracker.duty == pytest.approx(0.42)
```

**Verify**: `uv run pytest tests/test_restart_scaffold.py -v` -> all 12
pass.

### Step 6: full verification

```bash
uv run pytest -v --tb=short
uv run ruff check .
uv run ruff format --check .
```

All clean. Pay particular attention to
`tests/test_scan_and_track.py`/`tests/test_particle_swarm.py`'s restart-
and rescan-related tests specifically (grep both files for `restart` and
`rescan` to find them) - these are the ones that would catch the
short-circuit trap if Step 2/3 got it wrong.

## Test plan

The 12 new unit tests in Step 5 isolate every extracted helper, with
particular emphasis on `_restart_due`'s short-circuit contract (the one
genuinely risky part of this refactor). The full, unmodified
`test_scan_and_track.py`/`test_particle_swarm.py` suites are the
integration check that both algorithms' end-to-end behavior (construction
validation, restart triggering, periodic rescan, handoff to local
tracking) is unchanged.

## Done criteria

- [ ] `mpp_sdk/algorithms/restart.py` has the six new private helpers
- [ ] `scan_and_track.py` and `particle_swarm.py` both use them in place of
      the duplicated inline code
- [ ] `tests/test_restart_scaffold.py` exists, 12 tests, all passing
- [ ] `uv run pytest tests/test_scan_and_track.py tests/test_particle_swarm.py -v`
      - same pass count as before this change
- [ ] `uv run pytest -v --tb=short` - full suite green
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Any excerpt quoted in "Current state" does not match the live file (per
  the drift check) - re-derive the extraction against the current code,
  do not force this plan's exact diffs onto changed source.
- Any existing test in `test_scan_and_track.py` or `test_particle_swarm.py`
  fails after Steps 2/3 - do not modify the failing test to make it pass;
  that is a real behavior regression this plan must not ship. Revert the
  specific extraction that caused it and report which one.
- `restart.py` importing `.perturb_observe` turns out to create a circular
  import after all (it should not, per the "Where the shared code should
  live" analysis, but confirm with Step 1's verify command before
  proceeding to Steps 2-3 regardless).

## Maintenance notes

- If a third global-search algorithm is ever added (the codebase currently
  has exactly two: grid scan and swarm), it should use these same six
  helpers from the start rather than re-duplicating the scaffold a third
  time.
- If the restart-trigger semantics ever need to change (e.g. requiring
  both the backstop *and* a minimum settle time), change `_restart_due`
  once in `restart.py` - that is the entire reason this plan exists.
