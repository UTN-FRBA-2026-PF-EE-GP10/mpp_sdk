# Plan 031: Formalize `SpiMcuSource`/`DemoSweepSource`'s duck-typed interface as a `Protocol`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> mpp_sdk/io/ scripts/curve_tracer_server.py
> scripts/curve_tracer_demo_source.py`. If any of these changed since this
> plan was written, re-read the changed file(s) in full before proceeding;
> on a mismatch between the method signatures quoted below and the live
> code, treat it as a STOP condition - the whole point of this plan is
> making the interface *exact*, so working from stale signatures defeats it.

## Status

- **Priority**: P3
- **Effort**: S-M
- **Risk**: LOW - additive only; no existing class needs to change its
  base classes or behavior (`typing.Protocol` is structural - conformance
  needs no inheritance declaration)
- **Depends on**: none
- **Category**: tech debt
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`SpiMcuSource` (`mpp_sdk/io/spi_mcu.py`) and `DemoSweepSource`
(`scripts/curve_tracer_demo_source.py`) share no base class, no ABC, and no
common module - but `scripts/curve_tracer_server.py`'s `_poll_loop`
function treats them completely interchangeably, calling exactly four
methods (`start_sweep`, `release_relay`, `request_sweep`,
`poll_sweep_progress`) plus the context-manager protocol on whichever one
it was handed. `DemoSweepSource`'s own module docstring already says this
out loud: "Implements exactly the four methods `_poll_loop` calls on a
source... duck-typed against `SpiMcuSource`, not a subclass." That sentence
is correct today, but no shared type names the contract. The Protocol and
annotation added here make it visible to editors and any future static
type-check gate; the runtime tests catch removed or renamed members.
Runtime Protocol checks do not validate parameter or return annotations,
so this plan does not claim to catch those forms of drift until the repo
adopts a static checker. Found via the `improve` skill's
September 2026 audit (finding DEBT-03).

## Current state

`_poll_loop`'s complete interaction with `src`
(`scripts/curve_tracer_server.py`, inside `_poll_loop`, both branches
converge on `with source_cm as src:` then a `while True:` loop calling
`src.start_sweep()`, `src.release_relay()`, `src.request_sweep()`,
`src.poll_sweep_progress()` - see that function in full if you want the
surrounding control flow; not re-quoted here since this plan does not
change it).

The two implementations' relevant signatures, confirmed by reading both
files directly:

`mpp_sdk/io/spi_mcu.py`:

```python
class SpiMcuSource(SignalSource):
    def request_sweep(
        self, poll_attempts: int = 20, poll_interval_s: float = 0.05
    ) -> list[tuple[float, float]] | None: ...
    def poll_sweep_progress(self) -> SweepProgress | None: ...
    def start_sweep(self) -> None: ...
    def release_relay(self) -> None: ...
    def __enter__(self) -> SpiMcuSource: ...
    def __exit__(self, *_: object) -> None: ...
```

`scripts/curve_tracer_demo_source.py`:

```python
class DemoSweepSource:
    def __enter__(self) -> DemoSweepSource: ...
    def __exit__(self, *_: object) -> None: ...
    def start_sweep(self) -> None: ...
    def release_relay(self) -> None: ...
    def request_sweep(self) -> list[tuple[float, float]] | None: ...
    def poll_sweep_progress(self) -> _DemoProgress | None: ...
