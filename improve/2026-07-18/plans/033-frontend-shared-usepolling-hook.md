# Plan 033: Extract `usePolling` - the scaffold shared by `useLiveSweep`/`useConnectionStatus`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Hard dependency check (run first)**: `ls frontend/src/hooks/useLiveSweep.test.ts
> frontend/src/hooks/useConnectionStatus.test.ts frontend/vitest.config.ts
> 2>&1`. **If any of these three do not exist, STOP and report** - this
> plan depends on plan 032 (frontend hook tests) having landed first. Those
> tests are the regression safety net this refactor relies on; doing this
> work without them defeats the entire point of sequencing it second. Do
> not proceed to write `usePolling` "carefully by hand" instead - wait for
> plan 032.
>
> **Drift check (after confirming the dependency)**: `git diff --stat
> ff010a4..HEAD -- frontend/src/hooks/`. If `useLiveSweep.ts` or
> `useConnectionStatus.ts` changed since this plan was written (beyond
> plan 032 adding their `.test.ts` siblings), re-read both files in full
> before proceeding; on a mismatch with the excerpts below, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW *given plan 032 has landed* (the existing hook tests are
  black-box - they mock `@/lib/api` and assert on each hook's returned
  state/actions, never on internal implementation - so this refactor is
  fully covered without needing to touch a single test assertion). Risk is
  MED if attempted without plan 032's tests in place - hence the hard
  dependency check above.
- **Depends on**: **plan 032** (hard dependency - see above)
- **Category**: tech debt
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`useLiveSweep.ts` and `useConnectionStatus.ts` each independently
implement the same "poll a fetcher on a timer, apply the result via
setState, stop cleanly on unmount" scaffold - a `cancelled` flag, a
`timer` handle, a recursive `async function tick()` that self-reschedules
via `setTimeout` in a `finally` block, and a cleanup function that sets
`cancelled = true` and clears the timer. The two poll different intervals
(700ms vs 2000ms) and do different things with the result, but the
mechanism around that is identical. Found via the `improve` skill's
September 2026 audit (finding DEBT-04, sequenced explicitly after the
audit's TEST-03 finding/plan 032, since the audit itself flagged that
refactoring stateful polling logic with no test coverage would be
higher-risk than doing it after tests exist).

## Current state

Both hooks' polling scaffolds - see plan 032's own "Current state" section
for both files reproduced in full; the parts that matter here are the
`useEffect` bodies specifically:

`useLiveSweep.ts`'s scaffold:

```typescript
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function tick() {
      try {
        const data = await fetchLiveSweep()
        if (cancelled) return
        setActive(data.active)
        if (data.active) {
          setPartial(data.partial)
        } else {
          setPartial([])
          if (data.seq !== lastSeq.current) {
            setPoints(data.points)
            lastSeq.current = data.seq
          }
        }
      } catch (e) {
        console.error('polling /api/data failed', e)
      } finally {
        if (!cancelled) timer = setTimeout(tick, POLL_MS)
      }
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])
```

`useConnectionStatus.ts`'s scaffold:

```typescript
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function tick() {
      try {
        const data = await fetchLiveSweep()
        if (!cancelled) setStatus(statusFromLink(data.link))
      } catch {
        if (!cancelled) setStatus('disconnected')
      } finally {
        if (!cancelled) timer = setTimeout(tick, POLL_MS)
      }
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])
```

### The one behavioral difference between the two today (and the one intentional generalization this plan makes)

Look closely at the `catch` blocks: `useConnectionStatus` guards its
`setStatus` call with `if (!cancelled)`; `useLiveSweep`'s `catch` has
**no** such guard - it calls `console.error(...)` unconditionally, even if
the component unmounted while the fetch was in flight. Since
`console.error` isn't a `setState` call, this doesn't produce a React
warning either way - it's a minor, almost certainly unintentional
inconsistency, not a deliberate design choice.

**This plan's shared `usePolling` hook applies the `cancelled` guard to
both the success and error callbacks uniformly** - meaning after this
refactor, `useLiveSweep` will (correctly) stop logging poll errors that
arrive after unmount, matching `useConnectionStatus`'s existing, more
careful behavior. This is a deliberate, small behavior improvement (less
console noise after navigating away mid-poll), not an accidental side
effect - call it out in the PR description. Everything else is
byte-for-byte preserved.

### Why a plain parameter-based extraction would be wrong

A naive `usePolling(fetcher, onSuccess, onError, intervalMs)` that puts
`onSuccess`/`onError` in the internal `useEffect`'s dependency array would
restart the polling loop on **every render** if the caller passes a new
inline arrow function each time (which both hooks would, naturally, if
they call `usePolling(fetchLiveSweep, (data) => {...}, (e) => {...},
POLL_MS)` inline) - each render creates a new function identity, the
effect's dependency changes, React tears down and re-runs the effect,
and polling never settles into its intended steady cadence. The original
code avoids this entirely by using an empty `[]` dependency array (run
once on mount) and closing over the setState setters, which React
guarantees are referentially stable.

**The fix**: `usePolling` stores the latest `fetcher`/`onSuccess`/
`onError` in refs (updated on every render, a standard React pattern -
sometimes called "the latest ref pattern"), and its own `useEffect` still
runs its setup/teardown exactly once per mount (dependency array
`[intervalMs]` - stable across renders since both call sites pass a
literal number constant). The polling loop always calls through the refs,
so it never operates on a stale closure, and it never restarts due to a
new inline callback identity.

## Scope

**In scope**:

- `frontend/src/hooks/usePolling.ts` (new).
- `frontend/src/hooks/useLiveSweep.ts` - use it.
- `frontend/src/hooks/useConnectionStatus.ts` - use it.
- `frontend/src/hooks/usePolling.test.ts` (new) - direct tests for the
  extracted hook.

**Out of scope**:

- `useLiveSweep.test.ts` / `useConnectionStatus.test.ts` (from plan 032) -
  **do not modify these**. They are black-box against each hook's public
  return value and must pass unchanged after this refactor - that is the
  whole point of doing this after plan 032, and a passing, unmodified run
  of both files is this plan's primary correctness check (see Step 4).
- Any other hook or component.
- Changing either poll interval (`700`/`2000`) or any state-update logic
  inside `useLiveSweep`'s success handler (the `active`/`partial`/`points`/
  `seq` gating) - moves verbatim into a callback, unchanged.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Existing hook tests, unmodified | `cd frontend && pnpm exec vitest run src/hooks/useLiveSweep.test.ts src/hooks/useConnectionStatus.test.ts` | same pass count as before this change (14 total, per plan 032) |
| New `usePolling` tests | `cd frontend && pnpm exec vitest run src/hooks/usePolling.test.ts` | all pass |
| Full test run | `cd frontend && pnpm test` | all pass |
| Build (typecheck) | `cd frontend && pnpm build` | exit 0 |
| Lint | `cd frontend && pnpm lint` | exit 0 |

## Git workflow

- Branch: `refactor/frontend-shared-use-polling`.
- One commit.
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: create `frontend/src/hooks/usePolling.ts`

```typescript
import { useEffect, useRef } from 'react'

