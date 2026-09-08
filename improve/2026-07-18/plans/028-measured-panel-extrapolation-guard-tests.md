# Plan 028: Tests for `MeasuredPanel`'s Voc-extrapolation guards

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> mpp_sdk/models/measured.py tests/test_measured_panel.py`. If either file
> changed since this plan was written, re-read `MeasuredPanel.__init__`'s
> extrapolation block before proceeding; on a mismatch between the excerpt
> below and the live code, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW - test-only change, no production code touched
- **Depends on**: none
- **Category**: test coverage
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`MeasuredPanel.__init__` (`mpp_sdk/models/measured.py:78-92`) extrapolates
the last two measured points to estimate Voc, guarded by two conditions
that exist specifically to reject a bad extrapolation rather than produce
a wrong or non-monotonic curve:

1. A **tight-gap guard**: if the sweep's last two distinct voltages sit
   much closer together than the sweep's average spacing (ADC noise
   repeating a voltage near the knee), the slope estimate from just those
   two points is unstable, so extrapolation is skipped entirely.
2. A **non-negative-slope guard**: if the last two points' slope isn't
   negative (noise, or a sweep that doesn't actually reach the knee),
   projecting forward would not converge to `I = 0` at a higher voltage,
   so extrapolation is skipped.

`tests/test_measured_panel.py` today tests `extrapolate=True` producing a
Voc *above* the measured max (`test_extrapolate_true_exceeds_measured_max_voltage`)
and `extrapolate=False` using the measured max as-is
(`test_extrapolate_false_uses_measured_max_voltage`) - but nothing exercises
either guard, i.e. nothing confirms that `extrapolate=True` **correctly
declines** to extrapolate when the input makes it unsafe to do so. A
regression here (e.g. accidentally inverting `gap >= 0.1 * avg_spacing` to
`<=`) would silently start producing a wrong Voc for exactly the noisy,
real-world sweeps this guard was written for - and nothing today would
catch it. Found via the `improve` skill's September 2026 audit (finding
TEST-02).

## Current state

The guarded block, `mpp_sdk/models/measured.py:78-92` (inside
`__init__`, `v_sorted`/`i_avg` are the ascending-sorted, duplicate-averaged
voltage/current lists built just above this):

```python
        if extrapolate:
            # Guard against an unstable slope estimate: two points that sit
            # much closer together than the sweep's average spacing (ADC
            # noise repeating a voltage near the knee) can yield a near-flat
            # slope and an extrapolated Voc far beyond the measured range.
            avg_spacing = (v_sorted[-1] - v_sorted[0]) / (len(v_sorted) - 1)
            gap = v_sorted[-1] - v_sorted[-2]
            if gap >= 0.1 * avg_spacing:
                slope = (i_avg[-1] - i_avg[-2]) / gap
                if slope < 0.0:
                    extrapolated_voc = v_sorted[-2] - i_avg[-2] / slope
                    if extrapolated_voc > voc:
                        voc = extrapolated_voc
                        v_sorted.append(voc)
                        i_avg.append(0.0)
```

`voc` before this block is `v_sorted[-1]` (the measured maximum voltage,
set at `mpp_sdk/models/measured.py:77`) - so "extrapolation was skipped"
is directly observable as `panel.open_circuit_voltage == <measured max>`.

The existing fixture sweep and both existing extrapolation tests
(`tests/test_measured_panel.py:9-17,59-66`):

```python
_SWEEP = [
    (21.3, 0.006),
    (20.1, 0.105),
    (18.1, 0.195),
    (15.8, 0.208),
    (8.0, 0.215),
]
...
def test_extrapolate_false_uses_measured_max_voltage():
    panel = MeasuredPanel.from_points(_SWEEP, extrapolate=False)
    assert panel.open_circuit_voltage == pytest.approx(21.3)


def test_extrapolate_true_exceeds_measured_max_voltage():
    panel = MeasuredPanel.from_points(_SWEEP, extrapolate=True)
    assert panel.open_circuit_voltage > 21.3
