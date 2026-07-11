# Plan 004: Consolidate the harness scripts onto a shared harness/common.py

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6af6609..HEAD -- harness/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. NOTE: at planning time a local
> branch `feat/rescan-sweep-seed-stats` added `harness/compare_rescan.py`
> and `harness/compare_seeds.py`, both importing from
> `harness.compare_cyclic`. If those files exist on your checkout, they are
> IN scope for the verification runs (step 6) and their imports must keep
> working; if they do not exist, ignore every mention of them.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (the printed tables feed the thesis paper; they must not change)
- **Depends on**: 002 (characterization tests), 003 (plant tests); merge
  `feat/rescan-sweep-seed-stats` first if it is still unmerged
- **Category**: tech-debt
- **Planned at**: commit `6af6609`, 2026-07-06

## Why this matters

The algorithm roster is declared 5 times in 3 incompatible shapes, the
`read -> step -> write` measurement loop is re-implemented 6 times, and
`build_conditions` plus the `DynamicSimulatedSource(...)` construction (with
its magic numbers `load_resistance=10.0`, `dt=CONTROL_PERIOD_MS * 1e-3`) are
copy-pasted across scripts - while `panel_config.make_dynamic_source` exists
and the newer scripts do not use it. Adding one algorithm (adaptive-step P&O
and the thesis's own algorithm are both on the TODO) currently means editing
5+ files. Consolidating into `harness/common.py` makes "add an algorithm"
a one-line change and makes the TODO item "auto-generated paper figures"
nearly free.

## Current state

Duplication map (all at commit `6af6609`):

- `ALGORITHMS` rosters:
  - `harness/compare_static.py:28` and `harness/compare_dynamic.py:34` -
    `(label, class)` pairs, library-default constructor args (PSO
    `n_particles=5`, no `rescan_period`).
  - `harness/compare_cyclic.py:118-130` - `(label, factory(d))` with the
    deployed config: `ScanAndTrack(rescan_period=1000)`,
    `ParticleSwarm(n_particles=8, rescan_period=1000)`.
  - `harness/compare_bank.py:73-82` - `(label, factory(d))`, detector-only:
    `n_particles=8`, NO rescan_period (deliberate - see the comment at
    `compare_bank.py:69-72`; preserve it).
  - `harness/animate.py:47-53` - `(label, class, color)` triples with
    explicit colors: P&O `tab:blue`, InCond `tab:red`, Fuzzy `tab:green`,
    Scan&Track `tab:purple`, PSO `tab:orange`.
  - `harness/compare_noise.py:42` imports the cyclic roster; `snapshot.py:30`
    imports the animate roster.
- Run loops: `compare_static.final_point` (:42), `compare_dynamic.run` (:48),
  `compare_cyclic.run` (:218), `compare_bank.run` (:117, also records
  `(v, i, d)` traces), `compare_noise.run` (:94, wraps the source in
  `NoisySource`, grades on true power), `animate.Runner.advance` (:112).
- `build_conditions`: `compare_cyclic.py:203-215` (from a schedule) vs
  `compare_bank.py:106-114` (from SCENARIOS segments); identical body idea:
  `{irr: (TabulatedPanel(shaded_string(irr)), panel.mpp()[2])}`.
- `panel_config.make_dynamic_source` (`harness/panel_config.py:69-88`)
  wraps its argument in `TabulatedPanel(...)` unconditionally, which is why
  the cyclic/bank/noise scripts (whose conditions are already
  `TabulatedPanel`s) bypass it and hand-build `DynamicSimulatedSource`.

Repo conventions that apply: scripts are `uv run harness/<name>.py`
executables with module docstrings; `matplotlib.use("Agg")` before pyplot;
output PNGs under `harness/output/`; AGENTS.md "Prefer additive changes"
and "algorithms never import models or converters" (common.py lives in
harness, so it may import anything).

**Hard requirement: printed output of every script must be byte-identical
before and after this refactor** (same seeds, same constructor configs, same
table formatting). Plot COLORS are the one allowed visible change (see
step 5).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Sync | `uv sync --group dev --extra pvlib` | exit 0 |
| Tests | `uv run pytest -q` | all pass |
| Lint | `uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Run one script | `uv run harness/compare_cyclic.py` | table + `Saved: .../compare_cyclic.png` |

Each `compare_*` script takes seconds to a few minutes (cyclic is the
longest); run them serially.

## Scope

**In scope**:

- `harness/common.py` (create)
- `harness/compare_static.py`, `compare_dynamic.py`, `compare_cyclic.py`,
  `compare_bank.py`, `compare_noise.py`, `animate.py`, `snapshot.py`
- `harness/compare_rescan.py`, `harness/compare_seeds.py` (only if present;
  see drift note)

**Out of scope** (do NOT touch):

- `harness/panel_config.py` public API - you may ADD a parameter (step 1)
  but must not change existing call behavior.
- Anything under `mpp_sdk/` - constructor defaults there (PSO
  `n_particles=5` etc.) are published behavior.
- `tests/` except reading them; plan 002's tests must keep passing
  unmodified.
- Table formatting strings, METRICS_GUIDE texts, seeds, step counts.

## Git workflow

- Branch: `refactor/harness-common`
- One commit per step or one final commit; single-line conventional message,
  e.g. `refactor(harness): shared roster, run loop and conditions in common.py`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Capture the golden outputs

On the CLEAN tree (before any edit):

```sh
mkdir -p /tmp/harness_golden
for s in compare_static compare_dynamic compare_cyclic compare_bank compare_noise; do
  uv run harness/$s.py > /tmp/harness_golden/$s.txt 2>&1
done
uv run harness/snapshot.py > /tmp/harness_golden/snapshot.txt 2>&1
```

If `compare_rescan.py` / `compare_seeds.py` exist, capture them too.

**Verify**: each file ends with a `Saved: ...` line.

### Step 1: Let make_dynamic_source accept an already-tabulated panel

In `harness/panel_config.py`, add a keyword `tabulate: bool = True` to
`make_dynamic_source`; when `False`, pass `panel` through without wrapping
in `TabulatedPanel`. Default behavior unchanged.

**Verify**: `uv run pytest -q` all pass; `uv run harness/compare_dynamic.py`
output diff vs golden is empty.

### Step 2: Create harness/common.py

Module with docstring, containing:

1. `AlgorithmSpec = NamedTuple("AlgorithmSpec", [("label", str), ("color", str), ("make", Callable[[float], object])])`
   (typed properly; `make` takes the initial duty).

2. ```python
   def algorithm_specs(
       rescan_period: int | None = None,
       pso_particles: int = 5,
   ) -> list[AlgorithmSpec]:
   ```

   returning the five entries with animate's explicit colors (P&O
   `tab:blue`, InCond `tab:red`, Fuzzy `tab:green`, Scan&Track `tab:purple`,
   PSO `tab:orange`) and factories:
   - P&O / InCond / Fuzzy: `cls(initial_duty=d)` always.
   - Scan&Track: pass `rescan_period=rescan_period` only when not None,
     else default constructor.
   - PSO: `n_particles=pso_particles`, plus `rescan_period` when not None.
   Mapping to today's call sites: static/dynamic/animate/snapshot use
   defaults `(None, 5)`; cyclic and noise use `(1000, 8)`; bank uses
   `(None, 8)`.
3. `build_conditions(irradiance_pairs)` - takes an iterable of irr pairs
   (deduplicating), returns `{irr: (TabulatedPanel(shaded_string(irr)), p_mpp)}`
   exactly as `compare_cyclic.py:203-215` does today. Both existing callers
   can feed it a generator (`(irr for irr, _, _ in schedule)` /
   `(irr for _, _, segs in SCENARIOS for irr, _ in segs)`).

4. ```python
   def run_schedule(
       make_ctl, schedule, conditions, *,
       initial_duty, noise_v_std=0.0, noise_i_std=0.0, noise_seed=0,
   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   ```

   Returns `(v, i, d)` arrays of the TRUE plant values. Builds the inner
   `DynamicSimulatedSource` exactly as `compare_cyclic.run` does
   (`load_resistance=10.0`, `dt=CONTROL_PERIOD_MS * 1e-3`, first schedule
   entry's panel) - via `make_dynamic_source(..., tabulate=False)` from
   step 1 (that helper already fixes `dt` to `CONTROL_PERIOD_MS * 1e-3`
   internally and takes `initial_duty` as a parameter - pass it through).

   **`initial_duty` is NOT a constant across callers**: cyclic/noise use the
   module-level `INITIAL_DUTY = 0.5`, but `compare_bank` passes each
   scenario's own start duty `d0` (0.5 or 0.15, see `compare_bank.py:58-64`
   and the call at `:177-186`). `run_schedule` must apply the SAME value to
   both the source construction and `make_ctl(...)`, exactly as every
   current loop does. Getting this wrong breaks the byte-identical
   requirement on the `shade trap` scenario specifically (its whole point
   is the 0.15 start).

   When noise stds are nonzero, wrap in
   `NoisySource(inner, v_std=..., i_std=..., seed=...)` and feed the
   controller the noisy reading while recording the true one, exactly as
   `compare_noise.run` (:94-121) does. Schedule entries are
   `(irr, n_steps, anything)`; call `inner.set_panel(conditions[irr][0])`
   per entry.

   CRITICAL read-order note: `compare_noise.run` calls `inner.read()` then
   `src.read()` before `write`. `DynamicSimulatedSource.read()` is pure
   (no state advance, `mpp_sdk/io/dynamic.py:88-89`) and `NoisySource.read()`
   draws RNG only in itself, so the unified loop must call reads in the same
   order (true first, then noisy) to keep the noise RNG stream identical.

**Verify**: `uv run ruff check harness/common.py` exits 0;
`uv run python -c "from harness.common import algorithm_specs, build_conditions, run_schedule"`.

### Step 3: Port the schedule-based scripts

- `compare_cyclic.py`: replace its `ALGORITHMS` with
  `[(s.label, s.make) for s in algorithm_specs(rescan_period=RESCAN_PERIOD, pso_particles=8)]`,
  its `build_conditions` and `run` with thin wrappers that call
  `common.build_conditions` / `common.run_schedule` and return
  `powers = v * i` - KEEP the names `ALGORITHMS`, `build_conditions`, `run`
  exported from this module with their exact current signatures
  (`run(make_ctl, schedule, conditions)`), because `compare_noise.py` and
  (if present) `compare_rescan.py` / `compare_seeds.py` import them, and
  plan 002's tests import the profile functions. This is the additive
  pattern AGENTS.md asks for.
- `compare_noise.py`: keep importing the roster from `compare_cyclic`;
  replace its local `run` with a call to `common.run_schedule(...,
  noise_v_std=noise_fs * V_IN_MAX, noise_i_std=noise_fs * I_MAX,
  noise_seed=NOISE_SEED)`.
- `compare_bank.py`: roster from
  `algorithm_specs(pso_particles=8)` (keep the detector-only comment at
  :69-72); `build_conditions` from common; `run` becomes `run_schedule`
  with the scenario's `(irr, n)` segments mapped to `(irr, n, None)`.

**Verify** (the load-bearing gate):

```sh
for s in compare_cyclic compare_bank compare_noise; do
  uv run harness/$s.py > /tmp/harness_new_$s.txt 2>&1
  diff /tmp/harness_golden/$s.txt /tmp/harness_new_$s.txt && echo "$s OK"
done
```

Every diff must be EMPTY.

### Step 4: Port compare_static and compare_dynamic

Both keep their own `SCENARIOS` and per-script loop shape (static uses a
`SimulatedSource`, so `run_schedule` does not apply there - only the roster
changes). Replace their `ALGORITHMS` with
`[(s.label, lambda d, c=s.make: c(d)) ...]` - simplest faithful form:
`[(s.label, s.make) for s in algorithm_specs()]`, then construct with
`make(INITIAL_DUTY)` instead of `cls(initial_duty=INITIAL_DUTY)`.

**Verify**: diff printed output vs golden for both scripts - empty.

### Step 5: Port animate.py and snapshot.py to the shared roster

`animate.py`: replace its `ALGORITHMS` triples with `algorithm_specs()`
(same labels/colors; `Runner` takes `spec.make` instead of a class - update
`Runner.__init__` and `Runner.reset` accordingly, they currently call
`ctl_cls(initial_duty=...)` at `animate.py:88` and `:102`).
`snapshot.py` imports `ALGORITHMS` from animate (:30); keep that import
working (animate can re-export the specs under the name it uses, or
snapshot switches to `algorithm_specs()` - either, as long as labels,
colors and start duty stay identical).

Color note: after this step the `compare_*` plots stop using matplotlib's
positional `prop_cycle` colors and use the spec colors. Line colors in the
PNGs change for InCond/Scan&Track/PSO (printed tables do not). This is the
single intended visible change; mention it in the commit body? No - keep
the single-line commit, mention it in the PR description instead.

**Verify**: `uv run harness/snapshot.py` output text diff vs golden empty;
the PNG renders (file exists, nonzero size). `uv run harness/animate.py`
needs a display - skip if headless, snapshot covers the shared path.

### Step 6: Full verification sweep

```sh
uv run pytest -q                      # includes plan 002/003 tests
uv run ruff check . && uv run ruff format --check .
```

Re-run every golden diff one final time (and `compare_rescan` /
`compare_seeds` if present - their tables must also be identical).

## Test plan

No new test files: plan 002's characterization tests plus the golden-output
diffs ARE the safety net. If plan 002 is not merged yet, STOP.

## Done criteria

- [ ] `harness/common.py` exists; roster/loop/conditions defined once
- [ ] `grep -rn "PerturbAndObserve\|ParticleSwarm" harness/*.py` shows
      constructor calls only inside `harness/common.py` (plus imports);
      no script builds the roster from classes directly anymore
- [ ] All golden-output diffs empty (list them in your report)
- [ ] `uv run pytest -q` all pass; lint and format clean
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- ANY golden diff is non-empty. Do not rationalize a "tiny numeric
  difference" - it means a constructor arg, seed, RNG order or read order
  changed, and the paper's numbers are at stake.
- Plan 002's tests are absent from `tests/` (dependency not landed).
- `compare_rescan.py` / `compare_seeds.py` exist but import symbols this
  refactor would remove - re-export instead; if that is impossible, stop.

## Maintenance notes

- Adding an algorithm is now: one entry in `algorithm_specs` (plus its
  `mpp_sdk` implementation and tests). Reviewers should check new entries
  preserve per-script config mapping (deployed vs detector-only vs default).
- The "auto-generated paper figures" TODO item should build on
  `run_schedule` + `build_conditions`, not on per-script loops.
- Deferred deliberately: unifying the `METRICS_GUIDE` texts and the
  Agg/savefig boilerplate - low value, would churn the scripts' educational
  docstrings.
