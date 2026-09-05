# Curve workbench frontend

React + TypeScript curve-tracer UI (plan 023), scaffolded with
[Vite](https://vite.dev), styled with Tailwind, and using
[shadcn/ui](https://ui.shadcn.com) components (copy-in, not an npm
dependency - only the pieces actually used live under
`src/components/ui/`).

**Current status**: wired to a real backend -
`scripts/curve_tracer_server.py`'s FastAPI app (`mpp-sdk[web]`). `src/lib/api.ts`
is the one place that talks to it (`GET /api/data`/`/api/curves`/
`/api/measurement-kinds`, `POST /api/save-curve`/`/api/start-sweep`/
`/api/release-relay`) and the one place the mA/A unit boundary is crossed.
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
- shadcn/ui components (`button`, `card`, `tabs`, `badge`, `separator`,
  `table`) - copy-in source under `src/components/ui/`, not a runtime
  dependency; add more only as panes need them.
- `chart.js`, `react-chartjs-2` - ports the existing vanilla page's dual-axis
  I(V)/P(V) chart. Do not add a second charting library.

Keep this list short - "lightweight" is an explicit requirement from the
operator, carried over from plan 023.
