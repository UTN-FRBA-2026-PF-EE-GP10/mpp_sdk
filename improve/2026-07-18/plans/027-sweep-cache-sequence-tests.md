# Plan 027: Sequence tests for `_SweepCache.set_progress`'s reset heuristic

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> scripts/curve_tracer_server.py tests/test_curve_tracer_server.py`. If
> either file changed since this plan was written, re-read
> `_SweepCache.set_progress` and the existing tests before proceeding; on a
> mismatch between the excerpt below and the live code, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW - two tests plus a comment-only production-code correction;
  runtime behavior is unchanged
- **Depends on**: none
- **Category**: test coverage
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`_SweepCache.set_progress` (`scripts/curve_tracer_server.py`) has a
non-obvious reset heuristic for deciding when a new stream of progress
updates belongs to a *new* sweep versus continuing the current one - it
has to guess, because `poll_sweep_progress()` is lossy (a missed poll is
just a gap, not a retry) and a brand-new sweep's first point (`index ==
0`) is routinely missed entirely. The two behaviors that heuristic
actually encodes - "an index below the current high-water mark means
a new sweep started" and "duplicate/out-of-order delivery of the same
point does not spuriously reset anything" - are exactly the kind of
easily-inverted-by-a-future-edit logic that has no test today. One related
case (a zero-point aborted sweep clearing stale partial) was already fixed
and tested in PR #67 (September audit finding #1); this plan covers the
two remaining untested branches of the same method, found via the
`improve` skill's September 2026 audit (finding TEST-01).

## Current state

`_SweepCache.set_progress`, in full, as it stands today
(`scripts/curve_tracer_server.py`, inside the `_SweepCache` class):

```python
    def set_progress(self, progress: SweepProgress | None) -> None:
        """Update the in-progress-sweep view from one
        `SpiMcuSource.poll_sweep_progress()` result. `None` (a lossy poll
        miss, or no sweep has ever run) leaves `partial`/`active` as they
        were - see that method's docstring."""
        if progress is None:
            return
        with self._lock:
            if progress.active:
                # A new sweep started if we weren't already mid-sweep, or
                # if this point's index is below the highest one we've
                # already recorded - indices only increase within a sweep,
                # so seeing one below our high-water mark means the
                # previous sweep's tail got skipped and this is the next
                # sweep's own early point. Checking index == 0 alone isn't
                # enough: poll_sweep_progress() is lossy and each
                # _poll_loop iteration can easily take longer than the
                # firmware needs to capture several points, so a new
                # sweep's very first point is often missed entirely - that
                # would otherwise leave the previous sweep's leftover
                # points bleeding into this one's `partial`.
                if not self._active or not self._partial or progress.index < max(self._partial):
                    self._partial = {}
                self._partial[progress.index] = (progress.voltage, progress.current)
            else:
                # `partial` only means anything mid-sweep - a sweep that
                # aborts with zero points (e.g. a dark/disconnected panel)
                # publishes only this one inactive update, with no
                # preceding active=True call to have triggered the reset
                # above, so without this a previous unrelated sweep's
                # partial would linger and be served as if it belonged to
                # this (empty) one.
                self._partial = {}
            self._active = progress.active
```

Two branches of the `if progress.active:` reset condition have no direct
test:

1. **Index-skip reset**: `progress.index < max(self._partial)` while
   `self._active` is already `True` and `self._partial` is non-empty -
   i.e. a new sweep's early point arrives (index low, e.g. 0 or 1) while
   the cache still thinks the *previous* sweep is active and holds its
   higher-indexed points. This must wipe `_partial` down to just the new
   point, not merge the two sweeps' points together.
2. **Duplicate-poll idempotency**: the same index delivered twice in a row
   (a real scenario - `poll_sweep_progress()` is documented as peek-not-
   consume in `DemoSweepSource`/`SpiMcuSource`, so a slow-polling client
   can observe the same in-progress point more than once before it
   advances). `progress.index < max(self._partial)` is **strictly** less
   than, so re-delivering the *current* max index must NOT reset
   `_partial` - it should just overwrite that one key with the same (or
   updated) value and leave every earlier point in place.

The existing test file already has the fixture and helper this plan
reuses - `tests/test_curve_tracer_server.py`:

```python
class _FakeProgress:
    def __init__(self, index, voltage, current, active, final_point=False):
        self.index, self.voltage, self.current = index, voltage, current
        self.active, self.final_point = active, final_point
