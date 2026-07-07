# Plan 003: Unit tests for PerturbAndObserve, the simulated sources and TabulatedPanel

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6af6609..HEAD -- mpp_sdk/algorithms/perturb_observe.py mpp_sdk/io tests/`
> plus `git diff --stat 6af6609..HEAD -- mpp_sdk/models/tabulated.py`.
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none (001 recommended first so CI runs everything)
- **Category**: tests
- **Planned at**: commit `6af6609`, 2026-07-06

## Why this matters

`PerturbAndObserve` is the only algorithm without a dedicated test file
(InCond has 11 tests, Fuzzy 11, PSO 15, ScanAndTrack 12) - yet it is the
tracker that both global algorithms (`ScanAndTrack`, `ParticleSwarm`) hand
control to after their search, so its sign convention is load-bearing for
every result. Likewise `SimulatedSource` / `DynamicSimulatedSource` are the
plant every simulation result runs on, and `TabulatedPanel` is the lookup
layer between them and the physics - none has direct tests. All of these are
testable with the in-tree `IdealSingleDiode`, so no pvlib is needed and the
tests run in CI unconditionally.

## Current state

- Files under test and the behavior worth pinning:
  - `mpp_sdk/algorithms/perturb_observe.py` - fixed-step P&O. Key contract
    (docstring lines 17-27): SEPIC sign convention, `dP*dV > 0 -> decrease D`,
    `dP*dV < 0 -> increase D`, `dP == 0 -> hold`. First `step()` always moves
    `+step_size` (lines 51-55). Constructor validates
    `0 <= min_duty < max_duty <= 1` and finite positive `step_size`
    (lines 37-40); initial duty is clamped (line 41).
  - `mpp_sdk/io/simulated.py` - static operating-point solver: bisection on
    `I_panel(V) = V / R_eff(D)`; `write()` moves the point instantly;
    validates `load_resistance > 0` (line 32).
  - `mpp_sdk/io/dynamic.py` - capacitor ODE variant. Starts at `Voc`
    (lines 59-61); `set_panel()` keeps state but clamps `V` to the new Voc
    (lines 77-86); validates `capacitance > 0`, finite `dt > 0`,
    `substeps >= 1` (lines 44-51).
  - `mpp_sdk/models/tabulated.py` - frozen `np.interp` I-V snapshot;
    `current()` returns scalar for scalar input, array for array
    (lines 30-34); `n < 2` raises (line 22).
- Only existing P&O coverage: `tests/test_smoke.py:70-84` (one convergence
  test) plus incidental use in `tests/test_incond.py:100` and
  `tests/test_noisy.py:94`.
- Exemplar for structure and idiom: `tests/test_incond.py` - plain pytest
  functions, section comment bars, a `_make_source()` helper built on
  `IdealSingleDiode` + `SEPICConverter` + `load_resistance=10.0`.
- Direction-decision testing idiom (no plant needed): feed `step()` a
  synthetic `(V, I)` sequence and assert the sign of the duty change, as
  `tests/test_incond.py` does for its decision table.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Sync | `uv sync --group dev` | exit 0 (pvlib not needed) |
| New tests | `uv run pytest tests/test_perturb_observe.py tests/test_sources.py tests/test_tabulated.py -q` | all pass |
| Full suite | `uv run pytest -q` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |

## Scope

**In scope** (create only):

- `tests/test_perturb_observe.py`
- `tests/test_sources.py`
- `tests/test_tabulated.py`

**Out of scope** (do NOT touch):

- Any file under `mpp_sdk/` - characterization only; a revealed bug is a
  STOP, not a fix.
- `tests/test_smoke.py` - keep its P&O convergence test where it is.
- `mpp_sdk/io/spi_mcu.py` - hardware-only, not testable off-target.

## Git workflow

- Branch: `test/pno-sources-tabulated`
- Single-line conventional commit, e.g.
  `test: unit-test P&O, simulated sources and TabulatedPanel`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: tests/test_perturb_observe.py

Model after `tests/test_incond.py`. Cover:

1. Construction: `min_duty >= max_duty` raises; `step_size=-0.01` raises;
   `step_size=float("nan")` raises; `initial_duty=2.0` clamps to `max_duty`.
2. First step moves `+step_size` exactly (start at 0.5, expect 0.505 with
   defaults).
3. Decision table with synthetic samples (start `initial_duty=0.5`,
   `step_size=0.01`; feed one priming sample, then one decision sample):
   - dP > 0 with dV > 0 -> duty decreases.
   - dP > 0 with dV < 0 -> duty increases.
   - dP < 0 with dV > 0 -> duty increases.
   - dP == 0 -> duty unchanged.
4. Clamping: repeated same-direction decisions never take `duty` outside
   `[min_duty, max_duty]`.
5. Convergence from both sides against `SimulatedSource` +
   `IdealSingleDiode` (copy the `_make_source` helper pattern from
   `tests/test_incond.py:35-41`, initial duties 0.1 and 0.9, 800 steps,
   final power > 0.99 of `panel.mpp()[2]`).

**Verify**: `uv run pytest tests/test_perturb_observe.py -q` -> all pass.

### Step 2: tests/test_sources.py

For `SimulatedSource` (all with `IdealSingleDiode()` and
`SEPICConverter()`, `load_resistance=10.0`):

1. `load_resistance=0` raises ValueError.
2. Operating point solves the circuit: after construction at duty 0.5,
   `read()` returns `(v, i)` with
   `abs(i - v / conv.reflected_resistance(0.5, 10.0)) < 1e-6`.
3. SEPIC sign convention: writing a higher duty yields a LOWER voltage
   (write 0.7, compare against duty 0.3 voltage).
4. `read()` is idempotent (two reads without a write return the same pair).
5. `write()` clamps: `write(2.0)` leaves `src.duty == 0.95` (converter
   default max).

For `DynamicSimulatedSource`:

1. Constructor validation: `capacitance=0`, `dt=0`, `substeps=0` each raise.
2. Initial state is open circuit: first `read()` returns
   `v == pytest.approx(panel.open_circuit_voltage)` and `i` near 0.
3. Slew, not jump: after ONE `write(0.5)`, the voltage moved toward the
   static solution but is still farther from it than after 200 writes
   (assert monotone approach: `abs(v_1 - v_static) > abs(v_200 - v_static)`).
   Get `v_static` from a `SimulatedSource` with the same panel/duty.
4. `set_panel` clamps to the new Voc: run to steady state, then
   `set_panel(TabulatedPanel(panel, n=100))` with a panel whose Voc is lower
   than the current terminal voltage; assert
   `read()[0] <= new_panel.open_circuit_voltage`. (Easiest low-Voc panel:
   `IdealSingleDiode` constructed with a smaller open-circuit voltage if the
   constructor exposes it - check `mpp_sdk/models/ideal.py`; otherwise scale
   via a small inline `PanelModel` subclass wrapping `IdealSingleDiode` and
   dividing its voltage. Inspect `mpp_sdk/models/ideal.py` before writing
   this test and use whatever parameter it actually has.)

**Verify**: `uv run pytest tests/test_sources.py -q` -> all pass.

### Step 3: tests/test_tabulated.py

1. `TabulatedPanel(panel, n=1)` raises.
2. Endpoints preserved: `open_circuit_voltage` and `short_circuit_current`
   match the wrapped `IdealSingleDiode` within 1e-9.
3. Interpolation accuracy: for 20 voltages across `[0, Voc]`,
   `abs(tab.current(v) - panel.current(v)) < 0.01 * panel.short_circuit_current`
   with the default `n=800`.
4. Scalar in, scalar out; array in, array out (check types/shapes).
5. Out-of-range: `current(-1.0)` returns `short_circuit_current`;
   `current(voc + 1.0)` returns `0.0` (the `left=`/`right=` fills at
   `mpp_sdk/models/tabulated.py:33`).

**Verify**: `uv run pytest tests/test_tabulated.py -q` -> all pass; then the
full suite and lint/format commands.

## Test plan

The steps are the test plan (roughly 20 tests across three files). Structure
follows `tests/test_incond.py`; no pvlib import anywhere in these files.

## Done criteria

- [ ] Three new test files exist and pass
- [ ] `uv run pytest -q` all pass; the three new files run even WITHOUT the
      pvlib extra (`uv sync --group dev` alone, no skips in these files)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- A decision-table test contradicts the docstring contract in
  `perturb_observe.py:17-27`: that would be a sign-convention bug affecting
  every published result. Report immediately.
- `mpp_sdk/models/ideal.py` has no way to build a lower-Voc panel and the
  inline-subclass fallback in the `set_panel` test (Step 2,
  DynamicSimulatedSource item 4) feels ambiguous - report instead of
  inventing model physics.

## Maintenance notes

- Plan 004's refactor of the harness relies on these plant behaviors staying
  fixed; any future change to `DynamicSimulatedSource.set_panel` semantics
  must update the `set_panel` clamping test deliberately.
- When adaptive-step P&O lands (TODO backlog), its tests should extend
  `tests/test_perturb_observe.py`'s decision-table idiom.
