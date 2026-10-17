# Curve workbench frontend

React + TypeScript curve-tracer UI, scaffolded with
[Vite](https://vite.dev), styled with Tailwind, and using
[shadcn/ui](https://ui.shadcn.com) components (copy-in, not an npm
dependency - only the pieces actually used live under
`src/components/ui/`).

**Current status**: wired to a real backend -
`scripts/curve_tracer_server.py`'s FastAPI app (`mpp-sdk[web]`). `src/lib/api.ts`
is the one place that talks to it (curve routes: `GET /api/data`/`/api/curves`/
`/api/measurement-kinds`, `POST /api/save-curve`/`/api/start-sweep`/
`/api/release-relay`; run routes: `GET /api/run-config`/`/api/runs`/
`/api/runs/live`, `POST /api/runs/start`/`/api/runs/stop`; pico-config routes:
`GET /api/pico-config`, `POST /api/pico-config`, `POST /api/pico-config/reset-cutoff`)
and the one place the mA/A unit boundary is crossed.
This replaced the earlier mock-data prototype and the vanilla-JS page
under `scripts/curve_tracer_web/` (now the build output directory below,
not source).

## Code style

- Single quotes, no semicolons.
- Vendored `src/components/ui/*` keeps double quotes, as shadcn generates it.
- Never run prettier over the tree.
- Comments explain why, with plain hyphens.

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
shown as "Simulated board" in the connection indicator).

The connection indicator is also a three-way capture-mode menu
(`src/lib/captureMode.ts`), named to match `mpp_sdk/curves/record.py`'s
`CURVE_SOURCES` exactly. "Demo" is overloaded elsewhere in this codebase
(the server's own `--demo` status above is a fourth, unrelated meaning),
so each mode's on-screen label is written to be told apart from the
others at a glance:

- **PICO connected** (`hardware`) - the default. Start Measurement live,
  saving allowed.
- **Replay on the board** (`firmware-replay`) - real board, but the
  "Replay curve" buttons are the point: real SPI, a curve already stored
  in the firmware, not measured this session. Saving is still allowed -
  the result is real data off the wire. Only selectable with a live link;
  the app falls back to `hardware` on its own if the link drops.
- **Demo** (`simulated`) - no board and no hardware commands. Swaps the
  curve/run libraries for bundled fixtures (`src/lib/demoFixtures.ts`),
  disables every write (save/delete) and every genuinely hardware-only
  action (Start Measurement, Hand panel to converter), while still letting the
  two "Replay curve" buttons replay a bundled sweep locally into the
  capture pane. Called "sandbox" in code (`src/lib/sandbox.ts`) to avoid a
  third overload of the word "demo" alongside `ConnectionStatus`'s own
  `'demo'` value above - `useSandbox()` is the one place to read "are we
  fully offline" - reuse it rather than adding another check.

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

## Active session and capturing into a session

Curves and runs stay one flat, shared library - a run points at a curve by
`curve_ref`, an old curve can be a later session's reference - but each is
*stamped* with the session it was measured in (`session_id`, see
`mpp_sdk/curves/record.py`). A stamp is not ownership: deleting a session
leaves its curves and runs alone, and a stamp naming a deleted session is
just a stamp that matches no session.

- The **active session** (`src/lib/activeSession.ts`) is a client concept,
  kept in `localStorage`. Opening a session makes it active; the banner under
  the header (`ActiveSessionBar`) says so on every section and dismisses it
  ("Stop filing"). Measure and the run form repeat it. The id is sent per
  request (`session_id` on `POST /api/save-curve` and `POST /api/runs/start`);
  the server keeps no "current session" and rejects an id that names no
  session. When it does (the session was deleted in another tab), the client
  clears the active session and says what happened to that save or run.
- Curves and Runs lists get a "This session / Everything" switch while a
  session is active.
- Every `curve`/`run` step has **Capture into this step**
  (`src/lib/sessionCapture.ts`): sweep or run, wait, save stamped, then link.
  Nothing is linked until the record is saved, so a failed capture leaves the
  step as it was. It uses a `measurement` of `other` and no panel list (a step
  does not say which kind it is); use Measure when that matters, then link the
  result from the step's picker. A run uses the server's default bounds and
  duration and no reference curve.
- A session file exports what its steps link *and* everything stamped with
  the session, so a capture filed from Measure and never linked is not lost.
- None of this is reachable in demo mode or while viewing an imported session
  file (`useReadOnly()` / `useCaptureSession()`).

## Pico Dynamic Configuration

The **Pico Configuration** pane (`src/components/PicoConfigPane.tsx`), reachable
via the "Pico Configuration" tab in Measure or the "Pico Config" sidebar item,
allows live on-the-fly adjustment of board settings over high-speed SPI without
recompiling firmware:

- **ADC Divider Jumpers**: $V_{\text{in}}$ and $V_{\text{out}}$ jumper scaling
  (`Low` ~27.3 V, `Mid` ~51.5 V, `Full` ~75.6 V).
- **Hardware Safety Cutoffs**: $I_{\max}$ in mA and $V_{\max}$ in mV with
  automatic PWM shutdown, plus a "Reset Tripped Cutoff" trigger to resume gate drive.
- **Power Stage Switch**: $R_{\text{on}}$ MOSFET on-resistance in $\text{m}\Omega$.
- **Sensors**: MAX31865 RTD PT100 SPI sensor enable/disable toggle.
- **Bench Power Supply Mode**: Autonomous Pico closed-loop PID or open-loop
  fixed-duty PSU regulation setpoint ($V_{\text{out}}$ in mV and duty cycle).
- **Batch & Single Transmission**: Checkboxes let operators select any subset of
  parameters to send in batch, with individual per-field send buttons for instant tweaks.

## Build

```bash
pnpm build     # tsc -b && vite build -> scripts/curve_tracer_web/
```

Build output is **committed** on purpose: the Pi serves
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

Keep this list short - "lightweight" is an explicit requirement.