```

and the existing test this plan's new tests sit next to
(`tests/test_curve_tracer_server.py:91-104`):

```python
def test_a_zero_point_sweep_clears_a_previous_sweeps_stale_partial(client):
    """A sweep that aborts with zero points (e.g. auto_range() finds no
    panel) publishes only one inactive update, with no preceding
    active=True calls of its own - `partial` must not keep serving the
    previous, unrelated sweep's leftover points as if they belonged to
    this (empty) one."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    client.cache.set_progress(_FakeProgress(255, 0.0, 0.0, active=False, final_point=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is False
    assert payload["partial"] == []
```

Note this test drives `_SweepCache` through the HTTP layer
(`client.get("/api/data")`), not by calling `cache.snapshot()` directly -
match that pattern for consistency, it is exercising the same code either
way since `/api/data`'s handler just calls `cache.snapshot()`.

## Scope

**In scope**:

- `scripts/curve_tracer_server.py` - correct the two comment phrases
  quoted above from "isn't past"/"at or below" to "is below"; leave the
  condition and all runtime logic unchanged.
- `tests/test_curve_tracer_server.py` - add the two tests below, in the
  same "GET /api/data" section as the existing progress tests (after
  `test_a_zero_point_sweep_clears_a_previous_sweeps_stale_partial`, line
  104-ish - insert after it, do not reorder existing tests).

**Out of scope**:

- Any runtime-logic change to `_SweepCache.set_progress`, or any other
  method on `_SweepCache` - this plan tests behavior that is already
  believed correct (both branches were deliberately written this way per
  their comments; this plan is regression coverage, not a bug fix).
- The one known, already-accepted residual race in this reset heuristic
  (documented in an earlier session: a very specific interleaving where a
  fast-completing next sweep's points could theoretically be misattributed
  before the "inactive" update arrives) - do not attempt to test or fix
  that here, it is out of scope by design.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Run just this file | `uv run pytest tests/test_curve_tracer_server.py -v` | all tests pass, including the 2 new ones |
| Full check (routine edit) | `uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Git workflow

- Branch: `test/sweep-cache-sequence-tests`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: correct the reset-condition comment

In `scripts/curve_tracer_server.py`, change the two misleading phrases in
the comment above the reset condition from "isn't past" and "at or below"
to "is below". The implementation uses strict `<` deliberately because
equality is a duplicate poll, covered in Step 3. Do not change code.

**Verify**: `git diff -- scripts/curve_tracer_server.py` shows only those
comment words changed; `progress.index < max(self._partial)` is untouched.

### Step 2: add the index-skip reset test

Insert into `tests/test_curve_tracer_server.py`, directly after
`test_a_zero_point_sweep_clears_a_previous_sweeps_stale_partial`:

```python
def test_an_index_below_the_high_water_mark_starts_a_new_sweep(client):
    """A new sweep's own early point (low index) arriving while the cache
    still thinks the previous, higher-indexed sweep is active must replace
    `partial`, not merge with it - see set_progress()'s comment on why
    index==0 alone isn't a reliable "new sweep" signal."""
    client.cache.set_progress(_FakeProgress(5, 15.0, 0.050, active=True))
    client.cache.set_progress(_FakeProgress(6, 14.5, 0.060, active=True))

    # Next sweep's first observed point - index 1, well below the previous
    # sweep's high-water mark of 6 - arrives while `active` is still True
    # (no intervening inactive update, matching how a fast next sweep can
    # actually be observed by a lossy poller).
    client.cache.set_progress(_FakeProgress(1, 21.0, 0.010, active=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is True
    assert payload["partial"] == [{"x": 21.0, "y": 10.0}]
```

**Verify**: `uv run pytest tests/test_curve_tracer_server.py -v -k index_below`
-> 1 passed.

### Step 3: add the duplicate-poll idempotency test

Insert directly after the test from Step 1:

```python
def test_redelivering_the_current_max_index_does_not_reset_partial(client):
    """poll_sweep_progress() is peek-not-consume (see SpiMcuSource /
    DemoSweepSource docstrings) - a slow poller can observe the same
    in-progress point more than once before the sweep advances. That must
    not be mistaken for a new sweep starting (the reset condition is
    index < max, strictly), and must not lose earlier points."""
    client.cache.set_progress(_FakeProgress(0, 21.3, 0.006, active=True))
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    # Same index (1) delivered again, same sweep still active.
    client.cache.set_progress(_FakeProgress(1, 20.1, 0.105, active=True))

    payload = client.get("/api/data").json()
    assert payload["active"] is True
    assert payload["partial"] == [
        {"x": 21.3, "y": 6.0},
        {"x": 20.1, "y": 105.0},
    ]
```

**Verify**: `uv run pytest tests/test_curve_tracer_server.py -v -k redelivering`
-> 1 passed.

### Step 4: full file + routine checks

```bash
uv run pytest tests/test_curve_tracer_server.py -v
uv run ruff check .
uv run ruff format --check .
```

All green.

## Test plan

This plan adds two unit tests plus a comment-only production-code fix,
both tests exercising `_SweepCache.set_progress` through the existing
`/api/data` HTTP round trip to match the file's established pattern.

## Done criteria

- [ ] Both new tests added to `tests/test_curve_tracer_server.py` in the
      "GET /api/data" section
- [ ] `uv run pytest tests/test_curve_tracer_server.py -v` - all pass
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] `git diff --stat` shows only `scripts/curve_tracer_server.py` and
      `tests/test_curve_tracer_server.py` changed; the script diff is
      comment-only
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `_SweepCache.set_progress`'s reset condition has changed since this plan
  was written (per the drift check) in a way that changes what "index-skip"
  or "duplicate-poll" mean - re-derive the two test scenarios against the
  new logic rather than forcing these exact assertions.
- Either new test fails against the current, unmodified implementation -
  that means the heuristic does not actually behave as its own comments
  claim, which is a real finding, not a test-authoring mistake. Report it
  rather than "fixing" the test to match broken behavior.

## Maintenance notes

- If a future change adds a third dimension to "what counts as a new
  sweep" (e.g. a sweep ID/nonce from the firmware, which would make this
  whole index-heuristic unnecessary), these two tests are exactly the ones
  that should be replaced, not kept alongside a better mechanism.
