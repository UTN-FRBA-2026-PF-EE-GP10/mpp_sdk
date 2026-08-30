# Plan 023: React + shadcn curve workbench, served from the Pi

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard prerequisite**: plan 021 (curve library) must be DONE - the panes
> group by its `measurement` metadata and list via its `GET /curves`.
> Plan 020 (streaming) is *soft*: build the live-drawing pane against it if
> it has landed, otherwise render completed curves only and leave the
> component ready for it.
>
> **Drift check (run first)**: `git diff --stat f837fc2..HEAD --
> scripts/curve_tracer_server.py scripts/curve_tracer_web/`.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED (introduces a JS build toolchain to a repo that has none -
  the risk is dependency/tooling sprawl on a Pi, not correctness)
- **Depends on**: plan 021 (hard), plan 020 (soft - enables live drawing)
- **Category**: direction / feature
- **Planned at**: commit `f837fc2`, 2026-08-26

## Why this matters

The current page (`scripts/curve_tracer_web/`) was written in an hour to
prove the transport worked, and it shows: one chart, one curve, no history,
and a hand-rolled polling loop whose "has anything changed" check was
already wrong once (it diffed point count, so every sweep after the first
was silently dropped). It cannot show what the measurement campaign
actually needs - several curves side by side, grouped by what kind of
measurement they are, with the shaded case next to its baseline.

The operator has asked for a lightweight React frontend using shadcn
components, built with pnpm and served from the Pi. This plan replaces the
throwaway page with a real one, organised around the measurement kinds
plan 021 defines.

## Current state

`scripts/curve_tracer_server.py` is a stdlib `http.server` that serves
three static files by exact path and a `/data` JSON endpoint, plus
`POST /start-sweep` and `POST /release-relay` routed through a queue so
only the poll thread touches SPI:

```python
_STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/script.js": "script.js",
    "/chart.umd.min.js": "chart.umd.min.js",
}
_POST_COMMANDS = {
    "/start-sweep": "start_sweep",
    "/release-relay": "release_relay",
}
```

