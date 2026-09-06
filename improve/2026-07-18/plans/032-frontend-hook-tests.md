# Plan 032: Add vitest + tests for `useLiveSweep`/`useConnectionStatus`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> frontend/src/hooks/useLiveSweep.ts frontend/src/hooks/useConnectionStatus.ts
> frontend/src/lib/api.ts frontend/package.json`. If any of these changed
> since this plan was written, re-read the changed file(s) in full before
> proceeding; on a mismatch between the excerpts below and the live code,
> treat it as a STOP condition - the tests below assert exact behavior of
> the code as quoted.

## Status

- **Priority**: P3
- **Effort**: M - mostly tooling setup (no test infrastructure exists in
  `frontend/` today), the tests themselves are small
- **Risk**: LOW - purely additive (new devDependencies, new config file,
  new test files); nothing under `frontend/src/` that ships to production
  changes
- **Depends on**: none (Plan 033, if selected, depends on *this* plan
  landing first - do not do that work here)
- **Category**: test coverage
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`frontend/src/hooks/useLiveSweep.ts` and
`frontend/src/hooks/useConnectionStatus.ts` are the two hooks that turn raw
`GET /api/data` polling into the UI's live state - `useLiveSweep`'s
`seq`-gating logic (only adopt a newly-completed sweep's `points` once,
never re-apply the same sweep on a later poll) and its "clear `partial`
whenever `active` goes false, even on an aborted zero-point sweep" fix are
exactly the kind of small, stateful, easily-inverted logic this repo has
already caught real bugs in once this session (September audit finding #1,
PR #67) with no unit test to have caught it sooner. `useConnectionStatus`'s
`statusFromLink` mapping (`'no data yet'` -> `connecting`, `error*` ->
`disconnected`, `'demo'` -> `demo`, anything else -> `connected`) is a pure
function wrapped in polling boilerplate - untested today.

`frontend/` has **no test tooling at all** - no `vitest`, no
`@testing-library/*`, no test script in `package.json`. This plan adds the
minimum tooling needed to test these two hooks and nothing more (no
component-rendering tests, no snapshot tests) - found via the `improve`
skill's September 2026 audit (finding TEST-03).

## Current state

Both hooks in full, `frontend/src/hooks/useLiveSweep.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchLiveSweep, releaseRelay as releaseRelayRequest, startSweep as startSweepRequest } from '@/lib/api'
import type { CurvePoint } from '@/types'

const POLL_MS = 700

export function useLiveSweep() {
  const [partial, setPartial] = useState<CurvePoint[]>([])
  const [points, setPoints] = useState<CurvePoint[]>([])
  const [active, setActive] = useState(false)
  const lastSeq = useRef(-1)

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

  const start = useCallback(() => {
    startSweepRequest().catch((e) => console.error('start-sweep failed', e))
  }, [])

  const releaseRelay = useCallback(() => {
    releaseRelayRequest().catch((e) => console.error('release-relay failed', e))
  }, [])

  return { partial, points, active, start, releaseRelay }
}
```

(Comments trimmed above for length - re-read the live file, they explain
the *why* behind the gating but do not change any of the logic quoted.)

`frontend/src/hooks/useConnectionStatus.ts`, in full:

```typescript
import { useEffect, useState } from 'react'
import { fetchLiveSweep } from '@/lib/api'
import type { ConnectionStatus } from '@/types'

const POLL_MS = 2000

function statusFromLink(link: string): ConnectionStatus {
  if (link === 'no data yet') return 'connecting'
  if (link.startsWith('error')) return 'disconnected'
  if (link === 'demo') return 'demo'
  return 'connected'
}

export function useConnectionStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

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

  return status
}
```

Both hooks import `fetchLiveSweep` (and `useLiveSweep` also imports
`startSweep`/`releaseRelay`) from `frontend/src/lib/api.ts`, whose relevant
exported shape is:

```typescript
export interface LiveSweepState {
  points: CurvePoint[]
  partial: CurvePoint[]
  active: boolean
  link: string
  seq: number
}

export async function fetchLiveSweep(): Promise<LiveSweepState> { ... }
export async function startSweep(): Promise<void> { ... }
export async function releaseRelay(): Promise<void> { ... }
```

`frontend/package.json` today has no `test` script and no test-related
devDependency (confirmed: `grep -n "vitest\|testing-library\|jsdom"
frontend/package.json` returns nothing). `frontend/vite.config.ts` sets a
`@` -> `./src` alias and the React plugin - the new test config needs the
same alias so `vi.mock('@/lib/api', ...)` resolves.

`frontend/tsconfig.app.json` has `"include": ["src"]` - so any
`*.test.ts` files placed under `frontend/src/hooks/` are automatically
type-checked by `pnpm build`'s `tsc -b` step, same as any other source
file. This is intentional and matches this project's ecosystem convention
(test files type-check alongside app code) - do not add an `exclude` to
route around it; instead make sure the new test files type-check cleanly.

## Scope

**In scope**:

- `frontend/package.json` - new devDependencies, new `test` script.
- `frontend/pnpm-lock.yaml` - updated by `pnpm add`; this repository
  commits the frontend lockfile and installs with `--frozen-lockfile`.
- `frontend/vitest.config.ts` (new).
- `frontend/tsconfig.node.json` - add `vitest.config.ts` to `include` (so
  it gets Node-context editor typing, same as `vite.config.ts` already
  does; optional polish, not required for `pnpm test` to work, but cheap
  and consistent).
- `frontend/src/hooks/useConnectionStatus.test.ts` (new).
- `frontend/src/hooks/useLiveSweep.test.ts` (new).
- `.github/workflows/frontend.yml` - **only if it already exists** (i.e.
  plan 025 has landed by the time you execute this plan) - add a `pnpm
  test` step. If it does not exist yet, do not create it (that is plan
  025's job) - just note in your PR description that a future `frontend.yml`
  should include a test step, so it isn't forgotten.

**Out of scope**:

- Any other hook, component, or `.tsx` file - this plan is exactly the two
  hooks named in the audit finding. `CurveWorkbench.tsx`,
  `ConnectionIndicator.tsx`, `App.tsx`, etc. get no new tests here.
- Any change to `useLiveSweep.ts` or `useConnectionStatus.ts` themselves -
  this plan is tests only. If a test reveals a real bug, report it - do
  not fix it as part of this plan (that would be a separate, correctness-
  focused plan/PR).
- Deduplicating the two hooks' near-identical polling scaffold into a
  shared `usePolling` hook - that is plan 033, deliberately sequenced
  *after* this plan (it wants these tests in place first, so refactoring
  the scaffold has a safety net).
- `@testing-library/jest-dom` and its DOM-matcher assertions
  (`.toBeInTheDocument()` etc.) - not needed, since these tests assert on
  hook return values (plain JS state), not rendered DOM nodes. Do not add
  it unless a later plan actually renders components.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install new tooling | `cd frontend && pnpm add -D vitest jsdom @testing-library/react @testing-library/dom` | exit 0, `pnpm-lock.yaml` updated |
| Run the new tests | `cd frontend && pnpm test` | exit 0, all tests pass |
| Build still passes (test files type-check too - see "Current state") | `cd frontend && pnpm build` | exit 0 |
| Lint still passes | `cd frontend && pnpm lint` | exit 0 |

## Git workflow

- Branch: `test/frontend-hook-tests`.
- One commit (or two - tooling setup, then tests - operator's call; this
  session's established preference has been one focused commit per PR, so
  one commit covering both is also fine).
- Push and open a PR only after operator confirmation.

## Steps

### Step 1: install the new tooling

```bash
cd frontend
pnpm add -D vitest jsdom @testing-library/react @testing-library/dom
```

Do not pin exact versions in this plan - let `pnpm` resolve current
versions compatible with this project's React 19 (`@testing-library/react`
16.x+ supports React 19; if `pnpm` reports a peer-dependency conflict,
that is a STOP condition - see below, do not force-install past it).

**Verify**: `git diff --stat frontend/package.json` shows the four new
devDependencies added, and `frontend/pnpm-lock.yaml` changed.

### Step 2: add `frontend/vitest.config.ts`

A **separate** file from `vite.config.ts` (not merged into it) - this
keeps the production build's config completely untouched, so there is
zero risk of a test-only setting leaking into `pnpm build`'s output:

```typescript
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
  },
})
```

The `@` alias must match `vite.config.ts`'s exactly (it does above) - it
is what lets `vi.mock('@/lib/api', ...)` in the test files resolve to the
same module the hooks themselves import.

**Verify**: no command yet - this file is exercised by Step 4/5's test run.

### Step 3: wire up `package.json` and (optionally) `tsconfig.node.json`

In `frontend/package.json`'s `"scripts"`, add:

```json
"test": "vitest run",
```

(Placed alongside the existing `dev`/`build`/`lint`/`preview` scripts, any
order is fine.)

Optionally, in `frontend/tsconfig.node.json`, add `vitest.config.ts` to
`include`:

```json
"include": ["vite.config.ts", "vitest.config.ts"]
```

This gives `vitest.config.ts` the same Node-context editor typing as
`vite.config.ts` already has - purely a nicety, `pnpm test` works without
it since `vitest` transpiles its own config file regardless of whether
`tsc` also checks it.

**Verify**: `cat frontend/package.json | grep '"test"'` shows the new
script.

### Step 4: write `useConnectionStatus.test.ts`

Create `frontend/src/hooks/useConnectionStatus.test.ts`:

```typescript
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useConnectionStatus } from './useConnectionStatus'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
}))

import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'

function mockData(overrides: Partial<LiveSweepState>): LiveSweepState {
  return { points: [], partial: [], active: false, link: 'ok', seq: 0, ...overrides }
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('useConnectionStatus', () => {
  it('starts as connecting before the first poll resolves', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('connecting')
  })

  it('reports connecting when link is "no data yet"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'no data yet' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connecting'))
  })

  it('reports connected for "ok"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'ok' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connected'))
  })

  it('reports connected for "waiting for sweep"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'waiting for sweep' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connected'))
  })

  it('reports demo for link === "demo"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'demo' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('demo'))
  })

  it('reports disconnected when link starts with "error"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'error: boom' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('disconnected'))
  })

  it('reports disconnected when the fetch itself throws', async () => {
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('disconnected'))
  })
})
```

**Verify**: `cd frontend && pnpm exec vitest run src/hooks/useConnectionStatus.test.ts`
-> 7 passed.

### Step 5: write `useLiveSweep.test.ts`

Create `frontend/src/hooks/useLiveSweep.test.ts`:

```typescript
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLiveSweep } from './useLiveSweep'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
  startSweep: vi.fn().mockResolvedValue(undefined),
  releaseRelay: vi.fn().mockResolvedValue(undefined),
}))

import { fetchLiveSweep, releaseRelay, startSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'

function mockData(overrides: Partial<LiveSweepState>): LiveSweepState {
  return { points: [], partial: [], active: false, link: 'ok', seq: 0, ...overrides }
}

beforeEach(() => {
  // afterEach resets every mock implementation, so restore the action
  // endpoints' Promise contract before each test. useLiveSweep calls
  // .catch() on both return values.
  vi.mocked(startSweep).mockResolvedValue(undefined)
  vi.mocked(releaseRelay).mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('useLiveSweep', () => {
  it('starts with empty points/partial and inactive', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    expect(result.current.points).toEqual([])
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(false)
  })

  it('draws partial points live while a sweep is active', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(
      mockData({ active: true, partial: [{ v: 10, i: 0.5 }] }),
    )
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }]))
    expect(result.current.active).toBe(true)
    expect(result.current.points).toEqual([])
  })

  it('adopts points and clears partial once a sweep completes', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(
      mockData({ active: false, seq: 1, points: [{ v: 20, i: 0.1 }] }),
    )
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(result.current.points).toEqual([{ v: 20, i: 0.1 }]))
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(false)
  })

  it(
    'does not re-apply points on a later poll with the same seq',
    async () => {
      vi.mocked(fetchLiveSweep)
        .mockResolvedValueOnce(mockData({ seq: 1, points: [{ v: 1, i: 1 }] }))
        .mockResolvedValue(mockData({ seq: 1, points: [{ v: 2, i: 2 }] }))

      const { result } = renderHook(() => useLiveSweep())
      await waitFor(() => expect(result.current.points).toEqual([{ v: 1, i: 1 }]))

      // One more real poll interval (700ms) elapses with a different
      // payload but the same seq - `points` must not change. This is the
      // one genuinely load-bearing test in this file: the seq gate is
      // exactly what stops a completed sweep from being redrawn on every
      // poll.
      await new Promise((r) => setTimeout(r, 900))
      expect(result.current.points).toEqual([{ v: 1, i: 1 }])
    },
    3000,
  )

  it('start() calls the start-sweep endpoint', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    result.current.start()
    expect(vi.mocked(startSweep)).toHaveBeenCalledTimes(1)
  })

  it('releaseRelay() calls the release-relay endpoint', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    result.current.releaseRelay()
    expect(vi.mocked(releaseRelay)).toHaveBeenCalledTimes(1)
  })

  it('swallows a poll failure without throwing', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(errorSpy).toHaveBeenCalled())
    expect(result.current.active).toBe(false)
    errorSpy.mockRestore()
  })
})
```

**Verify**: `cd frontend && pnpm exec vitest run src/hooks/useLiveSweep.test.ts`
-> 7 passed. This file's "does not re-apply points" test deliberately
waits on a real ~900ms timer (see its comment) - it is expected to be the
slowest test in the suite, not a hang.

### Step 6: full verification

```bash
cd frontend
pnpm test
pnpm build
pnpm lint
```

All exit 0. `pnpm build`'s `tsc -b` step type-checks the two new test
files as part of the same pass as the rest of `src/` (see "Current state")

- a type error in either test file fails the build, not just `pnpm test`.

### Step 7: CI wiring, conditional on plan 025

```bash
ls .github/workflows/frontend.yml 2>/dev/null
```

- **If it exists** (plan 025 already landed): add a `pnpm test` step to
  its `build` job, after `Install (frozen lockfile)` and before `Lint`
  (or after `Lint`, either order is fine - just before `Build`, since a
  broken test is cheaper to report on than a broken build):

  ```yaml
      - name: Test
        run: pnpm test
  ```

- **If it does not exist yet**: do not create `.github/workflows/frontend.yml`
  yourself - that is plan 025's responsibility, and creating a competing
  version here risks conflicting with it. Just mention in your PR
  description that `frontend.yml` (whenever it lands) should include a
  `pnpm test` step, so it doesn't get forgotten.

## Test plan

The 14 new tests (7 per hook) directly exercise every branch of
`statusFromLink` and every branch of `useLiveSweep`'s active/inactive/
seq-gating state machine, plus both action callbacks and the error-
swallowing path. This *is* the test plan - see Steps 4/5 for the full
test code and what each test targets.

## Done criteria

- [ ] `frontend/package.json` has `vitest`, `jsdom`,
      `@testing-library/react`, `@testing-library/dom` as devDependencies
      and a `"test": "vitest run"` script
- [ ] `frontend/pnpm-lock.yaml` is updated and committed
- [ ] `frontend/vitest.config.ts` exists
- [ ] `frontend/src/hooks/useConnectionStatus.test.ts` exists, 7 tests, all
      passing
- [ ] `frontend/src/hooks/useLiveSweep.test.ts` exists, 7 tests, all
      passing
- [ ] `cd frontend && pnpm test` - all pass
- [ ] `cd frontend && pnpm build` - exit 0 (test files type-check cleanly)
- [ ] `cd frontend && pnpm lint` - exit 0
- [ ] `.github/workflows/frontend.yml` has a `pnpm test` step **if and
      only if** that file already existed before this plan ran
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `pnpm add -D vitest jsdom @testing-library/react @testing-library/dom`
  reports a peer-dependency conflict with this project's React version -
  do not force past it with `--force` or a version override; report the
  exact conflict.
- Either hook's code differs from what's quoted in "Current state" (per
  the drift check) - re-derive the test assertions against the live logic
  rather than forcing these exact expectations onto changed code.
- Any new test is flaky (passes/fails inconsistently across repeated runs)
  - the "does not re-apply points" test's real-time wait is the most
  likely source; if it proves flaky in practice, report it rather than
  silently increasing the wait until it passes.

## Maintenance notes

- Plan 033 (shared `usePolling` hook, dedup'd from both hooks' near-
  identical `useEffect` scaffold) should be executed after this plan, not
  before - these tests are exactly the safety net that refactor wants.
- If a future hook or component genuinely needs DOM-node assertions
  (rendering, not just state), add `@testing-library/jest-dom` and a
  `setupFiles` entry in `vitest.config.ts` at that point - not preemptively
  here.
