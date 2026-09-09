# Plan 037: Surface asynchronous command failures in the workbench

## Status

- Priority: P1
- Effort: S remaining (was M) - the server half is done, only the visible
  UI display is left
- Risk: LOW; additive status contract, no SPI protocol change
- Confidence: HIGH
- Depends on: 032 soft
- Planned at: `7f3ea44`, 2026-09-08
- Category: correctness / user feedback
- **Progress (2026-09-08, same-day reconciliation)**: the "concurrently
  changing local patch" this plan refers to is done and merged. It covers
  everything in this plan except the actual visible UI - deliberately left
  for the operator to design/try by hand (they want to iterate on the UI
  themselves rather than have an agent guess at it):
  - `scripts/curve_tracer_server.py`: `_SweepCache` has a dedicated
    `_command_error`/`set_command_error()` (not overloaded onto `_link`),
    `snapshot()` returns six items, both route unpackings updated,
    `_poll_loop`'s command branch calls `set_command_error(f"{cmd} failed:
    {exc}")` on failure and `set_command_error(None)` on success.
  - `GET /api/data` now includes `"command_error": str | None`.
  - `tests/test_curve_tracer_server.py`: three new tests, including the
    exact regression this plan describes (a failed command followed by a
    successful bulk poll in the same iteration - error still visible
    afterward) and the default-response-shape test updated. All pass,
    `uv sync --group dev --extra web` was used (not skipped).
  - `frontend/src/lib/api.ts`: `DataResponse`/`LiveSweepState` now carry
    `command_error`/`commandError`; `fetchLiveSweep()` passes it through
    (absent field maps to `null`, per this plan's rollout-compatibility
    note).
  - **Not done**: `useLiveSweep.ts` does not yet expose `commandError` in
    its returned state, and `CurveWorkbench.tsx` does not yet render it
    anywhere. HTTP-action-rejection display (a `start()`/`releaseRelay()`
    call itself throwing, separate from a *queued* command later failing
    server-side) is also not done. This is exactly the remaining scope -
    see Steps 3 (UI portion only) and 4 below.

## Why this matters

Start/release HTTP requests acknowledge queueing before the source executes
commands. At committed HEAD a command failure sets the link error, but a
successful bulk poll in the same iteration overwrites it. The operator sees
no failure. The server-side half of this is now fixed (see Progress above);
the React client still drops the field, so the operator still cannot see a
command failure in the UI - finishing only the server did not notify the
operator, exactly as this plan predicted.

## Current state

The server-side patch described in the original "Current state" section is
done and merged - re-read `scripts/curve_tracer_server.py`,
`tests/test_curve_tracer_server.py`, and `frontend/src/lib/api.ts` directly
rather than trusting this summary, but do not redo that work.

- `frontend/src/hooks/useLiveSweep.ts`: action errors only call
  `console.error`; returned state is still `{ partial, points, active,
  start, releaseRelay }` - `commandError` from `fetchLiveSweep()` is
  fetched but not threaded through.
- `frontend/src/components/CurveWorkbench.tsx`: owns the capture pane and
  is the appropriate place for visible command feedback - still
  unchanged.
- `tests/test_curve_tracer_server.py`: `client` fixture supplies isolated
  cache and queue, with a temporary curve directory and no SPI hardware.

## Scope (remaining)

`useLiveSweep.ts`, `CurveWorkbench.tsx`, their focused tests if 032 has
landed, and regenerated `scripts/curve_tracer_web/`. The server, its test
file, and the typed API client are done - do not redo them. No firmware,
controller, dependency migration, shared polling refactor, or change to
the existing command ordering. This is not acknowledgement of physical
actuation: SDK transport success does not prove the relay moved.

## Steps (remaining)

1. ~~Reconcile the local patch...~~ **Done** - see Progress above.
2. ~~Test a failed command followed by a successful bulk poll...~~ **Done**
   - see Progress above; all tests pass with `uv sync --group dev --extra
   web`.
3. Thread `commandError` from `fetchLiveSweep()`'s already-typed response
   through `useLiveSweep()`'s returned state, and render it visibly in
   `CurveWorkbench.tsx` - **this is a UI/UX design decision, not just
   plumbing** (a banner? inline text near the Start/Release buttons? a
   toast?), left deliberately open for hands-on iteration rather than
   prescribed here. Also display rejected HTTP action requests (a
   `start()`/`releaseRelay()` call itself throwing - currently only
   `console.error`'d, per `useLiveSweep.ts`'s existing catch blocks).
   Keep connection status (`ConnectionIndicator`) visually distinct from
   command status - they answer different questions. Verify failure and
   recovery in the demo UI (`--demo` mode) with the dev server, or with
   mocked API responses if plan 032's test tooling has landed.
4. Run `pnpm lint` and `pnpm build` from `frontend/`, then review and
   include the generated bundle. If 032 exists, add a mocked polling test
   showing error persistence across successful polls and clearing after
   retry.

## Test plan and done criteria (remaining)

- ~~API data and save routes work with the snapshot shape; default error
  null.~~ **Done.**
- ~~Failed command followed by successful bulk polling retains its
  error.~~ **Done.**
- ~~A successful command clears the previous error; the poll loop
  survives.~~ **Done.**
- UI displays both asynchronous source errors and HTTP request failures -
  **remaining**.
- Frontend lint/build pass and the served bundle matches source -
  **remaining, once the UI change lands**.

## STOP conditions

None specific to the remaining UI work - it is additive and low-risk. If
the eventual UI design needs command retries or firmware ACK changes,
report that separately: retrying start/release changes behavior.

## Maintenance notes

A single last-command error is sufficient for the present single operator.
Do not describe it as per-client acknowledgement or introduce command IDs
without a separate requirement. Preserve API compatibility across 031/033.

## Git workflow

Leave this handoff uncommitted. Implementation requires a later execution
request; preserve unrelated working-tree changes and use a dedicated branch.
Do not include internal session identifiers in artifacts or commit messages.

## Verification environment

The audit environment lacked FastAPI: the API test module skipped entirely.
When implementing, install the declared dependencies with
`uv sync --group dev --extra web` before running the gates below. A skipped
API module is not a passing verification result. No hardware is needed.
