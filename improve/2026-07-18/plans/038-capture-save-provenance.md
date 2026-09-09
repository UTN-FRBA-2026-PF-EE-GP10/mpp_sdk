# Plan 038: Save the displayed capture, not an unversioned latest sweep

## Status

- Priority: P1
- Effort: M
- Risk: MED; changes the save request contract
- Confidence: HIGH
- Depends on: 037 first if it changes the cache snapshot; 032 soft
- Planned at: `7f3ea44`, 2026-09-08 (server has a concurrent local patch)
- Category: correctness / measurement provenance

## Why this matters

A browser can display sweep A while another sweep B finishes before Save
arrives. The request contains metadata only, and the backend always saves
its latest cache points: B is silently labeled as A. Disabling the button
while the browser sees `active` cannot guard this race. The record also uses
save time as `captured_at`, obscuring when the measurement was obtained.

## Current state

- `scripts/curve_tracer_server.py`, `_SweepCache.set`: completed sweeps
  replace `_points` and increment `_seq` under the cache lock.
- `post_save_curve`: ignores `_seq` and `_active`, constructs a `CurveRecord`
  from latest points with `captured_at=now_utc()`.
- `frontend/src/lib/api.ts`, `SaveCurveInput`: label, measurement, panels,
  notes only; the live response already has `seq`.
- `frontend/src/hooks/useLiveSweep.ts`: tracks last sequence privately but
  does not expose the sequence associated with rendered completed points.
- `CurveWorkbench.tsx`: `hasCapture = !active && points.length > 0`.
- `mpp_sdk/curves/library.py`: exclusive file creation already prevents
  filename collisions; do not replace or duplicate that protection.

## Scope

Cache/save route and API tests, frontend API types/live hook/workbench and
focused hook tests if available, generated frontend bundle, frontend README
for changed request contract. No schema migration of saved curves, no deletion
API, no firmware or controller changes, no measurement vocabulary redesign.

## Steps

1. Record a server UTC timestamp when a completed sweep enters the cache.
   State explicitly that this is receipt time, not a hardware timestamp.
   Preserve it across repeated polls and repeated saves of that capture.
   Include points, sequence, active status and timestamp in one locked
   snapshot; keep route readers consistent with the local command-error patch.
2. Require `expected_seq` on Save. Under one locked read, reject missing or
   stale sequence and active sweeps; use 409 for state conflicts and normal
   validation for a missing field. Copy the matched points and timestamp
   atomically. A newer sweep after that copy must not change what is saved.
   Do disk I/O after releasing the cache lock. Empty captures remain 409.
3. Expose the sequence belonging to completed displayed points from the live
   hook, updating points and identity together. Pass it through the save form.
   On 409 show that the displayed capture is no longer current; require the
   operator to inspect the new capture before retrying. Never auto-retry with
   a newly fetched sequence. Keep the metadata entered by the operator.
4. Test via the existing isolated FastAPI fixture: cache A, display its seq,
   cache B, submit A's seq; expect 409 and no file. Submit B's seq; verify the
   file contains B and its cache receipt timestamp. Test active/empty capture,
   missing seq, repeated polls, and timestamp stability across saves.
5. Update mock save requests/tests, document the API change and regenerate
   the frontend bundle. Old clients should fail explicitly rather than save
   an unintended capture. No historical JSON rewriting is needed.

## Test plan and done criteria

- `uv run pytest tests/test_curve_tracer_server.py tests/test_curve_library.py -v -rs`
  passes with no API skips.
- Stale/active save requests write no file; matching requests save the exact
  selected points and stable receipt timestamp.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- From `frontend/`, `pnpm lint` and `pnpm build` pass. If 032 exists, test
  points/seq association through active and completed poll transitions.
- Manual two-client check cannot silently save B under the displayed A.

## STOP conditions

If session restart identity must be supported across persistent clients,
add a server instance token or opaque capture ID before release: an integer
sequence alone can collide across restarts. Resolve that requirement explicitly
rather than presenting process-local sequence checking as globally unique.
If true hardware acquisition time is required, report the protocol gap.

## Maintenance notes

Capture identity is distinct from measurement kind and filename. Keep conflict
handling explicit when campaigns or multiple operators are introduced.

## Git workflow

Leave this handoff uncommitted. Implementation requires a later execution
request; preserve unrelated working-tree changes and use a dedicated branch.
Do not include internal session identifiers in artifacts or commit messages.

## Verification environment

The audit environment lacked FastAPI: the API test module skipped entirely.
When implementing, install the declared dependencies with
`uv sync --group dev --extra web` before running the gates below. A skipped
API module is not a passing verification result. No hardware is needed.
