# Plan 005: Unconditionally stable integrator for DynamicSimulatedSource

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- mpp_sdk/io/dynamic.py tests/test_sources.py`
> On any change, compare the excerpts below against the live code first;
> mismatch = STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (numerical change; characterized by tests + golden harness runs)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

`DynamicSimulatedSource` integrates the panel-capacitor ODE with fixed-step
forward Euler. The stability bound is `h < 2*R_eff*C`. With the harness
defaults (`dt=1e-3`, `substeps=50` so `h=2e-5`, `C=100e-6`,
`R_load=10`), the reflected resistance at duty `D` is
`R_eff = R_load*((1-D)/D)^2`, which at `D=0.95` is 0.0277 Ohm - giving
`h/(R_eff*C) = 7.2 >> 2`. The integrator is unstable for `D >~ 0.909`; the
`max(0, min(v, voc))` clamp hides the divergence as a 0-to-Voc flip-flop
instead of NaN. `ScanAndTrack` sweeps `D` up to `max_duty=0.95` in every
scan (`mpp_sdk/algorithms/scan_and_track.py:65-68`), so the top scan
samples in EVERY published cyclic-harness run are corrupted. Any config
with a smaller `R_load` widens the broken region.

## Current state

`mpp_sdk/io/dynamic.py:63-75`:

```python
def _advance(self, duty: float) -> None:
    """Integrate the capacitor ODE over one control period."""
    r_eff = self._converter.reflected_resistance(duty, self._load)
    h = self._dt / self._substeps
    voc = self._panel.open_circuit_voltage  # constant over the control period
    v = self._v
    for _ in range(self._substeps):
        i_panel = float(self._panel.current(v))
        dvdt = (i_panel - v / r_eff) / self._cap
        v += dvdt * h
        v = max(0.0, min(v, voc))
    self._v = v
    self._i = float(self._panel.current(v))
```

Constructor defaults (`dynamic.py:39-51`): `capacitance=100e-6`, `dt` set by
callers (harness uses `1e-3`), `substeps=50`, all validated `> 0`.

The ODE is `C*dV/dt = I_panel(V) - V/R_eff`. The stiff term is the linear
`-V/R_eff`; `I_panel(V)` varies slowly over one substep.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync --group dev --extra pvlib` | exit 0 |
| Tests | `uv run pytest -q` | all pass |
| Focused | `uv run pytest -q tests/test_sources.py` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Golden run | `uv run harness/compare_cyclic.py` | completes, prints table |

## Scope

**In scope**:

- `mpp_sdk/io/dynamic.py` (`_advance` only)
- `tests/test_sources.py` (add tests)

**Out of scope** (do NOT touch):

- `mpp_sdk/converters/` (`reflected_resistance` is correct)
- Algorithm code, harness scripts, `panel_config.py` defaults
- The public constructor signature (keep `substeps` accepted)

## Steps

### Step 1: Exponential-Euler step for the linear term

Replace the explicit Euler update inside the loop with the exact solution
of the linearized substep (treat `i_panel` as constant over `h`):

```python
# v_eq is where V would settle if I_panel stayed constant.
v_eq = i_panel * r_eff
v = v_eq + (v - v_eq) * math.exp(-h / (r_eff * self._cap))
```

(`import math` at module top.) This is unconditionally stable for any
`h`, exact for constant `i_panel`, and reduces to the same first-order
behavior as Euler when `h << r_eff*C`. Keep the `[0, voc]` clamp as a
safety net; keep `substeps` and the per-substep `current()` refresh
unchanged.

**Verify**: `uv run pytest -q tests/test_sources.py` -> all existing tests
still pass (the change is within their tolerances; if one fails, inspect
whether its expectation encoded Euler artifacts before loosening anything -
report what you find in the PR body either way).

### Step 2: Regression tests

Add to `tests/test_sources.py` (match its existing style - plain pytest
functions, `mpp_sdk` public API only):

1. `test_dynamic_source_stable_at_high_duty`: build a
   `DynamicSimulatedSource` with `IdealSingleDiode`, `load_resistance=10`,
   `capacitance=100e-6`, `dt=1e-3`, `substeps=50`; `write(0.95)` 100
   times; assert every `read()` voltage is strictly inside `(0, voc)`
   after the first few steps AND that consecutive voltages are monotone
   (or change by < 1% of Voc) once settled - i.e. no 0/Voc flip-flop.
2. `test_dynamic_source_settles_to_load_line`: at fixed duty `0.5`, after
   enough steps, `V` satisfies `|I_panel(V) - V/R_eff| * r_eff < 1e-3 * voc`
   (steady state = load-line intersection).

**Verify**: `uv run pytest -q` -> all pass including the 2 new tests.

### Step 3: Golden harness sanity

Run `uv run harness/compare_cyclic.py`. Numbers will move slightly (the
high-duty scan samples are now physical instead of garbage). Record the
before/after efficiency table in your report.

**Verify**: script completes; no algorithm's efficiency changes by more
than ~2 percentage points (bigger jump = STOP, investigate).

## Test plan

Covered by step 2. Pattern: existing `tests/test_sources.py`.

## Done criteria

- [ ] `uv run pytest -q` exits 0, including the 2 new tests
- [ ] Lint/format clean
- [ ] `compare_cyclic` before/after table recorded in the PR body
- [ ] No files outside scope modified
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- An existing test encodes the unstable behavior tightly enough that the
  fix flips it and the right expectation is unclear.
- Step 3 shows an efficiency swing > 2 pp for any algorithm.
- The excerpt above no longer matches `dynamic.py`.

## Maintenance notes

- With the exponential step, `substeps=50` is now about accuracy of the
  nonlinear term only; a follow-up may lower it for speed (ties into the
  deferred PERF finding about numpy per-call overhead in this loop).
- Reviewer focus: the `v_eq` formula sign and that `r_eff` can be large at
  low duty (exp argument tiny - fine) and tiny at high duty (exp argument
  huge - `math.exp` underflows to 0.0 cleanly, giving `v = v_eq`; that is
  the correct stiff limit).
