# Plan 021: On-disk library of captured I-V curves, with measurement metadata

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat f837fc2..HEAD --
> mpp_sdk/io/spi_mcu.py scripts/curve_tracer_server.py data/`. If any
> changed, re-read them before trusting this plan's excerpts.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (new files + a new module; touches no firmware and no
  existing algorithm/model code)
- **Depends on**: none (016/018/019 are DONE - the tracer already returns
  real curves)
- **Category**: direction / feature
- **Planned at**: commit `f837fc2`, 2026-08-26

## Why this matters

The curve tracer now produces real I-V curves, but each one lives only in
the web UI until the next sweep overwrites it. The goal behind the tracer
is to build up a *body* of measured curves - one panel in full light, a
second at varying tilt to emulate partial shading, later under a
controllable dimmer - and then replay them through the MPPT algorithm
benchmark to predict how each algorithm behaves on the real array before
committing one to firmware. None of that is possible until a sweep can be
saved with enough context to know what it *is*. A curve without its
measurement conditions is not a data point; it is a picture.

This plan defines the storage format and the capture path. Plan 022
consumes it to drive the benchmark; plan 023's UI groups panes by the
metadata defined here. Getting the schema right first means neither of
those has to migrate data later.

## Current state

`SpiMcuSource.request_sweep()` (`mpp_sdk/io/spi_mcu.py`) returns
`list[tuple[float, float]] | None` - `(volts, amps)` pairs, already scaled
to physical units, at most `_TRACER_SWEEP_POINTS` (20) of them. A sweep
that aborted early returns fewer.

`scripts/curve_tracer_server.py` holds exactly one sweep in memory:

```python
class _SweepCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._points: list[tuple[float, float]] = []
        self._link = "no data yet"
        self._seq = 0
```

`data/` exists with only `data/README.md` and a `plecs/` subdirectory.
`data/README.md` documents the scrub policy that AGENTS.md requires for
measured data - **read it before choosing where files land**, and keep new
measured data consistent with it.

The repo is public. AGENTS.md's "What not to commit" forbids committing
raw measurement files with unscrubbed metadata; captured curves are
operator data, not repo content, so the default capture directory must be
git-ignored (see Step 1).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `uv run pytest tests/ -q` | all pass |
| Lint | `uv run ruff check .` | "All checks passed!" |
| Format | `uv run ruff format --check .` | "N files already formatted" |
| Markdown | `npx --yes markdownlint-cli2 <file>` | "0 issues" |

## Scope

**In scope**:

- `mpp_sdk/curves/__init__.py` (create)
- `mpp_sdk/curves/record.py` (create)
- `mpp_sdk/curves/library.py` (create)
- `tests/test_curve_library.py` (create)
- `scripts/curve_tracer_server.py` (add a save path)
- `scripts/curve_tracer_web/index.html`, `script.js` (minimal capture UI)
- `.gitignore`, `data/README.md`
- `improve/2026-07-18/plans/README.md` (status row only)

**Out of scope**:

- Any firmware change - this plan reads what the tracer already returns.
- The React rewrite (plan 023). Add only the minimum controls to the
  existing vanilla UI needed to save a labeled curve.
- Feeding curves into the benchmark (plan 022) - defining the format is
  this plan; consuming it is that one.
- Any automatic irradiance measurement. Metadata is operator-declared for
  now; the dimmer plan may add measured values later.

## Design

### The record

One sweep is one JSON file. JSON rather than CSV because the metadata is
structured and the point count is small; readable in a text editor, and
`json` is stdlib so nothing new is pulled into the base install.

```json
{
  "schema": 1,
  "captured_at": "2026-08-26T21:14:03Z",
  "label": "both panels flat, lamp at 30cm",
  "measurement": "baseline",
  "panels": [
    {"id": "A", "tilt_deg": 0},
    {"id": "B", "tilt_deg": 0}
  ],
  "notes": "",
  "points": [{"v": 21.33, "i": 0.006}, {"v": 21.265, "i": 0.013}]
}
```

- `schema` - integer, bumped only on a breaking change. Readers must
  reject an unknown schema loudly rather than guess (see `load`).
- `measurement` - the grouping key plan 023's panes use. A free string,
  but seed the vocabulary in `MEASUREMENT_KINDS` (see below) so the UI can
  offer a dropdown and typos don't silently create a new pane.
- `panels` - one entry per panel in the array, each with its tilt. This is
  what distinguishes "both flat" from "one tilted to emulate shading",
  which is the whole point of the exercise. A single-panel setup is a
  one-element list.
- `points` - `v` in volts, `i` in amps, matching `request_sweep()`'s units
  and the `SignalSource` convention. Ordered as swept (rising current).

Derived quantities (Voc, Isc, MPP) are **not** stored - they are computed
on load by `CurveRecord`. Storing them invites the file disagreeing with
its own points.

### `MEASUREMENT_KINDS`

Seed vocabulary, in `record.py`:

```python
MEASUREMENT_KINDS = (
    "baseline",       # all panels same tilt, uniform illumination
    "partial-shade",  # one panel tilted/shaded relative to the other
    "tilt-sweep",     # a series varying one panel's tilt
    "dimmer",         # varying illumination (plan 024)
    "other",
)
```

Not an enum: an operator must be able to write a kind this list did not
anticipate without a code change. The tuple exists so the UI can populate
a dropdown and so a typo is visible next to the intended value.

### API

```python
@dataclass(frozen=True)
class PanelSetup:
    id: str
    tilt_deg: float