```

`_SWEEP` is *not* reused for the two new tests below - it does not trigger
either guard (its last-two gap and slope are both "normal"), so this plan
defines two new, purpose-built fixtures instead of trying to force
existing data through an unrelated code path.

## Scope

**In scope**:

- `tests/test_measured_panel.py` - add two new tests (Step 1 and Step 2
  below), placed in the existing "Endpoints" section (after
  `test_extrapolate_true_exceeds_measured_max_voltage`).

**Out of scope**:

- `mpp_sdk/models/measured.py` - no production code change. Both guards
  are believed correct today; this plan is regression coverage.
- The third condition in the same block (`extrapolated_voc > voc`, i.e.
  "the extrapolation must not project *backward*") - real but not named in
  the audit finding this plan implements; leave it uncovered rather than
  scope-creep this plan. A follow-up can add it the same way if wanted.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Run just this file | `uv run pytest tests/test_measured_panel.py -v` | all tests pass, including the 2 new ones |
| Full check (routine edit) | `uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Git workflow

- Branch: `test/measured-panel-extrapolation-guards`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: tight-gap guard test

The guard trips when `gap < 0.1 * avg_spacing` - build a sweep where every
point is evenly spaced ~5 V apart except the last two, which sit 0.05 V
apart (simulating ADC noise re-reading almost the same voltage right at
the knee):

```python
def test_extrapolation_skipped_when_last_gap_is_much_tighter_than_average():
    """avg_spacing here is 20.05/5 = 4.01 V; the last gap (20.05 - 20 =
    0.05 V) is far under 10% of that, so the slope estimate from just
    those two points is too unstable to trust - extrapolation must be
    skipped and Voc must fall back to the measured maximum."""
    sweep = [
        (0.0, 0.215),
        (5.0, 0.212),
        (10.0, 0.205),
        (15.0, 0.19),
        (20.0, 0.1),
        (20.05, 0.005),
    ]
    panel = MeasuredPanel.from_points(sweep, extrapolate=True)
    assert panel.open_circuit_voltage == pytest.approx(20.05)
```

**Verify**: `uv run pytest tests/test_measured_panel.py -v -k tighter_than_average`
-> 1 passed. If it fails, first confirm by hand that `gap (0.05) < 0.1 *
avg_spacing (0.401)` for this fixture (it does) - a failure means the guard
itself is broken, which is a real finding to report, not a fixture bug to
paper over.

### Step 2: non-negative-slope guard test

The guard trips when the last two points' slope isn't negative - build a
sweep where the gap is normal but current does not decrease into the last
point (as if noise bumped it up slightly right at the end):

```python
def test_extrapolation_skipped_when_the_final_slope_is_not_negative():
    """The last two points' slope here is (0.06 - 0.05) / 3 = +0.0033 -
    non-negative, so projecting forward would not converge to I=0 at a
    higher voltage. Extrapolation must be skipped and Voc must fall back
    to the measured maximum."""
    sweep = [
        (0.0, 0.215),
        (5.0, 0.212),
        (10.0, 0.205),
        (15.0, 0.19),
        (18.0, 0.05),
        (21.0, 0.06),
    ]
    panel = MeasuredPanel.from_points(sweep, extrapolate=True)
    assert panel.open_circuit_voltage == pytest.approx(21.0)
```

**Verify**: `uv run pytest tests/test_measured_panel.py -v -k final_slope_is_not_negative`
-> 1 passed. Same caveat as Step 1: confirm by hand this fixture's gap
(3.0) clears `0.1 * avg_spacing` (21.0/5 * 0.1 = 0.42) so the *first* guard
does not also trip here - this test must isolate the slope guard alone.

### Step 3: full file + routine checks

```bash
uv run pytest tests/test_measured_panel.py -v
uv run ruff check .
uv run ruff format --check .
```

All green.

## Test plan

This plan *is* the test plan - two new unit tests, no production code
change, each constructed to trip exactly one of the two named guards while
leaving the other guard's precondition satisfied (so a passing test
actually isolates the guard it claims to, not an accidental interaction
between both).

## Done criteria

- [ ] Both new tests added to `tests/test_measured_panel.py`'s
      "Endpoints" section
- [ ] `uv run pytest tests/test_measured_panel.py -v` - all pass
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] `git diff --stat` shows only `tests/test_measured_panel.py` changed
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Either guard's condition in `mpp_sdk/models/measured.py` has changed
  since this plan was written (per the drift check) - re-derive both
  fixtures' numbers against the new condition rather than forcing these
  exact values.
- Either new test fails against the current, unmodified implementation -
  that means a guard does not behave as its own comment claims, which is a
  real finding to report, not a fixture-tuning problem.

## Maintenance notes

- If the third guard condition (extrapolated Voc not exceeding the
  measured range) ever gets its own test, it belongs in this same
  "Endpoints" section, following the same isolate-one-guard-at-a-time
  pattern as these two.
