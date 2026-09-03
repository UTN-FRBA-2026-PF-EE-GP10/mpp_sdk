# Curve workbench frontend

React + TypeScript curve-tracer UI (plan 023), scaffolded with
[Vite](https://vite.dev), styled with Tailwind, and using
[shadcn/ui](https://ui.shadcn.com) components (copy-in, not an npm
dependency - only the pieces actually used live under
`src/components/ui/`).

**Current status**: mock-data prototype only. Nothing here talks to the Pi
yet - `src/lib/mockCurves.ts` and `src/hooks/useMockSweep.ts` stand in for
the real `GET /curves` library and plan 020's per-point streaming. See
`improve/2026-07-18/plans/README.md`'s 2026-09-02 note on plan 023 for the
two decisions that diverge from that plan's original design (a FastAPI
backend instead of stdlib `http.server`; point-by-point streaming promoted
from a soft to a hard dependency).

## Develop

```bash
pnpm install
pnpm dev       # http://localhost:5173
```

## Build

```bash
pnpm build     # tsc -b && vite build -> frontend/dist/ (gitignored)
```

Build output is **not yet** committed to `scripts/curve_tracer_web/` -
that switch (replacing the vanilla-JS UI the Pi currently serves) happens
once this app is wired to a real backend, per plan 023.

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
