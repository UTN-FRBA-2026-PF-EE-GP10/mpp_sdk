# Plan 022: Replay measured curves through the MPPT algorithm benchmark

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard prerequisite**: plan 021 (curve library) must be DONE - this plan
> consumes `mpp_sdk.curves`. Quick check: `uv run python -c "from
> mpp_sdk.curves.record import CurveRecord"` imports cleanly.
>
> **Drift check (run first)**: `git diff --stat f837fc2..HEAD --
> mpp_sdk/models/ mpp_sdk/io/ harness/`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (adds a `PanelModel`; the risk is silently producing
  physically wrong curves through bad interpolation, not breaking
  anything existing)
- **Depends on**: plan 021 (hard)
- **Category**: direction / feature
- **Planned at**: commit `f837fc2`, 2026-08-26

## Why this matters

This is the payoff for building the tracer. Every MPPT algorithm in this
SDK already runs against `PanelModel` implementations through
`SimulatedSource`; if a *measured* curve can present itself as a
`PanelModel`, then the entire existing comparison harness - P&O,
IncrementalConductance, FuzzyLogic, ScanAndTrack, ParticleSwarm - runs
against real panel data with **no algorithm changes at all**. That is
precisely the seam AGENTS.md protects ("Switching `SimulatedSource` →
`SpiMcuSource`, or porting an algorithm to firmware, must need no
algorithm code changes"), and it is what lets you predict how an algorithm
will behave on the real array before committing one to firmware.

The partial-shading case is where this earns its keep: a synthetic
`PvString` multi-modal curve is an educated guess, while a curve measured
with one panel tilted is what the array actually does.

## Current state

`mpp_sdk/models/base.py` - a `PanelModel` needs exactly three things:

```python
class PanelModel(ABC):
    @abstractmethod
    def current(self, voltage): ...          # scalar or numpy array
    @property
    @abstractmethod
    def open_circuit_voltage(self) -> float: ...
    @property
    @abstractmethod
    def short_circuit_current(self) -> float: ...
```

`power()`, `iv_curve()`, and `mpp()` are derived on the base class.

`mpp_sdk/models/tabulated.py` is the closest existing analogue - it
interpolates a cached grid and its docstring already names "measured
curves" as a motivating case:

```python
def current(self, voltage):
    v = np.asarray(voltage, dtype=float)
    # np.interp needs increasing x; our voltage grid already is.
    i = np.interp(v, self._v, self._i, left=self._isc, right=0.0)
    return float(i) if v.ndim == 0 else i
```

Note the ordering assumption: `TabulatedPanel` builds `_v` from
`iv_curve()`, which is `np.linspace(0, Voc, n)` - **ascending voltage**. A
measured sweep arrives in the opposite order (rising current, so falling
voltage), and is not evenly spaced. That mismatch is this plan's main
correctness concern.

`harness/common.py` and the `compare_*.py` scripts drive algorithms
against sources; `harness/panel_config.py` builds the panels they use.
Read both before Step 4.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `uv run pytest tests/ -q` | all pass |
| Lint | `uv run ruff check .` | "All checks passed!" |
| Format | `uv run ruff format --check .` | "N files already formatted" |

## Scope

**In scope**:

- `mpp_sdk/models/measured.py` (create)
- `mpp_sdk/models/__init__.py` (re-export)
- `tests/test_measured_panel.py` (create)
- `harness/compare_measured.py` (create)
- `harness/cli.py` (register the new command)
- `improve/2026-07-18/plans/README.md` (status row only)

**Out of scope**:

- Any change to `PanelModel`, `TabulatedPanel`, `SimulatedSource`, or any
  algorithm. If this plan seems to need one, that is a STOP condition -
  the whole point is that measured data fits the existing seam.
- Curve capture/storage (plan 021 owns it).
- Temperature/irradiance modelling. A measured curve *is* its conditions;
  do not try to re-derive them.

## Design

### `MeasuredPanel(PanelModel)`

```python
class MeasuredPanel(PanelModel):
    def __init__(self, record: CurveRecord, *, extrapolate: bool = True): ...

    @classmethod
    def from_points(cls, points, **kw) -> "MeasuredPanel": ...
```

Construction:

1. Take `(v, i)` from the record, sort **ascending by voltage** (measured
   order is the reverse), and drop duplicate voltages keeping the mean
   current - a real sweep can repeat a voltage near the knee, and
   `np.interp` requires strictly increasing `x`.
2. Establish endpoints. This is the part that needs care:
   - **Isc**: the sweep stops just past the knee, so the largest measured
     current is close to Isc but the corresponding voltage is not 0.
     Extend the curve to `V = 0` by holding that largest current flat
     (`left=` in `np.interp`). Physically sound - the I-V curve is nearly
     horizontal in the constant-current region.
   - **Voc**: the first point sits at near-zero but nonzero current
     (bench-measured ~6 mA against a 21.3 V reading). Extending to `I = 0`
     by holding voltage flat would misplace Voc slightly high. With
     `extrapolate=True`, linearly extrapolate the last two points to
     `I = 0` and use that as Voc; with `extrapolate=False`, use the
     measured maximum voltage as-is.

   Default to `extrapolate=True` and **document the choice in the class
   docstring**, because it materially affects where an algorithm thinks
   the curve ends.
3. Cache the prepared arrays; `current()` is then a `np.interp` in the
   same shape as `TabulatedPanel.current`, returning a float for scalar
   input and an array otherwise (`float(i) if v.ndim == 0 else i`).

Beyond `Voc`, current is 0. Below `V = 0`, return Isc.

`MeasuredPanel` is immutable and carries no irradiance/temperature knobs -
unlike `PvlibPanelModel`, its conditions are baked into the measurement.
Say so in the docstring so nobody looks for the missing setters.

Keep a reference to the source `CurveRecord` on the instance
(`.record`) so the harness can title plots from its label/measurement
without a parallel lookup.

### Why not reuse `TabulatedPanel`

`TabulatedPanel(panel, n)` samples an *existing model*; it cannot be
constructed from raw points, and its grid assumptions (ascending, evenly
spaced, starting at 0) do not hold for a measured sweep. Wrapping
`MeasuredPanel` in a `TabulatedPanel` afterwards for speed is valid and
costs nothing - mention it in the docstring, do not do it automatically.

### `harness/compare_measured.py`

Mirror the structure of the existing `compare_*.py` scripts (read
`compare_static.py` first and match its argument handling, figure
layout, and output path convention under `harness/output/`).

Behaviour: load every record via `mpp_sdk.curves.library.load_all()`,
group with `group_by_measurement()`, and for each measurement kind run the
standard algorithm bank against a `MeasuredPanel` built from each record,
producing one figure per kind with the record's `label` as the subplot
title. This is what "panes with titles saying which type of measurement"
looks like offline; plan 023 does the interactive version.

Register in `harness/cli.py`'s `_COMMANDS` as
`"compare-measured": ("harness.compare_measured", False)`.

## Steps

### Step 1: `MeasuredPanel`

Implement per the Design section in `mpp_sdk/models/measured.py`, and
re-export from `mpp_sdk/models/__init__.py` alongside the other models.
Follow `tabulated.py` for style and docstring depth.

**Verify**: `uv run python -c "
from mpp_sdk.models import MeasuredPanel
p = MeasuredPanel.from_points([(21.3,0.006),(18.0,0.195),(8.0,0.215)])
print(round(p.open_circuit_voltage,2), round(p.short_circuit_current,3))
print(round(p.current(0.0),3), round(p.current(1e6),3))
"` → Voc slightly above 21.3, Isc 0.215, `current(0)` = 0.215,
`current(1e6)` = 0.0.

### Step 2: tests

`tests/test_measured_panel.py`, modelled on the existing model tests:

- ascending/descending input order give the same curve (the ordering trap)
- duplicate voltages do not raise and are averaged
- `current(0) == short_circuit_current`; current past Voc is 0
- `mpp()` on a hand-built curve with an obvious peak lands on it
- `extrapolate=False` uses the measured max voltage; `True` exceeds it
- array input returns an array, scalar returns a float
- a `MeasuredPanel` satisfies `isinstance(p, PanelModel)` and its
  inherited `power()` / `iv_curve()` / `mpp()` all work

**Verify**: `uv run pytest tests/test_measured_panel.py -q` → all pass.

### Step 3: prove the seam holds

Confirm an unmodified algorithm runs against a measured curve end to end:

```bash
uv run python -c "
from mpp_sdk.models import MeasuredPanel
from mpp_sdk.io import SimulatedSource
from mpp_sdk.algorithms import PerturbAndObserve
p = MeasuredPanel.from_points([(21.3,0.006),(20.1,0.105),(18.1,0.195),(15.8,0.208),(8.0,0.215)])
src = SimulatedSource(p)
alg = PerturbAndObserve(initial_duty=0.5)
for _ in range(200):
    v, i = src.read(); src.write(alg.step(v, i))
print('settled V =', round(src.read()[0], 2), 'MPP V =', round(p.mpp()[0], 2))
"
```

→ runs without error and settles near the measured MPP voltage. Adjust the
`SimulatedSource` construction to match its actual signature (read
`mpp_sdk/io/simulated.py`); the point is that **no algorithm or source
code was modified**.

### Step 4: `harness/compare_measured.py` + CLI

Write the harness entry per the Design section and register it.

**Verify**: `uv run mpp-sdk compare-measured --help` runs; with at least
one saved curve present it produces a figure under `harness/output/`.
With an empty library it exits with a clear message, not a traceback.

### Step 5: plan index

Update this plan's row in `improve/2026-07-18/plans/README.md`.

## Test plan

- `tests/test_measured_panel.py` per Step 2 - no hardware, no files.
- `uv run pytest tests/ -q` → all pass.
- Step 3's seam check, run by hand.
- Once real curves exist: `mpp-sdk compare-measured` over a `baseline`
  and a `partial-shade` capture, and sanity-check that global trackers
  (`ScanAndTrack`, `ParticleSwarm`) beat local ones on the shaded curve.
  That comparison is the actual deliverable.

## Done criteria

- [ ] `uv run pytest tests/ -q` passes, including `test_measured_panel.py`
- [ ] `uv run ruff check .` / `uv run ruff format --check .` clean
- [ ] Step 3's script settles near the measured MPP with **zero** changes
      to any algorithm, source, or existing model
- [ ] `mpp-sdk compare-measured` produces per-measurement figures
- [ ] `git diff --name-only` touches no file outside this plan's In-scope
      list

## STOP conditions

Stop and report if:

- Making a measured curve satisfy `PanelModel` appears to require changing
  `PanelModel`, `SimulatedSource`, or any algorithm. That would mean the
  abstraction is wrong, which is an architectural decision for the
  operator, not a workaround to improvise.
- The measured curve is too coarse for the algorithms to behave sensibly
  (20 points across the full range). The fix is more points per sweep in
  firmware, not smoothing invented here - report and stop.
- Extrapolating to Voc produces a value that disagrees with the
  open-circuit voltage the tracer reports at zero load by more than a few
  percent; that means the extrapolation model is wrong for this hardware.

## Maintenance notes

- If the tracer ever sweeps *past* Isc into reverse, the "hold flat to
  V=0" assumption breaks - revisit `current()`'s `left=` handling.
- `MeasuredPanel` deliberately has no irradiance/temperature setters.
  Requests to add them are really requests for a *series* of measured
  curves (plan 024's dimmer sweep), not a mutable single curve.
- Wrap in `TabulatedPanel` if a long benchmark shows interpolation cost
  mattering; measure before adding that indirection.