```

`request_sweep`'s extra, defaulted `poll_attempts`/`poll_interval_s`
parameters on `SpiMcuSource` are never passed by `_poll_loop` (it always
calls `src.request_sweep()` with no arguments) - the Protocol below
reflects the interface *`_poll_loop` actually uses*, not `SpiMcuSource`'s
full public surface, matching how this interface is genuinely consumed.

`SweepProgress` (`mpp_sdk/io/spi_mcu.py`) and `_DemoProgress`
(`scripts/curve_tracer_demo_source.py`) are two independently-defined
dataclasses with the same five fields (`index: int`, `voltage: float`,
`current: float`, `active: bool`, `final_point: bool`) -
`curve_tracer_demo_source.py`'s own module docstring already calls this out:
"`poll_sweep_progress()`'s return value is duck-typed against
`SweepProgress`... rather than importing that class - it lives in
`mpp_sdk.io.spi_mcu`, which requires `spidev` at import time, exactly what
demo mode exists to avoid needing." **This constraint governs where the
new Protocol can live** - see "Design constraint" below.

### Design constraint: the new module must have zero import cost

`mpp_sdk/io/spi_mcu.py` imports `spidev` unconditionally at module level
(gated only to produce a friendlier error, not to make the import
optional - confirmed: `import spidev as _spidev` sits directly in a
`try/except ModuleNotFoundError` block at the top of the file, so merely
importing the module still requires `spidev` to be installed).
`scripts/curve_tracer_demo_source.py` was deliberately written to import
nothing beyond the stdlib specifically so `--demo` mode works on a machine
with neither a board nor `spidev` installed. **The new shared Protocol
must not live inside, or be imported from, `mpp_sdk/io/spi_mcu.py`** -
doing so would force every importer (including demo mode, if it ever
referenced the Protocol at runtime) to have `spidev` installed, defeating
the entire point of demo mode.

The fix: a brand-new module, `mpp_sdk/io/sweep_source.py`, with **no
imports beyond `typing`**. Confirmed safe to import unconditionally:
`mpp_sdk/io/__init__.py` today only eagerly imports `.base`, `.dynamic`,
`.noisy`, `.simulated` and lazily loads `.spi_mcu` via a module-level
`__getattr__` (already written specifically to avoid an eager `spidev`
import - see its `__getattr__` at the bottom of
`mpp_sdk/io/__init__.py`); adding a normal, eager
`from .sweep_source import SweepSource, SweepProgressLike` there costs
nothing extra since the new module itself has no dependencies.

`scripts/curve_tracer_demo_source.py` still does **not** need to import
this new module at runtime - `Protocol` conformance is structural, so
`DemoSweepSource` satisfies `SweepSource` without declaring it. Do not add
an import there; keep that file exactly as dependency-free as it is today
(only its docstring changes, to reference the Protocol by name instead of
describing it in prose - see Step 3).

## Scope

**In scope**:

- `mpp_sdk/io/sweep_source.py` (new file).
- `mpp_sdk/io/__init__.py` - export the two new names.
- `scripts/curve_tracer_server.py` - annotate `_poll_loop`'s `source_cm`
  variable with the new Protocol (import only under `TYPE_CHECKING`,
  matching this file's existing pattern for `SweepProgress`).
- `mpp_sdk/io/spi_mcu.py` - docstring-only update on `SpiMcuSource`
  referencing the new Protocol by name (no import needed - see "Design
  constraint").
- `scripts/curve_tracer_demo_source.py` - docstring-only update, same
  reasoning, no import added.
- `tests/test_sweep_source.py` (new) - Protocol-conformance tests for both
  concrete classes.

**Out of scope**:

- Making `SpiMcuSource` or `DemoSweepSource` explicitly inherit from the
  Protocol (`class SpiMcuSource(SignalSource, SweepSource):`) - unnecessary
  and, for `SpiMcuSource`, would require importing `sweep_source` into
  `spi_mcu.py`, which is harmless in itself (the new module has zero
  deps) but adds a coupling with no behavioral benefit, since structural
  typing already covers it. Protocols are meant to be checked, not
  inherited.
- `SignalSource` (`mpp_sdk/io/base.py`) - unrelated interface (algorithm
  V/I read/write), not touched by this plan.
- Any change to `_poll_loop`'s actual logic, or to either class's runtime
  behavior - this plan adds a type-level description of an existing
  contract, nothing more.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| New module imports standalone | `uv run python -c "from mpp_sdk.io.sweep_source import SweepSource, SweepProgressLike"` | no ImportError |
| Demo module still needs no `mpp_sdk` import | `grep -n "^import\|^from" scripts/curve_tracer_demo_source.py` | still only stdlib (`math`, `random`, `time`, `collections.abc`, `dataclasses`, `__future__`) |
| New tests | `uv run pytest tests/test_sweep_source.py -v` | all pass |
| Full check | `uv run pytest -v --tb=short && uv run ruff check . && uv run ruff format --check .` | all clean |

## Git workflow

- Branch: `refactor/sweep-source-protocol`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: create `mpp_sdk/io/sweep_source.py`

```python
"""Shared curve-tracer sweep-control interface.

`_poll_loop` (`scripts/curve_tracer_server.py`) drives either a real
`SpiMcuSource` (`mpp_sdk.io.spi_mcu`, needs `spidev` + a board) or a
`DemoSweepSource` (`scripts/curve_tracer_demo_source.py`, stdlib only)
completely interchangeably - it only ever calls the four methods and the
context-manager protocol declared here. Neither class inherits from
`SweepSource`; `Protocol` conformance is structural, so this module exists
purely to make that already-relied-upon contract explicit and checkable,
not to add a base class either implementation must extend.

This module must stay dependency-free (stdlib `typing` only): both
`mpp_sdk.io.spi_mcu` (needs `spidev` at import time) and
`scripts/curve_tracer_demo_source.py` (deliberately stdlib-only, so `--demo`
mode needs neither a board nor `spidev`) must be able to reference this
module, or be checked against it, without pulling in the other's
dependencies.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SweepProgressLike(Protocol):
    """Structural shape of one in-progress-sweep update - satisfied by both
    `mpp_sdk.io.spi_mcu.SweepProgress` and
    `scripts.curve_tracer_demo_source._DemoProgress` without either
    inheriting from this class."""

    index: int
    voltage: float
    current: float
    active: bool
    final_point: bool


@runtime_checkable
class SweepSource(Protocol):
    """The exact subset of a curve-tracer source that `_poll_loop`
    (`scripts/curve_tracer_server.py`) uses - satisfied structurally by both
    `mpp_sdk.io.spi_mcu.SpiMcuSource` and
    `scripts.curve_tracer_demo_source.DemoSweepSource`.

    Deliberately narrower than `SpiMcuSource`'s full public API (e.g. it
    omits `request_sweep`'s `poll_attempts`/`poll_interval_s` parameters,
    which `_poll_loop` never passes) - this describes what the shared
    caller actually needs, not everything either implementation happens to
    offer.
    """

    def start_sweep(self) -> None: ...
    def release_relay(self) -> None: ...
    def request_sweep(self) -> list[tuple[float, float]] | None: ...
    def poll_sweep_progress(self) -> SweepProgressLike | None: ...
    def __enter__(self) -> SweepSource: ...
    def __exit__(self, *args: object) -> None: ...
```

**Verify**: `uv run python -c "from mpp_sdk.io.sweep_source import SweepSource, SweepProgressLike"`
-> no ImportError.

### Step 2: export from `mpp_sdk/io/__init__.py`

Add to the existing eager imports (alongside `.base`, `.dynamic`, `.noisy`,
`.simulated` - **not** into the lazy `__getattr__` block, which exists only
for the `spidev`-gated `spi_mcu` symbols):

```python
from .sweep_source import SweepProgressLike, SweepSource
```

and add both names to the existing `__all__` list.

**Verify**: `uv run python -c "from mpp_sdk.io import SweepSource, SweepProgressLike"`
-> no ImportError. Also re-run
`uv run python -c "import mpp_sdk"` to confirm the top-level package still
imports cleanly (no accidental `spidev` requirement introduced).

### Step 3: annotate `_poll_loop` and update docstrings

In `scripts/curve_tracer_server.py`, add to the existing `TYPE_CHECKING`
block (which already imports `SweepProgress` the same way):

```python
if TYPE_CHECKING:
    from mpp_sdk.io.spi_mcu import SweepProgress
    from mpp_sdk.io.sweep_source import SweepSource
```

Then, inside `_poll_loop`, annotate `source_cm` in both branches (the file
already has `from __future__ import annotations` at module level, so this
annotation costs nothing at runtime):

```python
    if demo:
        ...
        source_cm: SweepSource = DemoSweepSource()
        ...
    else:
        ...
        source_cm: SweepSource = SpiMcuSource(bus=bus, device=device, speed_hz=speed_hz)
        ...
```

Update the comment directly above the `demo` branch (today: "Duck-typed
against SpiMcuSource (start_sweep/release_relay/ request_sweep/
poll_sweep_progress + context manager) - imported only here, and never
mpp_sdk.io.spi_mcu, so demo mode needs neither `spidev` nor a board.") to
reference the formal Protocol instead of describing the duck-typing in
prose, e.g.: "Implements `mpp_sdk.io.sweep_source.SweepSource` - imported
only here, and never `mpp_sdk.io.spi_mcu`, so demo mode needs neither
`spidev` nor a board." Keep the "imported only here" / no-`spi_mcu`-import
point - that constraint is still exactly as true and important as before.

In `mpp_sdk/io/spi_mcu.py`, update `SpiMcuSource`'s class docstring to add
one sentence noting it satisfies `mpp_sdk.io.sweep_source.SweepSource`
(prose only - do not add an import of `sweep_source` into this file; see
"Design constraint").

In `scripts/curve_tracer_demo_source.py`, update the module docstring's
"duck-typed against `SpiMcuSource`, not a subclass" sentence to instead
say it implements `mpp_sdk.io.sweep_source.SweepSource` (prose only - do
not add an import; this file must stay stdlib-only).

**Verify**:

```bash
grep -n "^import\|^from" scripts/curve_tracer_demo_source.py
```

Must show only stdlib imports (`math`, `random`, `time`,
`collections.abc.Callable`, `dataclasses.dataclass`, and
`__future__.annotations`) - **no** `mpp_sdk` import. This is the single
most important check in this whole plan; if it fails, the design
constraint above was violated.

### Step 4: write Protocol-conformance tests

Create `tests/test_sweep_source.py`, following the existing fake-`spidev`
pattern from `tests/test_spi_mcu.py` (its `_FakeSpiDev` class and the
sys.modules-injection technique - reproduce the minimal parts needed here
rather than importing that test file's fixture, to keep this file
self-contained):

```python
"""Runtime Protocol-presence tests: both curve-tracer sources expose the
members named by `mpp_sdk.io.sweep_source.SweepSource`. These checks catch
removed or renamed methods before `_poll_loop` encounters them. Python's
runtime Protocol checks do not validate parameter or return annotations;
that stronger enforcement requires a future static type-check gate.

