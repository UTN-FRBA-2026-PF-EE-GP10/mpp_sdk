# Plan 034: Capture and analyze a real closed-loop MPPT run ("runs")

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> This plan has two halves: **Steps 1-6 are pure SDK/script code**,
> verifiable with unit tests and no hardware. **Step 7 needs the real
> board** and cannot be completed by a software-only executor - if you
> reach it without bench access, stop there, report Steps 1-6 done, and
> hand the on-target check to whoever has the board.
>
> **Drift check (run first)**: `git diff --stat b5175f4..HEAD --
> mpp_sdk/io/spi_mcu.py mpp_sdk/curves/ harness/common.py
> scripts/curve_tracer_bench_test.py firmware/pipico_board/src/main.rs`. If
> any of these changed since this plan was written, re-read the changed
> file(s) in full before proceeding; on a mismatch with the excerpts below
> (especially `FIRMWARE_MODE`, `SpiMcuSource`'s method signatures, or
> `CurveRecord`'s schema), treat it as a STOP condition.

## Status

- **Priority**: P2 - this is Phase 5a's actual payoff (AGENTS.md: "A
  Pi-side `SpiMcuSource(SignalSource)`... the algorithm still lives on the
  Pi"): running a real registered algorithm against real hardware and
  capturing what it does, closing the sim-to-real loop `docs/methodology.md`
  already describes at layer 3 ("Closed loop... run the test-case bank in
  each environment and compare the metrics tables") but has never actually
  exercised on real hardware.
- **Effort**: L - a new SDK subpackage, a new hardware capture script, a
  new analysis/plotting script, CLI wiring, and tests; no firmware changes
  needed (see "Why no firmware change is needed").
- **Risk**: MED - **this is the first time in the project an algorithm
  will drive the live SEPIC continuously** against a real panel and real
  load, not just probe it like the curve tracer's separate bleed path. The
  design below includes a client-side safety abort specifically because of
  this - see "Safety: no on-target cutoff exists for this today".
- **Depends on**: none (does not depend on any of plans 025-033).
- **Category**: feature (from an operator request, not the September
  audit - see "Why this matters").
- **Planned at**: commit `b5175f4`, 2026-09-08.

## Why this matters

Everything the SDK does with the five registered algorithms
(`mpp_sdk.algorithms`) today is either pure simulation (`SimulatedSource`,
the whole `harness/compare_*.py` family) or replay of a **static** captured
curve (`MeasuredPanel`, `mpp-sdk compare-measured`) - both grade an
algorithm against a model, never against a live plant. `SpiMcuSource`
(`mpp_sdk/io/spi_mcu.py`) already implements the exact same `SignalSource`
interface (`read()`/`write()`) that every algorithm is built against, and
per AGENTS.md this substitution is supposed to need **zero algorithm
code changes** - but nothing in the repo actually exercises that path
today. `git grep -n "SpiMcuSource("` across the whole tree (excluding
tests) only turns up `scripts/curve_tracer_server.py` (the curve tracer,
a different subsystem entirely) and `scripts/curve_tracer_bench_test.py`
(fetches curves, never calls `.step()` on an algorithm). **No script has
ever run a real `MPPTAlgorithm` against real `(V, I)` in a loop and
recorded what happened.**

The operator's ask (paraphrased from the request that produced this plan):
capture a static I-V curve as ground truth (already fully supported - see
`mpp_sdk.curves`), then run one algorithm against the live panel/converter
for a while, streaming `(t, V, I, D)` back from the Pico exactly the way
the curve tracer already streams sweep points, save both the curve and the
run together, and later replay them with a script that plots the real P-V
curve (with its true MPP) alongside the dynamic `(V, I)` trajectory the
algorithm actually traced - i.e. **did it find the MPP, how fast, and how
well did it hold it**. Explicitly scoped to one static scenario for now
(no shading changes mid-run) - a dynamic-conditions version is a natural
follow-up once this lands, not part of this plan.

## Why no firmware change is needed

`firmware/pipico_board/src/main.rs` already has exactly the mode this
needs, already the active one:

```rust
enum FirmwareMode {
    MppTracker,
    PowerSupply,
}

/// Change to `FirmwareMode::PowerSupply` for bench supply operation.
const FIRMWARE_MODE: FirmwareMode = FirmwareMode::MppTracker;
```

and in the main control loop:

```rust
FirmwareMode::MppTracker => DUTY.load(Ordering::Relaxed).min(DUTY_MAX),
```

`FirmwareMode::MppTracker` is a dumb passthrough: it applies whatever duty
the Pi last wrote over SPI (clamped to `DUTY_MAX`, 95%). The algorithm
itself has never lived on the firmware side and does not need to - it
already lives on the Pi, exactly per AGENTS.md's design. **Confirm on the
bench that the flashed firmware is actually built with this
`FIRMWARE_MODE` before Step 7** (re-read `main.rs` per the drift check; if
it has been changed to `PowerSupply`, this plan's whole premise needs the
firmware reflashed first - that is itself a STOP condition, not something
to route around).

`SpiMcuSource`'s existing contract (`mpp_sdk/io/spi_mcu.py`) is exactly
what a control loop needs:

```python
def read(self) -> tuple[float, float]:
    """Return the (V, I) received in the last write() transaction."""
    if not self._has_read:
        raise RuntimeError("SpiMcuSource.read() called before the first write()")
    return self._v, self._i

def write(self, duty_cycle: float) -> None:
    """Send *duty_cycle* to the Pico and capture the returned telemetry."""
    self._duty = max(0.0, min(1.0, duty_cycle))
    self._send_cmd()
```

Each `write()` call performs one full SPI transaction and updates the
cached `(V, I)` immediately - `read()` never blocks or polls, it returns
whatever the last `write()` captured. This means **the very first `read()`
raises unless `write()` was already called once** (confirmed in "Current
state" above and covered by an existing test,
`test_read_before_write_raises` in `tests/test_spi_mcu.py`) - the control
loop below seeds this with one `write(initial_duty)` before its first
`read()`, exactly the same shape as any `SimulatedSource`-driven harness
loop but with that one extra seed call `SpiMcuSource` specifically
requires.

## Safety: no on-target cutoff exists for this today

The curve tracer has its own dedicated safety cutoff
(`CurveTracer::breach`, `firmware/pipico_board/src/mode_curve_tracer.rs`,
subject of plan 026) because driving current through the bleed path
without one is dangerous. **`FirmwareMode::MppTracker` has no analogous
on-target protection** beyond `DUTY_MAX`'s 95% ceiling - it will apply
whatever duty the Pi sends, unconditionally, for as long as the Pi keeps
sending it. `scripts/spi_test.py` already treats this as worth flagging
inline (`ok = "✓" if (0 <= v_raw <= 40_000 and 0 <= i_raw <= 1_000) else
"✗"`, citing "Board is designed for <= 40 V / <= 1 A" from
`docs/general_information.md`) but only for a printed indicator, never an
abort.

This plan is the first script that drives the SEPIC **continuously** with
a live algorithm rather than a fixed test duty or a bounded curve-tracer
sweep, so it adds a client-side (Python) safety abort using the same
board limits `spi_test.py` already cites: if a `read()` ever reports
`voltage > 40.0` or `current > 1.0`, the loop calls
`source.write(0.0)` (drive duty to zero - `SpiMcuSource.soft_stop()` does
exactly this) and stops immediately, marking the saved run as aborted
rather than completed. This is a **software safety net on top of**
existing hardware protection, not a replacement for it - same
defense-in-depth spirit as `TRACER_I_MAX_MA`/`TRACER_P_MAX_MW`, just
implemented Pi-side since `MppTracker` mode has no on-target equivalent.

## Design

### New subpackage: `mpp_sdk/runs/`

Mirrors `mpp_sdk/curves/` deliberately - same shape, same conventions,
same test style - because `mpp_sdk/curves/` is exactly the right template
for "capture something physical, persist it as JSON with metadata, load it
back later for analysis."

`mpp_sdk/runs/record.py`:

```python
"""One closed-loop MPPT run: a time series of (V, I, D) captured while an
algorithm drove real hardware (or, in principle, a simulated source), plus
the metadata needed to know what it is and, optionally, which captured
I-V curve it should be graded against.

Plain stdlib only (no numpy) - mirrors mpp_sdk/curves/record.py's own
reasoning: this module must stay importable anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..curves.record import now_utc  # re-exported below, not duplicated

_SCHEMA = 1


@dataclass(frozen=True)
class RunSample:
    """One control-loop step. `t` is seconds since the run started
    (wall-clock, from whatever `clock` the loop was given - not assumed to
    be evenly spaced, since real SPI round-trip time varies)."""

    t: float
    voltage: float
    current: float
    duty: float

    def to_dict(self) -> dict:
        return {"t": self.t, "v": self.voltage, "i": self.current, "d": self.duty}

    @classmethod
    def from_dict(cls, d: dict) -> RunSample:
        return cls(t=d["t"], voltage=d["v"], current=d["i"], duty=d["d"])


@dataclass(frozen=True)
class RunRecord:
    """One captured closed-loop run plus the metadata needed to grade it."""

    captured_at: datetime
    label: str
    algorithm: str  # free text, e.g. "P&O" - matches harness/common.py's AlgorithmSpec.label
    samples: tuple[RunSample, ...]
    curve_ref: str | None = None  # filename under mpp_sdk.curves.library.default_dir(), or None
    aborted: bool = False  # True if the safety abort fired before completion
    notes: str = field(default="")

    def to_dict(self) -> dict:
        return {
            "schema": _SCHEMA,
            "captured_at": self.captured_at.isoformat(),
            "label": self.label,
            "algorithm": self.algorithm,
            "curve_ref": self.curve_ref,
            "aborted": self.aborted,
            "notes": self.notes,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RunRecord:
        schema = d.get("schema")
        if schema != _SCHEMA:
            raise ValueError(f"unsupported run record schema {schema!r}, expected {_SCHEMA}")
        try:
            return cls(
                captured_at=datetime.fromisoformat(d["captured_at"]),
                label=d["label"],
                algorithm=d["algorithm"],
                samples=tuple(RunSample.from_dict(s) for s in d["samples"]),
                curve_ref=d.get("curve_ref"),
                aborted=d.get("aborted", False),
                notes=d.get("notes", ""),
            )
        except KeyError as exc:
            raise ValueError(f"run record missing field {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"run record has an invalid field: {exc}") from exc


__all__ = ["RunRecord", "RunSample", "now_utc"]
```

`mpp_sdk/runs/library.py` - a near-verbatim copy of
`mpp_sdk/curves/library.py`'s `default_dir`/`_slug`/`save`/`load`/
`load_all` shape, retargeted at `RunRecord` and `data/runs/`:

```python
"""Read/write `RunRecord`s to `data/runs/` (or wherever `MPP_SDK_RUN_DIR`
points), one JSON file per run."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .record import RunRecord

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SLUG_MAX_LEN = 40


def default_dir() -> Path:
    """`data/runs/` under the repo root, overridable via `MPP_SDK_RUN_DIR`
    (tests use this to avoid touching the real directory)."""
    override = os.environ.get("MPP_SDK_RUN_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "runs"


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug[:_SLUG_MAX_LEN].rstrip("-") or "run"


def save(record: RunRecord, directory: Path | None = None) -> Path:
    """Write `record` as `{captured_at}-{slug(label)}.json`. Same
    collision handling as `mpp_sdk.curves.library.save` - exclusive
    creation, `-2`/`-3`/... suffix on collision, never overwrites."""
    directory = directory if directory is not None else default_dir()
    directory.mkdir(parents=True, exist_ok=True)

    stem = f"{record.captured_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(record.label)}"
    body = json.dumps(record.to_dict(), indent=2) + "\n"
    suffix = 0
    while True:
        name = f"{stem}.json" if suffix == 0 else f"{stem}-{suffix + 1}.json"
        path = directory / name
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(body)
        except FileExistsError:
            suffix += 1
            continue
        return path


def load(path: Path) -> RunRecord:
    """Parse one run record file - same error-reporting philosophy as
    `mpp_sdk.curves.library.load` (named file + field, since these are
    hand-editable JSON, not just internal state)."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return RunRecord.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def load_all(directory: Path | None = None) -> list[RunRecord]:
    directory = directory if directory is not None else default_dir()
    if not directory.exists():
        return []
    return [load(path) for path in sorted(directory.glob("*.json"))]
```

`mpp_sdk/runs/__init__.py`:

```python
"""On-disk library of captured closed-loop MPPT runs.

from mpp_sdk.runs import RunRecord, RunSample
from mpp_sdk.runs import save, load, load_all
"""

from .library import default_dir, load, load_all, save
from .record import RunRecord, RunSample

__all__ = ["RunRecord", "RunSample", "default_dir", "save", "load", "load_all"]
```

### `curve_ref`: how a run points at its ground-truth curve

`RunRecord.curve_ref` stores just the **filename** `mpp_sdk.curves.library
.save()` returned (e.g. `"20260908T120000Z-baseline.json"`), not a full
path - this keeps it portable across `MPP_SDK_CURVE_DIR` overrides (tests,
a different machine). A consumer resolves it as
`mpp_sdk.curves.library.default_dir() / record.curve_ref`. `None` means
"no paired curve" (e.g. `--no-sweep`, see Step 4).

### `scripts/run_algorithm.py`: the hardware capture script

Needs `mpp-sdk[hardware]` (spidev) - same extra `scripts/spi_test.py` and
`scripts/curve_tracer_bench_test.py` already need. Two clearly separated
pieces, so the control loop is unit-testable without hardware:

1. **Sweep + save the curve** (hardware-specific: `start_sweep()`/
   `request_sweep()`/`release_relay()`) - reuses
   `scripts.curve_tracer_bench_test.run_sweep_and_fetch` rather than
   duplicating that handshake, then calls `mpp_sdk.curves.library.save()`.
   Skippable with `--no-sweep --curve <path>` to reuse an existing capture
   (e.g. while iterating on the algorithm-loop code without re-sweeping
   every time).
2. **`run_control_loop(source, algorithm, *, duration_s, v_max, i_max,
   clock, sleep) -> list[RunSample]`** - a pure function, hardware-agnostic
   (anything with `.read()`/`.write()`, i.e. any `SignalSource`), with
   injectable `clock`/`sleep` (mirrors `DemoSweepSource`'s injectable
   `clock` from the `--demo` work) so it is fully deterministic under test
   with no real waiting and no real hardware:

   ```python
   def run_control_loop(
       source,
       algorithm,
       *,
       duration_s: float,
       v_max: float,
       i_max: float,
       initial_duty: float = 0.5,
       clock=time.monotonic,
       sleep=time.sleep,
       period_s: float = 0.0,
   ) -> tuple[list[RunSample], bool]:
       """Run `algorithm` against `source` for `duration_s` seconds,
       recording one `RunSample` per control step. Returns
       `(samples, aborted)` - `aborted` is True if `voltage > v_max` or
       `current > i_max` fired the safety cutoff (source is driven to 0
       duty before returning). `period_s > 0` adds a `sleep()` pad between
       steps; 0 (default) runs as fast as `source.read()/write()` allow."""
       source.write(initial_duty)  # seed - SpiMcuSource.read() raises before the first write()
       samples: list[RunSample] = []
       start = clock()
       aborted = False
       while clock() - start < duration_s:
           voltage, current = source.read()
           t = clock() - start
           if voltage > v_max or current > i_max:
               source.write(0.0)
               aborted = True
               break
           duty = algorithm.step(voltage, current)
           source.write(duty)
           samples.append(RunSample(t=t, voltage=voltage, current=current, duty=duty))
           if period_s > 0:
               sleep(period_s)
       return samples, aborted
   ```

   Note the sample recorded each iteration pairs the **measurement that
   was just read** with the **duty computed from it** (not the duty that
   produced that measurement) - this matches every harness script's
   existing convention (`harness/common.py`'s `final_point`:
   `v, i = src.read(); src.write(ctl.step(v, i))`, same
   read-then-respond-then-actuate order), so a `RunRecord`'s samples are
   directly comparable to any simulated `(V, I, D)` trace the harness
   already produces (`compare_bank.py`'s CSV dump, see
   `docs/methodology.md`).

`main()` wires argparse around both pieces: `--algorithm` (matching one of
`harness.common.algorithm_specs()`'s labels, case-insensitive - reuse that
roster rather than re-declaring the five algorithms a third time),
`--duration-s` (default `10.0`), `--label`, `--v-max`/`--i-max` (defaults
`40.0`/`1.0`, the board's documented limits per
`docs/general_information.md` and `scripts/spi_test.py`'s existing inline
check), `--no-sweep`/`--curve <path>`, `--bus`/`--device`/`--speed-hz`
(same defaults as `curve_tracer_bench_test.py`). On completion, builds a
`RunRecord` (`aborted` from the loop's return, `curve_ref` set to the
saved curve's filename or `None`) and saves it via `mpp_sdk.runs.save()`.
Prints a short summary table (steps captured, final `(V, I, D)`, whether
aborted) - matches the printed-table convention every other harness/
scripts entry point already follows.

### `scripts/plot_run.py`: the analysis script

No hardware - pure plotting from saved files, same shape as
`harness/compare_measured.py`. Loads one `RunRecord` (path or most-recent-
in-`data/runs/` if omitted), and if `curve_ref` is set, loads the paired
`CurveRecord` and wraps it in `MeasuredPanel` (`mpp_sdk.models.measured`)
to get the smooth P-V curve and its (possibly extrapolated) MPP - exactly
the object `mpp-sdk compare-measured` already builds from a saved curve,
reused here rather than re-implemented.

Produces one figure, two subplots:

1. **P-V curve with the run's trajectory overlaid**: the curve as a
   `k-` line (same style as `compare_static.py`/`compare_measured.py`),
   the MPP starred, and the run's `(V, P=V*I)` points plotted as a
   scatter colored by `t` (a sequential colormap, e.g. `viridis`, via
   `ax.scatter(v, p, c=t, cmap="viridis")` with a colorbar labeled "time
   (s)") - this is the "did it find the peak, and how" picture.
2. **Time series**: `V(t)`, `I(t)`, `P(t)` on shared/twin axes, with a
   horizontal reference line at the curve's `p_mpp` (if a curve is paired)
   - this is the "how fast, how well did it hold it" picture, the same
   shape `compare_dynamic.py`/`compare_bank.py` already draw for
   *simulated* traces, now drawn from a *measured* one.

If no curve is paired (`curve_ref is None`), subplot 1 is skipped (no MPP
to compare against) and a note is printed - do not fabricate a curve or
skip the whole script.

### CLI wiring

`harness/cli.py`'s `_COMMANDS` dict gains two entries, both argv-forwarding
(they use argparse with no explicit `args=`, same as `spi-test`/
`curve-tracer-web`):

```python
"run-algorithm": ("scripts.run_algorithm", True),
"plot-run": ("scripts.plot_run", True),
```

### `data/runs/` and docs

`.gitignore` gains `data/runs/` (same pattern as `data/curves/` - measured
data, not repo content). `data/README.md` gains a `data/runs/` bullet
mirroring its existing `data/curves/` one. `README.md`'s "Curve-tracer web
workbench" Quickstart area is not the right place for this (it is a
different workflow, not the web UI) - add a short new "Closed-loop runs"
paragraph near it instead, one-lining `run-algorithm`/`plot-run`.

## Scope

**In scope**:

- `mpp_sdk/runs/` (new: `__init__.py`, `record.py`, `library.py`).
- `scripts/run_algorithm.py` (new).
- `scripts/plot_run.py` (new).
- `harness/cli.py` - two new `_COMMANDS` entries.
- `.gitignore`, `data/README.md`, `README.md` - the small additions above.
- `tests/test_run_library.py` (new, mirrors `tests/test_curve_library.py`).
- `tests/test_run_algorithm.py` (new - tests `run_control_loop` only, no
  hardware, no argparse/`main()` invocation).

**Out of scope**:

- Any firmware change - `FirmwareMode::MppTracker` already does what this
  needs (see "Why no firmware change is needed"). If bench testing in
  Step 7 reveals it does not, that is a STOP condition, not a green light
  to start editing `main.rs` under this plan.
- Dynamic/changing conditions during a run (shading changes, dimmer
  sweeps mid-run) - explicitly a static-scenario MVP per the operator's
  own framing ("for now just measuring a dynamic scenario with a static
  curve"). A follow-up plan can add a controlled condition change mid-run
  once this lands.
- Computing `mpp_sdk.metrics` numbers (`tracking_efficiency`,
  `settling_time`, etc.) from a saved run. Those functions assume evenly-
  spaced samples (`dt` is a single scalar); a real run's samples are
  **not** evenly spaced (`RunSample.t` varies with actual SPI round-trip
  time per step), so feeding them in requires resampling onto a uniform
  grid first - a real piece of work, and not what was asked for ("for now
  just... plot"). Leave it for a follow-up once someone actually has runs
  captured to resample and wants the numbers.
- Any change to `SpiMcuSource`, `mpp_sdk.curves`, or
  `harness/common.py` - all reused as-is.
- A web-UI equivalent of this (a "Runs" tab in `frontend/`) - out of scope
  until this CLI-first version is validated on the bench; do not start
  frontend work under this plan.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Runs-library tests | `uv run pytest tests/test_run_library.py -v` | all pass |
| Control-loop tests (no hardware) | `uv run pytest tests/test_run_algorithm.py -v` | all pass |
| Full suite | `uv run pytest -v --tb=short` | all pass |
| Routine checks | `uv run ruff check . && uv run ruff format --check .` | clean |
| CLI wiring sanity (no hardware, `--help` only) | `uv run mpp-sdk run-algorithm --help` / `uv run mpp-sdk plot-run --help` | exit 0, prints usage |
| **Bench only** (Step 7) | `uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check` then `uv run mpp-sdk plot-run` | a `RunRecord` and paired `CurveRecord` saved; a figure showing a real trajectory |

## Git workflow

- Branch: `feat/hardware-mppt-runs`.
- Suggested commit split: one for `mpp_sdk/runs/` + its tests, one for the
  two scripts + CLI wiring + docs (operator's call - a single commit
  covering everything is also fine, matching this session's usual
  one-PR-per-unit-of-work pattern).
- Push and open a PR only after operator confirmation. **Do not merge or
  consider this plan DONE until Step 7's on-target check has actually run**
  - mark the plan `IN PROGRESS` (code complete, on-target pending) if the
  PR lands before bench access, matching how plans 016/018/019/020 were
  tracked in this same index.

## Steps

### Step 1: `mpp_sdk/runs/record.py`

Write the file exactly as specified in "Design" above.

**Verify**: `uv run python -c "from mpp_sdk.runs.record import RunRecord, RunSample; print(RunRecord, RunSample)"`
-> no ImportError.

### Step 2: `mpp_sdk/runs/library.py` and `__init__.py`

Write both files exactly as specified in "Design" above.

**Verify**: `uv run python -c "from mpp_sdk.runs import RunRecord, RunSample, save, load, load_all, default_dir"`
-> no ImportError.

### Step 3: `tests/test_run_library.py`

Mirror `tests/test_curve_library.py` structurally (read it first - it is
the exact template): a `_record(**overrides)` builder, round-trip
save/load, filename-from-`captured_at`+slug, collision-suffix behavior,
`load_all`/missing-directory, and parse-error cases (`schema` mismatch,
missing field). Use `RunSample`s with a couple of `t`/`v`/`i`/`d` values
instead of `CurveRecord`'s `(v, i)` points. Every test uses `tmp_path` -
never touch the real `data/runs/`.

**Verify**: `uv run pytest tests/test_run_library.py -v` -> all pass.

### Step 4: `scripts/run_algorithm.py`

Write `run_control_loop` exactly as specified in "Design" above (this is
the function Step 6's tests exercise directly - keep its signature
matching, including the `clock`/`sleep`/`period_s` injection points).

Then the sweep-and-save half and `main()`:

```python
def _sweep_and_save_curve(src, *, timeout_s: float, poll_interval_s: float, label: str) -> str:
    """Trigger one sweep, save it via mpp_sdk.curves, release the relay,
    and return the saved file's name (for RunRecord.curve_ref)."""
    from scripts.curve_tracer_bench_test import run_sweep_and_fetch

    points = run_sweep_and_fetch(src, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
    record = CurveRecord(
        captured_at=curves_now_utc(),
        label=label,
        measurement="baseline",
        panels=(),
        points=tuple(points),
    )
    path = curves_save(record)
    src.release_relay()
    return path.name
```

(`CurveRecord`, `curves_now_utc` (aliased from `mpp_sdk.curves.record
.now_utc`), and `curves_save` (aliased from `mpp_sdk.curves.library.save`)

- import at the top of the file; naming them distinctly from this file's
own `RunRecord`/`save` avoids a collision.)

`main()`: argparse per "Design"'s CLI section, builds the algorithm via
`harness.common.algorithm_specs()` (`{s.label.lower(): s.make for s in
algorithm_specs()}`, matched case-insensitively against `--algorithm`),
opens `SpiMcuSource` as a context manager, does the optional sweep, runs
`run_control_loop`, builds and saves a `RunRecord`, prints a summary.
Guard the `--algorithm` lookup with a clear `argparse.ArgumentTypeError`
or manual `parser.error(...)` listing valid choices on a miss - do not let
an unrecognized algorithm name raise a bare `KeyError`.

**Verify**: `uv run mpp-sdk run-algorithm --help` -> exit 0, lists all the
flags above. (No hardware call happens on `--help`.)

### Step 5: `scripts/plot_run.py`

Per "Design"'s analysis-script section. `main()`: argparse with an
optional positional `run_path` (default: most recent file in
`mpp_sdk.runs.default_dir()`, sorted by name - same convention curves'
`load_all` already uses, since filenames are zero-padded-timestamp-
prefixed and sort chronologically). Loads the run, loads+wraps the paired
curve if `curve_ref` is set, draws the two-subplot figure per "Design",
saves to `harness/output/plot_run_<slug>.png` (create the directory if
needed, matching `compare_measured.py`'s `out_dir.mkdir(exist_ok=True)`).

**Verify**: `uv run mpp-sdk plot-run --help` -> exit 0.

### Step 6: `tests/test_run_algorithm.py`

Tests `run_control_loop` only - not `main()`, not the sweep/save half (both
need real hardware). A minimal in-test fake source, no `spidev` faking
needed (this function only calls `.read()`/`.write()`, nothing curve-
tracer-specific):

```python
class _FakeSource:
    """Minimal SignalSource fake: read() returns whatever write() last
    received, run through a trivial linear plant (V drops as duty rises) -
    just enough for run_control_loop's own logic to be exercised, not a
    physically accurate model."""

    def __init__(self):
        self._duty = 0.0

    def write(self, duty):
        self._duty = duty

    def read(self):
        v = 20.0 * (1.0 - self._duty)
        i = 0.2 * self._duty
        return v, i


class _FixedDutyAlgorithm:
    def __init__(self, duty):
        self._duty = duty

    def step(self, voltage, current):
        return self._duty


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_seeds_with_initial_duty_before_first_read():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.3),
        duration_s=0.0,
        v_max=100.0,
        i_max=100.0,
        initial_duty=0.5,
        clock=clock,
        sleep=lambda _: None,
    )
    # duration_s=0.0 means the while-condition is false immediately, but
    # the seed write() must still have happened - confirmed indirectly via
    # the fake source's internal state.
    assert source._duty == 0.5
    assert samples == []
    assert aborted is False


def test_records_one_sample_per_step():
    source = _FakeSource()
    clock = _FakeClock()

    def sleep(dt):
        clock.advance(dt)

    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.25),
        duration_s=0.3,
        v_max=100.0,
        i_max=100.0,
        clock=clock,
        sleep=sleep,
        period_s=0.1,
    )
    assert len(samples) == 3  # t=0, 0.1, 0.2 - loop exits once clock - start >= 0.3
    assert aborted is False
    assert all(s.duty == 0.25 for s in samples)


def test_safety_abort_on_overvoltage_stops_and_zeroes_duty():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.5),
        duration_s=10.0,
        v_max=1.0,  # source's V at duty=0.5 (seed) is 10.0 - immediately over
        i_max=100.0,
        initial_duty=0.5,
        clock=clock,
        sleep=lambda _: None,
    )
    assert aborted is True
    assert samples == []
    assert source._duty == 0.0  # driven to zero, not left at the offending duty


def test_safety_abort_on_overcurrent():
    source = _FakeSource()
    clock = _FakeClock()
    samples, aborted = run_control_loop(
        source,
        _FixedDutyAlgorithm(0.9),
        duration_s=10.0,
        v_max=100.0,
        i_max=0.05,  # source's I at duty=0.9 (seed) is 0.18 - over
        initial_duty=0.9,
        clock=clock,
        sleep=lambda _: None,
    )
    assert aborted is True
    assert source._duty == 0.0
```

Adjust the exact numbers above if `run_control_loop`'s actual read-check-
step-write ordering (Step 4) differs even slightly from the version in
"Design" - re-derive expected sample counts/values from your own
implementation rather than forcing these if they drift, but the four
behaviors under test (seed-before-first-read, one-sample-per-step,
abort-on-overvoltage, abort-on-overcurrent) must all still be covered.

**Verify**: `uv run pytest tests/test_run_algorithm.py -v` -> all 4 pass.

### Step 7: on-target verification (needs the board)

**Do not attempt this without physical bench access.** If you have it:

1. Confirm `firmware/pipico_board/src/main.rs`'s `FIRMWARE_MODE` is
   `MppTracker` on the currently-flashed build (re-read the file; reflash
   if it drifted - that is bench work outside this plan's scope to
   automate).
2. `uv run mpp-sdk run-algorithm --algorithm "P&O" --duration-s 10 --label bench-check`.
   Confirm: a curve gets swept and saved (check `data/curves/`), the relay
   audibly releases, the run completes (or safety-aborts - either is a
   valid finding to report), and a `RunRecord` is saved under `data/runs/`.
3. `uv run mpp-sdk plot-run` - confirm the figure shows a plausible P-V
   curve with a trajectory that starts somewhere and (hopefully) heads
   toward the starred MPP, plus a sensible time series.
4. Watch the panel/converter for anything alarming (audible whine change,
   heat, the safety abort firing unexpectedly) - this is a genuinely new
   thing to run on this hardware; treat any surprise as worth reporting
   in detail, not just noting pass/fail.

Report the actual numbers observed (steps captured, aborted or not, rough
convergence time) in the PR - this becomes the "011 is DONE"-style closing
note for this plan in the README's status table, not just a checkbox.

## Test plan

- `tests/test_run_library.py`: round-trip, collision handling, parse
  errors, `load_all` - mirrors `tests/test_curve_library.py` exactly.
- `tests/test_run_algorithm.py`: `run_control_loop`'s four behaviors
  (seed-before-read, per-step sampling, both safety-abort paths) against a
  trivial fake source - no hardware, no `spidev` faking needed since this
  function only needs `.read()`/`.write()`.
- No test for `scripts/plot_run.py`'s plotting itself (matplotlib output,
  not meaningfully unit-testable) - Step 7's visual check is the
  verification for that half.

## Done criteria

- [ ] `mpp_sdk/runs/` exists (`record.py`, `library.py`, `__init__.py`)
- [ ] `scripts/run_algorithm.py` and `scripts/plot_run.py` exist
- [ ] `harness/cli.py` has both new `_COMMANDS` entries
- [ ] `.gitignore`/`data/README.md`/`README.md` updated per "Design"
- [ ] `tests/test_run_library.py` and `tests/test_run_algorithm.py` exist,
      all tests passing
- [ ] `uv run pytest -v --tb=short` - full suite green
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] `uv run mpp-sdk run-algorithm --help` / `plot-run --help` both exit 0
- [ ] Step 7 completed on the bench, with actual observations recorded (or
      explicitly marked pending if no bench access - do not mark this
      plan fully DONE without it)
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `FIRMWARE_MODE` is not `MppTracker` on the flashed firmware at Step 7 -
  do not reflash or change firmware under this plan without operator
  sign-off; report the mismatch instead.
- `SpiMcuSource`'s `read()`/`write()` contract (raises before first
  `write()`, `write()` performs the full transact) has changed since this
  plan was written (per the drift check) - re-derive `run_control_loop`'s
  seeding behavior against the new contract.
- The safety abort fires during Step 7's bench run - **this is not a bug
  to silently work around**. Stop, note the exact `(V, I)` reading that
  tripped it, and report whether it looks like a real over-limit condition
  (algorithm genuinely drove duty somewhere bad) or a false trip (e.g. a
  glitched reading) before considering re-running.
- Any existing test (`tests/test_curve_library.py`, `tests/test_spi_mcu.py`,
  `tests/test_curve_tracer_server.py`, `tests/test_harness_common.py`)
  starts failing after this plan's changes - nothing in this plan should
  touch code any of those exercise; a failure means an unintended
  interaction, not something to paper over.

## Maintenance notes

- This plan deliberately does not touch `mpp_sdk.metrics` - once a few
  real runs exist, resampling `RunSample.t`-indexed data onto a uniform
  grid (e.g. `numpy.interp`) and feeding it through
  `mpp_sdk.metrics.summarize()` is the natural next plan, and would let a
  real run report a real `tracking_efficiency`/`settling_time` number
  instead of just a picture.
- A dynamic-conditions version (a controlled shading/dimmer change
  partway through a run, once plan 024's dimmer spike lands) is the
  natural sequel - `run_control_loop`'s shape (a plain loop over
  `read()`/`step()`/`write()`) does not need to change for that, only the
  physical setup and what gets recorded in `notes` would.
- If a "Runs" web-UI tab is ever wanted (mirroring `frontend/`'s curve
  workbench), `mpp_sdk.runs`'s save/load API is already the right seam for
  a FastAPI route to sit behind, same as `mpp_sdk.curves` is for
  `scripts/curve_tracer_server.py` today - do not redesign the storage
  layer for that when it comes, reuse it.