@dataclass(frozen=True)
class CurveRecord:
    captured_at: datetime
    label: str
    measurement: str
    panels: tuple[PanelSetup, ...]
    points: tuple[tuple[float, float], ...]   # (volts, amps)
    notes: str = ""

    @property
    def open_circuit_voltage(self) -> float: ...
    @property
    def short_circuit_current(self) -> float: ...
    def mpp(self) -> tuple[float, float, float]: ...  # (V, I, P)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "CurveRecord": ...
```

`open_circuit_voltage` is the largest measured `v`, `short_circuit_current`
the largest measured `i`. Both are **measured extremes, not
extrapolations**: the sweep stops just past the knee, so Isc is close, but
Voc is the first point's voltage under near-zero load. Document that in the property
docstrings: a consumer that needs true Voc/Isc must extrapolate itself
(plan 022 addresses this for the model).

`library.py`:

```python
def default_dir() -> Path: ...          # data/curves/, override via env
def save(record: CurveRecord, directory: Path | None = None) -> Path: ...
def load(path: Path) -> CurveRecord: ...
def load_all(directory: Path | None = None) -> list[CurveRecord]: ...
def group_by_measurement(records) -> dict[str, list[CurveRecord]]: ...
```

`save` names files `{captured_at:%Y%m%dT%H%M%SZ}-{slug(label)}.json` so a
directory listing sorts chronologically and is readable without opening
files. Slug: lowercase, non-alphanumerics to `-`, collapsed, trimmed to 40
chars. On collision (two saves in the same second), append `-2`, `-3`, ...
rather than overwriting - a captured measurement is never silently lost.

`load` raises `ValueError` naming the file and the offending field on a
missing key, a bad type, or an unknown `schema`. These files are written by
this code today but hand-edited by operators tomorrow; a clear parse error
beats a `KeyError` from three frames deep.

### Capture path in the server

`_SweepCache` gains nothing - saving is an explicit action, not automatic.
Rationale: the poll loop re-fetches the same sweep repeatedly while idle,
and auto-saving would either write duplicates or need dedup logic that
the operator cannot override. An explicit "Save" also lets the label be
typed *after* seeing the curve.

Add `POST /save-curve` taking a JSON body `{label, measurement, panels,
notes}`, which pairs it with the cache's current points and writes via
`library.save`. Return `{"path": "..."}` with 200, or 409 if the cache
holds no points yet.

Add `GET /curves` returning `[{path, captured_at, label, measurement,
n_points, voc, isc, p_mpp}]` for every saved record - enough for plan 023
to render pane headers without loading full point arrays.

## Steps

### Step 1: git-ignore captured data, document it

Add to `.gitignore`:

```gitignore
# Captured I-V curves - operator measurement data, not repo content.
# See data/README.md and AGENTS.md "What not to commit".
data/curves/
```

Extend `data/README.md` with a short section pointing at `data/curves/`,
the schema above, and the rule that anything promoted into git must first
be scrubbed per the existing policy in that file.

**Verify**: `printf 'x' > data/curves/probe.json && git status --short |
grep -q 'data/curves' && echo LEAKED || echo IGNORED; rm -f
data/curves/probe.json` → prints `IGNORED`.

### Step 2: `mpp_sdk/curves/record.py`

Implement `PanelSetup`, `CurveRecord`, `MEASUREMENT_KINDS`, and the
to/from-dict pair per the Design section. Use `datetime` with explicit UTC
(`datetime.now(UTC)`), serialised with `.isoformat()`; parse with
`datetime.fromisoformat`. Type hints on all public API per AGENTS.md.
No numpy - this module is plain stdlib so it stays importable anywhere.

**Verify**: `uv run python -c "from mpp_sdk.curves.record import
CurveRecord, MEASUREMENT_KINDS; print(MEASUREMENT_KINDS)"` → prints the
tuple.