/**
 * Poll `fetcher` on a fixed interval for as long as the calling component
 * is mounted - the scaffold shared by `useLiveSweep` and
 * `useConnectionStatus` (both poll `GET /api/data`, at different
 * intervals, doing different things with the result).
 *
 * `fetcher`/`onSuccess`/`onError` are read through refs, updated every
 * render, so the polling loop always calls the latest closures without
 * needing them in the effect's own dependency array - putting them there
 * directly would restart the interval on every render whenever a caller
 * passes a fresh inline function (the common case), which would prevent
 * polling from ever settling into a steady cadence. `intervalMs` is
 * assumed stable (a literal constant at each call site) and *is* a real
 * effect dependency - if it changes at runtime, the interval restarts,
 * which is the correct behavior for a genuinely changed poll rate.
 *
 * `onSuccess`/`onError` are only called while the component is still
 * mounted - a response or rejection that lands after unmount is silently
 * dropped, never applied to state.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  onSuccess: (data: T) => void,
  onError: (error: unknown) => void,
  intervalMs: number,
): void {
  const fetcherRef = useRef(fetcher)
  const onSuccessRef = useRef(onSuccess)
  const onErrorRef = useRef(onError)
  fetcherRef.current = fetcher
  onSuccessRef.current = onSuccess
  onErrorRef.current = onError

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function tick() {
      try {
        const data = await fetcherRef.current()
        if (!cancelled) onSuccessRef.current(data)
      } catch (e) {
        if (!cancelled) onErrorRef.current(e)
      } finally {
        if (!cancelled) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // fetcher/onSuccess/onError are intentionally read via refs, not
    // listed here - see this function's docstring.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs])
}
```

The `eslint-disable` comment is defensive - this repo lints with `oxlint`,
not `eslint`, so it is inert today, but costs nothing and documents intent
if `eslint`'s `react-hooks/exhaustive-deps` rule is ever added later.

**Verify**: `cd frontend && pnpm exec tsc -b --noEmit` (or just proceed to
Step 2/3 and let `pnpm build` catch it) - no type errors from this file in
isolation yet, since nothing calls it.

### Step 2: use it in `useLiveSweep.ts`

Replace the whole `useEffect` block with a call to `usePolling`, and
remove the now-unused `useEffect` import (keep `useCallback`, `useRef`,
`useState`):

```typescript
import { useCallback, useRef, useState } from 'react'
import { fetchLiveSweep, releaseRelay as releaseRelayRequest, startSweep as startSweepRequest } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'
import type { CurvePoint } from '@/types'
import { usePolling } from './usePolling'

const POLL_MS = 700

export function useLiveSweep() {
  const [partial, setPartial] = useState<CurvePoint[]>([])
  const [points, setPoints] = useState<CurvePoint[]>([])
  const [active, setActive] = useState(false)
  const lastSeq = useRef(-1)

  const handleData = (data: LiveSweepState) => {
    setActive(data.active)
    if (data.active) {
      setPartial(data.partial)
    } else {
      // Once a sweep is no longer active, `points` (gated on `seq`) is
      // authoritative - see this hook's docstring. Clearing `partial`
      // here too matters when a sweep never completes (link drop,
      // relay released mid-capture): otherwise a stale `partial` from
      // the aborted attempt keeps rendering in LiveChart, which falls
      // back to `partial` whenever `points` is still empty.
      setPartial([])
      if (data.seq !== lastSeq.current) {
        setPoints(data.points)
        lastSeq.current = data.seq
      }
    }
  }

  const handleError = (e: unknown) => {
    console.error('polling /api/data failed', e)
  }

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS)

  const start = useCallback(() => {
    startSweepRequest().catch((e) => console.error('start-sweep failed', e))
  }, [])

  const releaseRelay = useCallback(() => {
    releaseRelayRequest().catch((e) => console.error('release-relay failed', e))
  }, [])

  return { partial, points, active, start, releaseRelay }
}
```

Keep the hook's own top-of-file docstring (the "Polls GET /api/data on a
timer..." comment) - it still describes this hook's behavior accurately,
just update it if it specifically described the removed `useEffect`
mechanics rather than the `active`/`seq` semantics (re-read it first; the
version quoted in plan 032's "Current state" is prose about semantics, not
implementation, so it likely needs no change at all).

`handleData`/`handleError` are plain functions, not wrapped in
`useCallback` - unlike `start`/`releaseRelay`, they don't need referential
stability, since `usePolling` reads them through a ref on every render
regardless of identity (see `usePolling`'s docstring). Do not add
`useCallback` here; it would be a no-op past what `usePolling` already
handles.

**Verify**: `cd frontend && pnpm exec vitest run src/hooks/useLiveSweep.test.ts`
-> same 7 tests, all passing, unmodified.

### Step 3: use it in `useConnectionStatus.ts`

```typescript
import { useState } from 'react'
import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'
import type { ConnectionStatus } from '@/types'
import { usePolling } from './usePolling'

const POLL_MS = 2000

function statusFromLink(link: string): ConnectionStatus {
  if (link === 'no data yet') return 'connecting'
  if (link.startsWith('error')) return 'disconnected'
  if (link === 'demo') return 'demo'
  return 'connected'
}

/** Derived from GET /api/data's `link` field, not just HTTP reachability -
 * the server can be up while the Pico link itself is down. */
