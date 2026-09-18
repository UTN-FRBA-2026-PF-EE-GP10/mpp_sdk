# Curve workbench frontend

React + TypeScript curve-tracer UI (plan 023), scaffolded with
[Vite](https://vite.dev), styled with Tailwind, and using
[shadcn/ui](https://ui.shadcn.com) components (copy-in, not an npm
dependency - only the pieces actually used live under
`src/components/ui/`).

**Current status**: wired to a real backend -
`scripts/curve_tracer_server.py`'s FastAPI app (`mpp-sdk[web]`). `src/lib/api.ts`
is the one place that talks to it (curve routes: `GET /api/data`/`/api/curves`/
`/api/measurement-kinds`, `POST /api/save-curve`/`/api/start-sweep`/
`/api/release-relay`; run routes: `GET /api/run-config`/`/api/runs`/
`/api/runs/live`, `POST /api/runs/start`/`/api/runs/stop`) and the one place
the mA/A unit boundary is crossed.
This replaced the earlier mock-data prototype and the vanilla-JS page
under `scripts/curve_tracer_web/` (now the build output directory below,
not source). See `improve/2026-07-18/plans/README.md`'s notes on plan 023
for the two decisions that diverge from that plan's original design (a
FastAPI backend instead of stdlib `http.server`; point-by-point streaming
promoted from a soft to a hard dependency - plan 020 landed first).

## Develop

```bash
pnpm install
pnpm dev       # http://localhost:5173 - proxies /api/* to :8000 (vite.config.ts)
```

Run the backend alongside it in another terminal:
`uv run mpp-sdk curve-tracer-web` (needs `uv sync --extra web --extra hardware`;
without a board attached, `/api/data` just reports `link: "error: ..."`
forever - the API itself still works for browsing/saving curves).

No board and no Pi at hand? `uv run mpp-sdk curve-tracer-web --demo` swaps
in a simulated sweep source (`scripts/curve_tracer_demo_source.py`) - only
needs `uv sync --extra web`, runs on any machine, and behaves like the
real thing from the frontend's perspective (`link` reports `"demo"`,
shown as a distinct status in the connection indicator).

The connection indicator is also a three-way capture-mode menu
(`src/lib/captureMode.ts`), named to match `mpp_sdk/curves/record.py`'s
`CURVE_SOURCES` exactly:

- **PICO connected** (`hardware`) - the default. Start Measurement live,
  saving allowed.
- **Demo with PICO** (`firmware-replay`) - real board, but the "Demo curve"
  buttons are the point: real SPI, a curve already stored in the
  firmware, not measured this session. Saving is still allowed - the
  result is real data off the wire. Only selectable with a live link;
  the app falls back to `hardware` on its own if the link drops.
- **Demo** (`simulated`) - no board and no hardware commands. Swaps the
  curve/run libraries for bundled fixtures (`src/lib/demoFixtures.ts`),
  disables every write (save/delete) and every genuinely hardware-only
  action (Start Measurement, Release Relay), while still letting the two
  "Demo curve" buttons replay a bundled sweep locally into the capture
  pane. Called "sandbox" in code (`src/lib/sandbox.ts`) to avoid a third
  overload of the word "demo" alongside `ConnectionStatus`'s own `'demo'`
  value above - `useSandbox()` is the one place to read "are we fully
  offline" - reuse it rather than adding another check.

  One exception: starting a run (`RunPane`) still reaches the backend even
  here, against a `SimulatedSource` (`POST /api/runs/start` with
  `"simulated": true`) - the registered MPPT algorithms are Python, and
  porting them to TypeScript would fork the one implementation the whole
  project is built around, so there is no offline equivalent to fall back
  to the way there is for a curve. This does write a `RunRecord` to the
  server's real run library, which is why this is acceptable at all: the
  record is stamped `source: "simulated"` server-side
  (`mpp_sdk/runs/record.py`'s `RUN_SOURCES`, never taken from the
  request), `ProvenanceBadge` marks it unmissably everywhere a run is
  listed or played back, and the setup form and live view both say
  "simulated" throughout, so nothing written here can be mistaken for a
  measurement or shown as one. No board is touched and no hardware
  command is ever sent - the one write demo mode makes is this clearly
  labelled, non-physical one.

## Build

```bash
pnpm build     # tsc -b && vite build -> scripts/curve_tracer_web/
```

Build output is **committed** on purpose (plan 023): the Pi serves
prebuilt static files from `curve_tracer_server.py` and must not need Node
installed at runtime. Rebuild and commit the output whenever `src/`
changes - nothing regenerates it automatically.

## Dependencies, and why

- `react`, `react-dom`, `typescript`, `vite` - the scaffold.
- `tailwindcss`, `@tailwindcss/vite` - utility CSS, no separate config file
  needed (Tailwind v4's Vite plugin).
- `@base-ui/react` - the unstyled primitives shadcn/ui's dialog, dropdown
  menu, and menu components wrap (`Dialog`, `Menu`).
- shadcn/ui components (`button`, `card`, `tabs`, `badge`, `separator`,
  `table`, `dialog`, `dropdown-menu`) - copy-in source under
  `src/components/ui/`, not a runtime dependency; add more only as panes
  need them.
- `lucide-react` - icons (nav, close buttons, theme toggle).
- `chart.js`, `react-chartjs-2` - ports the existing vanilla page's dual-axis
  I(V)/P(V) chart. Do not add a second charting library.

Keep this list short - "lightweight" is an explicit requirement from the
operator, carried over from plan 023.