### Step 3: `mpp_sdk/curves/library.py`

Implement `default_dir`, `save`, `load`, `load_all`,
`group_by_measurement`. `default_dir()` returns
`Path(os.environ.get("MPP_SDK_CURVE_DIR", "data/curves"))` resolved
against the repo root, and `save` creates it if missing.
`load_all` skips nothing silently: a file that fails to parse raises,
naming the file.

**Verify**: `uv run ruff check mpp_sdk/curves/` → passes.

### Step 4: tests

Create `tests/test_curve_library.py` covering, at minimum:

- round-trip: `save` then `load` returns an equal record (use `tmp_path`)
- `open_circuit_voltage` / `short_circuit_current` / `mpp` on a known
  hand-built curve with an obvious answer
- filename collision in the same second produces two files, not one
- `load` on a record with an unknown `schema` raises `ValueError`
- `load` on a record missing `points` raises `ValueError` naming the field
- `group_by_measurement` buckets correctly, including an unknown kind

Model the file on `tests/test_spi_mcu.py`'s structure (module docstring,
section comments, one behaviour per test).

**Verify**: `uv run pytest tests/test_curve_library.py -q` → all pass.

### Step 5: server save + list endpoints

Add `POST /save-curve` and `GET /curves` to
`scripts/curve_tracer_server.py` per the Design section. Both are pure
filesystem work - do **not** route them through the SPI command queue,
which exists only to keep `SpiMcuSource` single-threaded.

**Verify**: extend the existing no-hardware smoke test pattern:

```bash
uv run python -c "
import json, queue, threading, time, urllib.request
from http.server import ThreadingHTTPServer
from scripts.curve_tracer_server import _SweepCache, _make_handler
c=_SweepCache(); c.set([(21.3,0.006),(18.0,0.195)],'ok')
s=ThreadingHTTPServer(('127.0.0.1',8094),_make_handler(c,queue.Queue()))
threading.Thread(target=s.serve_forever,daemon=True).start(); time.sleep(.2)
r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8094/save-curve',
  method='POST', data=json.dumps({'label':'t','measurement':'baseline',
  'panels':[{'id':'A','tilt_deg':0}],'notes':''}).encode()))
print('save', r.status, json.loads(r.read()))
print('list', json.loads(urllib.request.urlopen('http://127.0.0.1:8094/curves').read()))
s.shutdown()"
```

→ `save 200 {...}` then a one-entry list. Delete the file it wrote.

### Step 6: minimal capture UI

In `scripts/curve_tracer_web/`, add a label text input, a `measurement`
`<select>` seeded from `MEASUREMENT_KINDS` (serve it from a new
`GET /measurement-kinds` rather than duplicating the list in JS), and a
"Save curve" button that POSTs. Show the saved path or the error inline.
Reuse the existing `.btn` / `.ctrl-label` styles; keep it to one toolbar
row. This is deliberately throwaway - plan 023 replaces this page.

**Verify**: serve the page and confirm the new controls render and a save
round-trips (same smoke-test harness as Step 5, plus a manual click).

### Step 7: plan index

Update this plan's row in `improve/2026-07-18/plans/README.md`.

## Test plan

- `tests/test_curve_library.py` per Step 4 - pure stdlib, no hardware, no
  network.
- `uv run pytest tests/ -q` → all pass including the new file.
- Manual on the Pi: capture a `baseline` curve and a `partial-shade` curve
  (one panel tilted), confirm both land in `data/curves/` with correct
  metadata and sane Voc/Isc.

## Done criteria

- [ ] `uv run pytest tests/ -q` passes, including new `test_curve_library.py`
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] `data/curves/` is git-ignored (Step 1 verification prints `IGNORED`)
- [ ] `POST /save-curve` + `GET /curves` round-trip without hardware
- [ ] `data/README.md` documents the format and the scrub rule
- [ ] Two real curves captured on the bench with differing `measurement`
      values - **needs the board**

## STOP conditions

Stop and report if:

- `data/README.md`'s existing scrub policy conflicts with storing curves
  under `data/` - it governs, and the location needs an operator decision.
- A captured curve turns out to need a field this schema has no room for
  (e.g. per-point timestamps for plan 020's streaming). Bump `schema` and
  say so; do not overload an existing field.
- The code at the excerpts above has drifted (see the drift check).

## Maintenance notes

- `schema` is the migration lever. Any breaking change bumps it and
  teaches `load` to either upgrade or reject with a clear message.
- Voc/Isc are measured extremes, not true intercepts. Plan 022 must not
  treat them as datasheet values - the sweep stops just past the knee.
- If the tracer's point count ever becomes configurable, nothing here
  changes: `points` is variable-length by construction.