export function useConnectionStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  const handleData = (data: LiveSweepState) => setStatus(statusFromLink(data.link))
  const handleError = (_error: unknown) => setStatus('disconnected')

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS)

  return status
}
```

`_error` (leading underscore) is required, not stylistic - this project's
`tsconfig.app.json` has `noUnusedParameters: true`, and TypeScript exempts
underscore-prefixed parameters from that check; a bare unused `error`
parameter would fail `pnpm build`.

**Verify**: `cd frontend && pnpm exec vitest run src/hooks/useConnectionStatus.test.ts`
-> same 7 tests, all passing, unmodified.

### Step 4: confirm both existing test files are byte-identical to before this plan

```bash
git diff --stat -- frontend/src/hooks/useLiveSweep.test.ts frontend/src/hooks/useConnectionStatus.test.ts
```

Expected: **no output** (zero changes) - these files must not need any
edit for this refactor to work, since they only observe each hook's
public return value. If you find yourself wanting to change either test
file to make it pass, stop - that means the refactor changed observable
behavior, which this plan must not do (the one documented exception is
the post-unmount-error-logging change in "Current state", which neither
test file exercises or asserts on).

### Step 5: write `usePolling.test.ts`

Create `frontend/src/hooks/usePolling.test.ts`:

```typescript
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('usePolling', () => {
  it('calls the fetcher immediately on mount', () => {
    const fetcher = vi.fn().mockReturnValue(new Promise(() => {}))
    renderHook(() => usePolling(fetcher, vi.fn(), vi.fn(), 1000))
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('calls onSuccess with the resolved value', async () => {
    const fetcher = vi.fn().mockResolvedValue('hello')
    const onSuccess = vi.fn()
    renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 1000))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('hello'))
  })

  it('calls onError when the fetcher rejects', async () => {
    const error = new Error('boom')
    const fetcher = vi.fn().mockRejectedValue(error)
    const onError = vi.fn()
    renderHook(() => usePolling(fetcher, vi.fn(), onError, 1000))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(error))
  })

  it('does not call onSuccess for a response that resolves after unmount', async () => {
    let resolveFetch: (value: string) => void = () => {}
    const fetcher = vi.fn().mockReturnValue(
      new Promise<string>((resolve) => {
        resolveFetch = resolve
      }),
    )
    const onSuccess = vi.fn()
    const { unmount } = renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 1000))
    unmount()
    resolveFetch('too late')
    await new Promise((r) => setTimeout(r, 10))
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it(
    'polls again after intervalMs',
    async () => {
      const fetcher = vi.fn().mockResolvedValue('tick')
      const onSuccess = vi.fn()
      renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 200))
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2), { timeout: 2000 })
    },
    3000,
  )
})
```

**Verify**: `cd frontend && pnpm exec vitest run src/hooks/usePolling.test.ts`
-> 5 passed.

### Step 6: full verification

```bash
cd frontend
pnpm test
pnpm build
pnpm lint
```

All exit 0.

## Test plan

The 5 new `usePolling.test.ts` tests (Step 5) directly cover the extracted
hook's contract: immediate first call, success/error dispatch, post-
unmount silence, and re-polling at the given interval. The unmodified,
still-passing `useLiveSweep.test.ts`/`useConnectionStatus.test.ts` (Step 4)
are the integration check that both real call sites behave identically
after the extraction.

## Done criteria

- [ ] `frontend/src/hooks/usePolling.ts` exists
- [ ] `useLiveSweep.ts` and `useConnectionStatus.ts` both use it, with no
      remaining duplicated `useEffect`/`tick`/`cancelled` scaffold
- [ ] `frontend/src/hooks/usePolling.test.ts` exists, 5 tests, all passing
- [ ] `git diff --stat -- frontend/src/hooks/useLiveSweep.test.ts
      frontend/src/hooks/useConnectionStatus.test.ts` shows **no changes**
- [ ] `cd frontend && pnpm test` - all pass
- [ ] `cd frontend && pnpm build` - exit 0
- [ ] `cd frontend && pnpm lint` - exit 0
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Plan 032's test files don't exist yet (per the hard dependency check at
  the top) - do not proceed with this plan until they land.
- Either existing hook's code differs from what's quoted in "Current
  state" (per the drift check) - re-derive the extraction against the
  live logic.
- `useLiveSweep.test.ts` or `useConnectionStatus.test.ts` needs **any**
  edit to keep passing after Steps 2-3 - that means this refactor changed
  observable behavior beyond the one documented, unasserted exception
  (post-unmount error logging). Revert and report which behavior changed.

## Maintenance notes

- Any future hook that polls a `GET` endpoint on an interval (there is
  exactly one shared endpoint today, `/api/data`, polled by two hooks at
  two rates - a third consumer is plausible if the workbench grows another
  live-updating panel) should use `usePolling` from the start.
- If `usePolling` ever needs to support a *dynamic* `intervalMs` (changing
  at runtime, not just per-hook-constant), the effect's `[intervalMs]`
  dependency already handles that correctly (the interval restarts with
  the new value) - no further change needed for that case.
