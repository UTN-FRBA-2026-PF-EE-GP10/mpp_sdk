# Plan 029: Dedup the P-V-curve-plus-final-points plot body shared by `compare_static.py` and `compare_measured.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> harness/common.py harness/compare_static.py harness/compare_measured.py`.
> If any of these changed since this plan was written, re-read the changed
> file(s) in full and compare against the excerpts below before proceeding;
> on a mismatch, treat it as a STOP condition - **this plan's core risk is
> a subtle behavior difference between the two scripts (see "The one
> behavioral trap" below), so do not proceed on stale excerpts.**

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: MED - not because the change is complex, but because the two
  call sites have one non-obvious behavioral difference (fresh vs. reused
  panel instance per algorithm) that a careless extraction would silently
  collapse into one behavior for both. See below.
- **Depends on**: none
- **Category**: tech debt
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`harness/compare_static.py` (inside its per-scenario loop,
`compare_static.py:50-71`) and `harness/compare_measured.py`'s
`_plot_record` (`compare_measured.py:37-58`) each independently implement
the same ~15-line plot body: draw the P-V curve, star the global MPP,
settle every registered algorithm and mark its final operating point, then
format axis labels/legend/grid/limits. `harness/common.py` already exists
precisely to hold shared harness plumbing (`algorithm_specs`, `final_point`,
`build_conditions`, `run_schedule` - see its own module docstring: "Every
`compare_*` script used to declare its own copy... this module is the
single place those live") - this plot body is the one remaining piece of
that pattern that hasn't been moved in yet. Found via the `improve` skill's
September 2026 audit (finding DEBT-01).

## Current state

`compare_static.py`'s per-scenario loop body
(`harness/compare_static.py:50-71`):

```python
    for ax, (title, panel_fn) in zip(axes, SCENARIOS, strict=True):
        panel = panel_fn()
        v_curve, i_curve = panel.iv_curve(n=400)
        p_curve = v_curve * i_curve
        v_mpp, _, p_mpp = panel.mpp()

        ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
        ax.plot(v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"global MPP ({p_mpp:.2f} W)")

        for (label, make_ctl), color in zip(ALGORITHMS, colors, strict=False):
            v_f, p_f = final_point(make_ctl, panel_fn())
            eta = p_f / p_mpp
            ax.plot(v_f, p_f, "o", color=color, ms=10, zorder=4, label=f"{label}: {p_f:.2f} W")
            print(f"{title:<32}{label:<10}{v_f:<9.2f}{p_f:<9.2f}{eta * 100:5.1f} %")

        ax.set_title(title)
        ax.set_xlabel("Voltage [V]")
        ax.set_ylabel("Power [W]")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
```

(`final_point` here is the module-level wrapper at
`compare_static.py:37-38`, which just forwards to `common.final_point`
with this script's `N_STEPS`/`INITIAL_DUTY`.)

`compare_measured.py`'s `_plot_record` (`harness/compare_measured.py:37-58`):

```python
def _plot_record(ax, record, colors) -> None:
    panel = MeasuredPanel(record)
    v_curve, i_curve = panel.iv_curve(n=400)
    p_curve = v_curve * i_curve
    v_mpp, _, p_mpp = panel.mpp()

    ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
    ax.plot(v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"MPP ({p_mpp:.3f} W)")

    for (label, make_ctl), color in zip(ALGORITHMS, colors, strict=False):
        v_f, p_f = common.final_point(make_ctl, panel, n_steps=N_STEPS, initial_duty=INITIAL_DUTY)
        eta = p_f / p_mpp if p_mpp else 0.0
        ax.plot(v_f, p_f, "o", color=color, ms=10, zorder=4, label=f"{label}: {p_f:.3f} W")
        print(f"{record.label:<32}{label:<10}{v_f:<9.2f}{p_f:<9.3f}{eta * 100:5.1f} %")

    ax.set_title(record.label, fontsize=10)
    ax.set_xlabel("Voltage [V]")
    ax.set_ylabel("Power [W]")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
```

### The one behavioral trap

Read both blocks above closely: **`compare_static.py` calls `panel_fn()` a
second time inside the algorithm loop** (`final_point(make_ctl,
panel_fn())`) - a *fresh* panel instance per algorithm, distinct from the
`panel` used to draw the curve and compute the MPP. `compare_measured.py`
does the opposite - it reuses the *same* `panel` object (built once, passed
into `_plot_record`) for the curve, the MPP, and every algorithm's
`final_point` call.

This must be preserved exactly, not collapsed into one behavior, because a
shared function that always reuses one `panel` object would silently
change `compare_static.py`'s behavior (removing its per-algorithm fresh
instance), and a shared function that always calls a factory per algorithm
would require `compare_measured.py` to somehow refabricate an identical
`MeasuredPanel` from a `CurveRecord` for every algorithm, which is not
obviously safe or even the point of that script.

**The fix that preserves both**: the shared function takes a
`panel_factory: Callable[[], object]` (matching `AlgorithmSpec.make`'s
existing `Callable`-based style in this same module), calls it once for the
curve/MPP, and calls it again for every algorithm's `final_point`.
`compare_static.py` passes its existing `panel_fn` (a fresh instance each
call, as today). `compare_measured.py` passes `lambda: panel` - the closure
captures the single already-built `MeasuredPanel`, so calling the "factory"
any number of times returns the same object, exactly matching today's
reuse behavior. Do not "simplify" this to a plain `panel` parameter -
that is the trap.

### Other differences between the two call sites (all become parameters)

| | `compare_static.py` | `compare_measured.py` |
|---|---|---|
| MPP star legend text | `"global MPP ({p_mpp:.2f} W)"` | `"MPP ({p_mpp:.3f} W)"` |
| Decimal places (MPP + per-algo labels) | 2 | 3 |
| `eta` when `p_mpp == 0` | not guarded (never zero for a synthetic panel) | guarded: `p_f / p_mpp if p_mpp else 0.0` |
| Legend fontsize | 8 | 7 |
| `ax.set_title(...)` | `ax.set_title(title)` (no fontsize) | `ax.set_title(record.label, fontsize=10)` |

The title call is different enough (positional text differs, one script
passes `fontsize`, the other doesn't) that it stays the caller's
responsibility - do not fold `set_title` into the shared function.

### What the print statements need from the shared function

Both scripts print one table row per algorithm with their own header/column
choices (static's decimals differ from measured's, as above) - so the
shared function must **return** each algorithm's `(label, v_f, p_f, eta)`
plus `p_mpp`, and let each script keep its own `print(...)` call using
those returned values. Do not print from inside the shared function.

## Scope

**In scope**:

- `harness/common.py` - add one new function (Step 1).
- `harness/compare_static.py` - rewrite the per-scenario loop body to call
  it (Step 2).
- `harness/compare_measured.py` - rewrite `_plot_record` to call it
  (Step 3).
- `tests/test_harness_common.py` - add tests for the new function (Step 4).

**Out of scope** (explicitly, per the audit and this session's prior
direction):

- `harness/compare_dynamic.py` and `harness/compare_bank.py` - these plot
  *transient traces* over time, not a single final operating point; they
  do not share this code shape and must not be forced into this function.
- `harness/compare_cyclic.py`, `compare_noise.py`, `compare_rescan.py`,
  `compare_seeds.py`, `animate.py` - none of these draw a static P-V curve
  with final-point markers; out of scope by the same reasoning.
- Any change to `harness/common.py`'s existing `final_point`,
  `algorithm_specs`, `build_conditions`, or `run_schedule` - the new
  function calls `final_point` as-is, it does not modify it.
- Any change to the actual pixel output / PNG content - this is a pure
  refactor, both scripts' saved figures must be pixel-identical before and
  after (verified via Step 5, not by diffing PNG bytes directly since
  matplotlib output is not guaranteed byte-stable - verify via the
  printed table values instead, which fully determine what gets drawn).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Run the new + existing harness-common tests | `uv run pytest tests/test_harness_common.py -v` | all pass |
| Static script still runs end-to-end | `uv run harness/compare_static.py` | exit 0, prints the same table shape, saves `harness/output/compare_static.png` |
| Measured script still runs (needs a saved curve, or exits early) | `uv run mpp-sdk compare-measured` | exit 0 - if no curves are saved, it prints "No curves found..." and exits 0 without error either way, so this command is safe to run regardless |
| Full check (touches 3 non-test files) | `uv run pytest && uv run ruff check . && uv run ruff format --check .` | all clean |

## Git workflow

- Branch: `refactor/harness-plot-dedup`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: add the shared function to `harness/common.py`

Add near `final_point` (after it), reusing this module's existing
`NamedTuple` convention (see `AlgorithmSpec`):

```python
class FinalPointResult(NamedTuple):
    """One algorithm's settled operating point, as returned by
    :func:`plot_pv_with_final_points` for the caller's own table print."""

    label: str
    v: float
    p: float
    eta: float


def plot_pv_with_final_points(
    ax,
    panel_factory: Callable[[], object],
    algorithms: Iterable[tuple[str, Callable[[float], object]]],
    colors,
    *,
    n_steps: int = 2000,
    initial_duty: float = 0.5,
    n_curve_points: int = 400,
    decimals: int = 2,
    mpp_label: str = "global MPP",
    legend_fontsize: int = 8,
) -> tuple[float, list[FinalPointResult]]:
    """Draw one P-V curve with the global MPP starred and every algorithm's
    settled final operating point marked - the shared plot body of
    `compare_static.py` and `compare_measured.py`.

    ``panel_factory`` is called once for the curve/MPP and once per
    algorithm (matching `final_point`'s signature) - **not** memoized here.
    Pass a factory that returns a fresh panel each call (as
    `compare_static.py`'s per-scenario ``panel_fn`` does) or one that
    always returns the same instance (``lambda: panel``, as
    `compare_measured.py` needs for a `MeasuredPanel` built once from a
    `CurveRecord`) depending on which behavior the call site needs - this
    function does not decide that for you.

    Sets everything about the axes except its title (callers' title calls
    differ in text and kwargs) and does not print or save anything -
    returns ``(p_mpp, results)`` so the caller can print its own table.
    """
    panel = panel_factory()
    v_curve, i_curve = panel.iv_curve(n=n_curve_points)
    p_curve = v_curve * i_curve
    v_mpp, _, p_mpp = panel.mpp()

    ax.plot(v_curve, p_curve, "k-", lw=1.5, label="P-V curve", zorder=1)
    ax.plot(
        v_mpp, p_mpp, "k*", ms=14, zorder=3, label=f"{mpp_label} ({p_mpp:.{decimals}f} W)"
    )

    results = []
    for (label, make_ctl), color in zip(algorithms, colors, strict=False):
        v_f, p_f = final_point(
            make_ctl, panel_factory(), n_steps=n_steps, initial_duty=initial_duty
        )
        eta = p_f / p_mpp if p_mpp else 0.0
        ax.plot(
            v_f, p_f, "o", color=color, ms=10, zorder=4, label=f"{label}: {p_f:.{decimals}f} W"
        )
        results.append(FinalPointResult(label, v_f, p_f, eta))

    ax.set_xlabel("Voltage [V]")
    ax.set_ylabel("Power [W]")
    ax.legend(fontsize=legend_fontsize)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    return p_mpp, results
```

Note `eta = p_f / p_mpp if p_mpp else 0.0` is now used unconditionally
(adopting `compare_measured.py`'s guard for both callers) - this is safe
for `compare_static.py` too since its synthetic panels never have
`p_mpp == 0`, and it removes a `ZeroDivisionError` footgun for any future
caller that does have one. This is the one intentional, documented
behavior generalization in this plan; everything else preserves each
script's exact prior behavior.

**Verify**: `uv run python -c "from harness.common import plot_pv_with_final_points, FinalPointResult"`
-> no ImportError (needs pvlib installed locally to import `harness.common`
at all - see "Current state" of plan 028/existing test file conventions;
if pvlib isn't installed, skip straight to running the test file in Step 4
instead, which already handles the skip).

### Step 2: rewrite `compare_static.py` to use it

Replace the loop body (`harness/compare_static.py:50-71`) with:

```python
    for ax, (title, panel_fn) in zip(axes, SCENARIOS, strict=True):
        p_mpp, results = common.plot_pv_with_final_points(
            ax, panel_fn, ALGORITHMS, colors, n_steps=N_STEPS, initial_duty=INITIAL_DUTY
        )
        for label, v_f, p_f, eta in results:
            print(f"{title:<32}{label:<10}{v_f:<9.2f}{p_f:<9.2f}{eta * 100:5.1f} %")
        ax.set_title(title)
```

`panel_fn` is passed directly (not `lambda: panel_fn()`) - it is already a
zero-arg callable (`SCENARIOS`'s second tuple element, e.g.
`series_string`), so this preserves the "fresh panel per call" behavior
exactly as today's `panel_fn()` / `final_point(make_ctl, panel_fn())`
double-call did.

The now-unused local `final_point` wrapper function
(`harness/compare_static.py:37-38`) becomes dead code - remove it, along
with its now-unused nested reference, once nothing in the file calls it
anymore (confirm with `grep -n "final_point" harness/compare_static.py`
after this edit - it should show zero remaining references once removed).

**Verify**: `uv run harness/compare_static.py` -> exit 0, table printed to
stdout with the exact same column layout as before this change (compare
the printed numbers against a run from before this edit if in doubt - they
must match to the printed decimal places, since this is a pure refactor of
already-deterministic computations).

### Step 3: rewrite `compare_measured.py` to use it

Replace `_plot_record` (`harness/compare_measured.py:37-58`) with:

```python
def _plot_record(ax, record, colors) -> None:
    panel = MeasuredPanel(record)
    p_mpp, results = common.plot_pv_with_final_points(
        ax,
        lambda: panel,
        ALGORITHMS,
        colors,
        n_steps=N_STEPS,
        initial_duty=INITIAL_DUTY,
        decimals=3,
        mpp_label="MPP",
        legend_fontsize=7,
    )
    for label, v_f, p_f, eta in results:
        print(f"{record.label:<32}{label:<10}{v_f:<9.2f}{p_f:<9.3f}{eta * 100:5.1f} %")

    ax.set_title(record.label, fontsize=10)
```

`lambda: panel` closes over the single `MeasuredPanel` built at the top of
this function - every call returns that same object, matching today's
reuse behavior exactly (see "The one behavioral trap" above).

**Verify**: `uv run mpp-sdk compare-measured` -> exit 0. If no curves are
saved locally, it prints "No curves found under ... - capture some first."
and exits 0 - that is expected and fine, it still confirms the module
imports and runs without error. If curves *are* available locally, compare
the printed table against a run from before this edit.

### Step 4: add tests for the new function

`harness/common.py` requires `pvlib` to import at all (it imports
`harness.panel_config`, which imports `PvlibPanelModel` at module level) -
follow the exact same `pytest.importorskip("pvlib", ...)` pattern already
used in `tests/test_harness_common.py:12`, even though the new tests below
use a plain `IdealSingleDiode` panel that itself needs no `pvlib`.

Add to `tests/test_harness_common.py` (new section at the end, using
`matplotlib.use("Agg")` the same way every `compare_*` script does):

```python
# ------------------------------------------------------------------
# plot_pv_with_final_points
# ------------------------------------------------------------------


def test_plot_pv_with_final_points_calls_the_factory_once_plus_once_per_algorithm():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from harness.common import plot_pv_with_final_points
    from mpp_sdk.models import IdealSingleDiode

    calls = []

    def panel_factory():
        calls.append(1)
        return IdealSingleDiode()

    specs = algorithm_specs()
    algorithms = [(s.label, s.make) for s in specs]
    colors = ["tab:blue"] * len(algorithms)

    fig, ax = plt.subplots()
    try:
        p_mpp, results = plot_pv_with_final_points(
            ax, panel_factory, algorithms, colors, n_steps=5
        )
    finally:
        plt.close(fig)

    # One call for the curve/MPP, one per algorithm - this is the contract
    # a fresh-panel-per-scenario caller (compare_static.py) relies on.
    assert len(calls) == 1 + len(algorithms)
    assert p_mpp > 0
    assert [r.label for r in results] == [label for label, _ in algorithms]


def test_plot_pv_with_final_points_reuses_a_single_instance_when_the_factory_does():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from harness.common import plot_pv_with_final_points
    from mpp_sdk.models import IdealSingleDiode

    panel = IdealSingleDiode()
    calls = []

    def panel_factory():
        calls.append(panel)
        return panel

    specs = algorithm_specs()
    algorithms = [(s.label, s.make) for s in specs]
    colors = ["tab:blue"] * len(algorithms)

    fig, ax = plt.subplots()
    try:
        plot_pv_with_final_points(ax, panel_factory, algorithms, colors, n_steps=5)
    finally:
        plt.close(fig)

    # Every returned object is the exact same instance - this is the
    # contract compare_measured.py's `lambda: panel` relies on.
    assert all(c is panel for c in calls)
```

Both tests deliberately stop at the factory's call-count/identity contract
(the thing this plan is actually protecting against regressing) rather
than re-deriving `final_point`'s own arithmetic, which
`tests/test_harness_common.py`'s existing `run_schedule`/`final_point`-
adjacent tests already cover indirectly.

**Verify**: `uv run pytest tests/test_harness_common.py -v -k plot_pv_with_final_points`
-> 2 passed.

### Step 5: full verification

```bash
uv run pytest -v --tb=short
uv run ruff check .
uv run ruff format --check .
uv run harness/compare_static.py
uv run mpp-sdk compare-measured
```

All clean; both scripts still produce output (a saved PNG for
`compare_static.py`, either a saved PNG per measurement kind or the
"No curves found" message for `compare-measured`, depending on whether any
curves are saved locally).

## Test plan

Two new unit tests (Step 4) pin the one behavioral contract this
refactor's correctness actually depends on - factory call count/order, and
identity-preservation when the factory always returns the same object. The
two scripts' own end-to-end runs (Step 2/3/5 verification) are the
integration check that nothing about the printed table or saved figure
changed.

## Done criteria

- [ ] `harness/common.py` has `FinalPointResult` and
      `plot_pv_with_final_points`
- [ ] `harness/compare_static.py`'s loop body and dead `final_point`
      wrapper are replaced/removed
- [ ] `harness/compare_measured.py`'s `_plot_record` calls the shared
      function
- [ ] `tests/test_harness_common.py` has the 2 new tests, both passing
- [ ] `uv run pytest -v --tb=short` - full suite green
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] Both scripts run end-to-end without error (Step 5)
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Either script's excerpted code differs from what's quoted above (per the
  drift check) - especially if a future edit changed which of the two uses
  a fresh-vs-shared panel per algorithm; re-derive the `panel_factory`
  design against the new code rather than assuming this plan's "the one
  behavioral trap" analysis still applies verbatim.
- The printed table from either script, run before vs. after this change,
  differs in any number beyond floating-point formatting noise - that
  means the refactor changed behavior, which this plan explicitly must
  not do.

## Maintenance notes

- If a third script ever needs the same "static P-V curve + final-point
  markers" plot (e.g. a future per-panel comparison mode), it should call
  `plot_pv_with_final_points` from the start rather than copy-pasting a
  third version of this block.
- `compare_dynamic.py`/`compare_bank.py`'s transient-trace plotting is a
  structurally different shape (time-series, not a single settled point)
  - do not try to unify it with this function; if those two ever grow
  their own duplication between each other, that would be a separate,
  new plan.