`/data` returns `{points: [{x, y}], link, seq}` where `seq` increments per
fetched sweep. Points are `x` = volts, `y` = **milliamps** (the UI's unit),
while plan 021 stores amps - keep that conversion in one place.

The repo has **no JavaScript toolchain**: no `package.json`, no `node_modules`,
no JS in CI. `chart.umd.min.js` is a vendored Chart.js UMD bundle loaded
with a plain `<script>` tag.

AGENTS.md requires that the base Python install stay lean and that heavy
optional things be gated. The JS build is a *build-time* dependency only -
the Pi serves prebuilt static files and must not need Node at runtime.

## Design

### Build once, serve static

The Pi serves **prebuilt** assets. Node/pnpm are needed only to build, and
the build can happen on a dev machine or on the Pi, but never at request
time. This keeps `curve_tracer_server.py` a stdlib-only script and keeps
the runtime dependency set exactly as it is today.

```text
frontend/                     # source, committed
  package.json
  pnpm-lock.yaml
  vite.config.ts
  index.html
  src/
scripts/curve_tracer_web/     # build output, committed
  index.html
  assets/*.js, *.css
```

Committing the build output is deliberate: the Pi must be able to `git
pull` and serve, with no Node installed. Note it in `frontend/README.md`
so nobody "fixes" it by gitignoring the output.

Replace the exact-path `_STATIC_FILES` dict with a directory-serving
handler rooted at `scripts/curve_tracer_web/`, resolving paths safely
(reject anything that escapes the root after `Path.resolve()`), serving
`index.html` for unknown non-asset paths so client-side routing works.
Extend `_CONTENT_TYPES` for `.css`, `.svg`, `.woff2`, `.map`.

### Stack

- **Vite** + React + TypeScript (`pnpm create vite`). Vite because the
  output is plain static files with no server runtime.
- **Tailwind + shadcn/ui** as requested. Add only the components used -
  shadcn is copy-in, so unused ones never enter the tree.
- **Chart.js via `react-chartjs-2`**, keeping the existing chart
  configuration (dual axis I(V) / P(V), the current dark theme's colours).
  Do not swap charting libraries in the same plan as the framework - if
  Chart.js turns out to be wrong for this, that is its own decision.

Keep the dependency list short and justify each addition in
`frontend/README.md`. "Lightweight" is an explicit requirement.

### Layout: panes by measurement kind

The main view is a tab bar over the measurement kinds present in the
library (`GET /curves`, grouped by `measurement`), each tab a pane titled
with that kind. Inside a pane:

- A chart overlaying every curve of that kind, one series per record,
  legend showing each record's `label`.
- A table of the pane's records: label, captured time, Voc, Isc, P_mpp,
  and each panel's tilt - the columns that make a shaded curve
  interpretable next to its baseline.
- A per-record visibility toggle so a pane with many curves stays readable.

A separate **Live** pane holds the capture controls: Start Sweep, Release
Relay, the in-progress chart, and the save form (label, measurement kind,
per-panel tilt, notes) posting to `POST /save-curve`.

Measurement kinds come from `GET /measurement-kinds` (plan 021, Step 6) -
do not hardcode the vocabulary in TypeScript.

### Live drawing

If plan 020 has landed, the Live pane's chart appends `partial` points as
they arrive and switches to the authoritative `points` array when `active`
goes false. If plan 020 has not landed, render only completed sweeps and
keep the component's props shaped so streaming drops in without a
rewrite - `{points, partial, active}` with `partial` empty.

Poll `/data` on a timer as today. Do not introduce websockets: the poll
loop is simple, already works, and the data rate is a handful of points
per second at most.

## Scope

**In scope**:

- `frontend/**` (create)
- `scripts/curve_tracer_web/**` (replaced by build output)
- `scripts/curve_tracer_server.py` (directory serving, content types)
- `.gitignore` (`frontend/node_modules/`, `frontend/dist/` if not the
  output dir)
- `frontend/README.md`, and a pointer from the root `README.md`
- `improve/2026-07-18/plans/README.md` (status row only)

**Out of scope**:

- Any firmware change.
- Any change to `mpp_sdk/` - the frontend talks HTTP only.
- Adding Node to CI. If a JS check is wanted later it is its own plan;
  this one must not make the Python CI depend on a JS build.
- Websockets, SSR, a router library, or a state-management library. If one
  of these seems necessary, that is a STOP condition - the app is a few
  panes over a polling endpoint.

## Steps

### Step 1: server serves a directory

Rewrite the static handler to serve `scripts/curve_tracer_web/`
recursively with path-escape rejection and the extended content types,
falling back to `index.html`. Do this **first**, against the existing
vanilla page, so the change is verifiable in isolation.

**Verify**: the existing page still loads and a sweep still plots - the
current UI must keep working before it is replaced. Confirm
`GET /../../etc/passwd` (and URL-encoded variants) returns 404, not a file.

### Step 2: scaffold the frontend

`pnpm create vite frontend --template react-ts`, add Tailwind and
shadcn/ui, set `build.outDir` to `../scripts/curve_tracer_web` with
`emptyOutDir: true`, and set a relative `base` so assets resolve when
served from `/`.

**Verify**: `cd frontend && pnpm install && pnpm build` writes
`scripts/curve_tracer_web/index.html` + `assets/`, and the Python server
serves the Vite starter page.

### Step 3: data layer

A typed client for `/data`, `/curves`, `/measurement-kinds`,
`/save-curve`, `/start-sweep`, `/release-relay`. One module, one place
where mA↔A conversion happens, mirroring the existing endpoint shapes
exactly - do not redesign the API here.

**Verify**: `pnpm build` with `tsc` passing (Vite's default template runs
`tsc -b` as part of `build`).

### Step 4: Live pane

Port the existing chart configuration (dual axis, dark theme, auto-scale
and unit-toggle buttons) into a React component, plus the capture
controls and save form. Feature-detect `partial`/`active` so it works
with or without plan 020.

**Verify**: with the Python server running against a fake cache (the
no-hardware smoke-test pattern), the pane renders a curve and the save
form posts successfully.

### Step 5: measurement panes

Tabs over the kinds present in the library, each with the overlay chart,
record table, and visibility toggles per the Design section.

**Verify**: with several saved records across two kinds, both tabs render
with correct grouping and per-record stats.

### Step 6: docs

`frontend/README.md`: how to build, why the output is committed, why each
dependency is there. Add a pointer from the root `README.md`. Update
`scripts/curve_tracer_server.py`'s module docstring, which currently
describes the vanilla page adapted from the ESP32 reference.

**Verify**: `npx --yes markdownlint-cli2 frontend/README.md README.md`
→ 0 issues.

### Step 7: plan index

Update this plan's row in `improve/2026-07-18/plans/README.md`.

## Test plan

- `cd frontend && pnpm build` succeeds with `tsc` clean - that is the
  frontend's regression gate for now.
- `uv run pytest tests/ -q` unchanged (no Python behaviour changes beyond
  static serving; add a test for the path-escape rejection in Step 1 if a
  natural home exists).
- Manual on the Pi: build, `mpp-sdk curve-tracer-web`, capture a baseline
  and a shaded curve, confirm both panes render and the Live pane drives
  the hardware.

## Done criteria

- [ ] `cd frontend && pnpm install && pnpm build` succeeds from clean
- [ ] The Pi serves the built app with **no Node installed**
- [ ] Panes group by measurement kind, sourced from the library, not
      hardcoded
- [ ] Live pane can start a sweep, release the relay, and save a labeled
      curve
- [ ] Path-escape attempts return 404
- [ ] `uv run pytest tests/ -q` / `ruff check` / `ruff format --check` clean
- [ ] On-target: full capture-to-pane round trip - **needs the board**

## STOP conditions

Stop and report if:

- The dependency tree grows beyond a handful of direct deps, or the build
  output exceeds a few hundred KB. "Lightweight" was the requirement; a
  heavy bundle on a Pi-served page defeats the point.
- Serving a directory turns out to need a real web framework - it does
  not, and adding Flask/FastAPI here would pull a runtime dependency onto
  the Pi that this design deliberately avoids.
- Building on the Pi itself is impractically slow. Building on a dev
  machine and committing the output is the intended path; say so and move
  on rather than adding a Pi-side build step.
- Any of this appears to need a change under `mpp_sdk/` - the frontend is
  an HTTP client and must stay one.

## Maintenance notes

- The build output is committed on purpose. Anyone who gitignores
  `scripts/curve_tracer_web/` breaks deployment on the Pi.
- The API shapes are shared with plan 021's server endpoints; changing one
  side requires changing the other, and the mA/A boundary is the easiest
  thing to get wrong (`/data` is mA, the library stores A).
- The vanilla page's Chart.js config is the reference for the port -
  recover it from git history if the ported chart looks wrong.
- If plan 020 lands after this, only the Live pane changes: the props are
  already shaped for it.
