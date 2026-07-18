# Plan 008: Make NoisySource.read() idempotent (cache per control step)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- mpp_sdk/io/noisy.py tests/test_noisy.py harness/common.py`
> On any change, compare the excerpts below against the live code;
> mismatch = STOP. (A change in `harness/common.py` from plan 007 landing
> is expected and fine - only its `run_schedule` loop body matters here.)

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW-MED (changes the exact noise realization - documented noise
  findings must be re-checked)
- **Depends on**: 007 (its characterization tests must exist first)
- **Category**: bug
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

Every `SignalSource` in the SDK treats `read()` as "return the most recent
measurement" (`mpp_sdk/io/base.py:21`): `simulated.py`, `dynamic.py` and
`spi_mcu.py` all return cached values refreshed by `write()`. `NoisySource`
breaks that contract: each `read()` re-reads the inner source AND draws
fresh RNG noise, so two reads in the same control period disagree, and
run-to-run reproducibility depends on how many times `read()` happens to be
called. It is latent today only because `harness/common.py` reads the noisy
source exactly once per step - any future logger, HIL shim, or debugging
`read()` desyncs the seeded noise stream that `compare_noise.py`'s
published findings rely on.

## Current state

`mpp_sdk/io/noisy.py:62-71`:

```python
def read(self) -> tuple[float, float]:
    v, i = self._source.read()
    if self._v_std > 0.0:
        v += self._rng.gauss(0.0, self._v_std)
    if self._i_std > 0.0:
        i += self._rng.gauss(0.0, self._i_std)
    return v, i

def write(self, duty_cycle: float) -> None:
    self._source.write(duty_cycle)
```

`harness/common.py:117-123` (the one production caller) reads
`inner.read()` (true value) then `noisy.read()` (controller value), then
`ctl.step`, then `inner.write(d)` - note it writes to the INNER source,
so `NoisySource.write` is not in that loop.

`tests/test_noisy.py` pins current behavior including seeded streams -
expect to update it.

Docs that quote noise-sweep numbers (η percentages from
`harness/compare_noise.py`): `docs/algorithms/` pages and
`entregables/22_06_26/anteproyecto.md`. The qualitative claims (fixed-step
locals collapse ~0.5-1% FS, Fuzzy more robust, globals hold) must survive;
exact decimals may shift.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev --extra pvlib` | exit 0 |
| Focused | `uv run pytest -q tests/test_noisy.py tests/test_harness_common.py` | all pass |
| Full | `uv run pytest -q` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Noise sweep | `uv run harness/compare_noise.py` | completes, prints table |

## Scope

**In scope**:

- `mpp_sdk/io/noisy.py`
- `tests/test_noisy.py` (update expectations)
- `harness/common.py` - ONLY IF the read-order note in its docstring
  (lines 94-99, "the noise RNG stream stays identical run to run") needs
  rewording to match the new semantics; no logic change.

**Out of scope** (do NOT touch):

- Other sources (`simulated.py`, `dynamic.py`, `spi_mcu.py`) - they
  already honor the contract.
- `compare_noise.py` logic; docs/entregables numbers (report drift, don't
  edit history documents).
- `tests/test_harness_common.py` assertions (plan 007's tripwires - if one
  fails, STOP).

## Steps

### Step 1: Cache the noisy sample

Rework `NoisySource`: draw the noisy `(v, i)` ONCE per control step and
cache it. Sampling points: in `__init__` (initial cache from the inner
source's current reading) and in `write()` (after forwarding the duty).
`read()` returns the cache untouched. Update the class docstring: `read()`
is now idempotent per the `SignalSource` contract; the noise stream
advances exactly once per `write`.

Note the wiring consequence: in `harness/common.py` the loop writes to
`inner`, not to the `NoisySource` wrapper - so after this change the
wrapper's cache would never refresh there. Fix the wiring in
`run_schedule` by writing through the wrapper when it exists
(`(noisy or inner).write(d)`) - `NoisySource.write` forwards to the inner
source, so plant behavior is identical; only the noise-draw timing moves.
This is a 1-line change and IS in scope (amend the Scope caveat: this
line, plus the docstring, are the only `common.py` edits allowed).

**Verify**: `uv run pytest -q tests/test_harness_common.py` -> plan 007's
tests all still pass UNCHANGED (especially `test_run_schedule_noise_isolation`).

### Step 2: Update the NoisySource tests

Adjust `tests/test_noisy.py`: same-seed runs still reproduce; two
consecutive `read()`s now return the SAME tuple; the stream advances only
on `write()`. Add `test_read_idempotent_between_writes`.

**Verify**: `uv run pytest -q` -> all pass; lint clean.

### Step 3: Re-run the noise sweep and check the documented claims

Run `uv run harness/compare_noise.py`. Compare its table against the
qualitative claims: P&O/InCond collapse by 0.5-1% FS noise while Fuzzy and
the global trackers hold; no false restarts. Record before/after numbers
in the PR body.

**Verify**: the qualitative ordering holds. If any documented claim FLIPS
(e.g. Fuzzy no longer beats P&O at 1%), STOP.

## Test plan

Step 2's updated/added tests in `tests/test_noisy.py`, plus plan 007's
suite acting as the harness-level regression net.

## Done criteria

- [ ] Two `read()` calls between writes return identical tuples (test)
- [ ] Same-seed reproducibility test passes
- [ ] Plan 007's tests pass unmodified
- [ ] `uv run pytest -q` exits 0; lint clean
- [ ] Noise-sweep before/after table in the PR body; qualitative claims hold
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- Plan 007's tests are absent (it hasn't landed) - this plan depends on
  them.
- A `tests/test_harness_common.py` assertion fails after step 1.
- Step 3 flips a documented qualitative claim.

## Maintenance notes

- The HIL path gets this for free: `SpiMcuSource` already caches, so a
  noise-wrapper over it now behaves consistently.
- If a future caller needs fresh noise WITHOUT commanding duty, add an
  explicit `sample()` method - do not revert `read()` to drawing.