`spidev` is a real Linux-only C-backed module and isn't installed in the
base dev environment (it's the optional ``[hardware]`` extra) - a minimal
fake is injected into ``sys.modules`` before importing
``mpp_sdk.io.spi_mcu``, same technique as ``tests/test_spi_mcu.py``.
"""

import sys
import types

from mpp_sdk.io.sweep_source import SweepProgressLike, SweepSource


class _FakeSpiDev:
    def open(self, bus: int, device: int) -> None:
        pass

    max_speed_hz: int | None = None
    mode: int | None = None

    def xfer2(self, tx: list[int]) -> list[int]:
        return [0] * 12

    def close(self) -> None:
        pass


def _make_spi_mcu_source():
    fake_module = types.ModuleType("spidev")
    fake_module.SpiDev = _FakeSpiDev
    sys.modules["spidev"] = fake_module
    sys.modules.pop("mpp_sdk.io.spi_mcu", None)

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    return SpiMcuSource(bus=0, device=0)


def test_spi_mcu_source_satisfies_sweep_source():
    source = _make_spi_mcu_source()
    assert isinstance(source, SweepSource)


def test_demo_sweep_source_satisfies_sweep_source():
    from scripts.curve_tracer_demo_source import DemoSweepSource

    assert isinstance(DemoSweepSource(), SweepSource)


def test_sweep_progress_satisfies_sweep_progress_like():
    from mpp_sdk.io.spi_mcu import SweepProgress

    progress = SweepProgress(index=0, voltage=1.0, current=0.1, active=True, final_point=False)
    assert isinstance(progress, SweepProgressLike)


def test_demo_progress_satisfies_sweep_progress_like():
    from scripts.curve_tracer_demo_source import _DemoProgress

    progress = _DemoProgress(index=0, voltage=1.0, current=0.1, active=True, final_point=False)
    assert isinstance(progress, SweepProgressLike)
```

Note: `@runtime_checkable` Protocol `isinstance` checks only verify that
the named methods/attributes **exist** (are callable, for methods) - they
do not check parameter or return types. This is still valuable regression
coverage (it catches a renamed or removed method immediately) but is not a
full static type check; this repo runs no static type checker in CI (`grep
-rn "mypy\|pyright" pyproject.toml .github/workflows/` was confirmed empty
when this plan was written), so this runtime check is the only automated
enforcement of this contract, and is worth keeping precise about what it
does and doesn't catch in the test file's own docstring/comments if you
want to expand on this note.

**Verify**: `uv run pytest tests/test_sweep_source.py -v` -> 4 passed.

### Step 5: full verification

```bash
uv run pytest -v --tb=short
uv run ruff check .
uv run ruff format --check .
```

All clean.

## Test plan

The 4 new tests in Step 4 are the entire test plan - they assert runtime
presence of the Protocol members for both concrete implementations and
both dataclass-shaped progress types. No behavior
changed elsewhere, so no other test should be affected.

## Done criteria

- [ ] `mpp_sdk/io/sweep_source.py` exists with `SweepProgressLike` and
      `SweepSource`, zero non-`typing` imports
- [ ] `mpp_sdk/io/__init__.py` exports both names eagerly (not via the
      lazy `__getattr__` block)
- [ ] `scripts/curve_tracer_server.py`'s `_poll_loop` annotates
      `source_cm: SweepSource` in both branches, imported under
      `TYPE_CHECKING`
- [ ] `scripts/curve_tracer_demo_source.py` still imports nothing beyond
      the stdlib (verified via the Step 3 grep)
- [ ] `tests/test_sweep_source.py` exists, 4 tests, all passing
- [ ] `uv run pytest -v --tb=short` - full suite green
- [ ] `uv run ruff check . && uv run ruff format --check .` - clean
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Either class's method signatures differ from what's quoted in "Current
  state" (per the drift check) - update the Protocol to match the live
  interface actually used by `_poll_loop`, not this plan's possibly-stale
  snapshot.
- Adding `from .sweep_source import ...` to `mpp_sdk/io/__init__.py`
  somehow triggers an import error unrelated to `sweep_source.py` itself -
  that would mean something changed about `mpp_sdk/io/__init__.py`'s
  other imports since this plan was written; investigate that, don't route
  around it.
- The Step 3 grep on `curve_tracer_demo_source.py` shows any non-stdlib
  import after your changes - that means the design constraint was
  violated; revert whichever edit added it.

## Maintenance notes

- If a third curve-tracer source implementation is ever added (e.g. a
  mock used only in tests, or a second hardware revision), it should be
  checked against `SweepSource` the same way, and `_poll_loop` should keep
  accepting anything satisfying that Protocol rather than special-casing a
  third concrete type.
- If the repository adds `mypy`, `pyright`, or another static checker,
  include `scripts/curve_tracer_server.py` in that gate. That is what will
  enforce method parameters and return types against `SweepSource`; the
  runtime tests intentionally cannot.
- If `_poll_loop` ever starts using more of `SpiMcuSource`'s API (e.g.
  passing `poll_attempts` to `request_sweep`), widen `SweepSource`'s
  method signature to match **and** update `DemoSweepSource` to accept
  (even if it ignores) the same parameter, so both stay conformant.
