import { useCallback, useEffect, useState } from 'react'
import { fetchRun } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import type { RunDetail } from '@/lib/runs'

/** How many GET /api/runs/{id} may be in flight at once. Each one carries a
 * run's full samples, so a session with dozens of runs must not ask for all
 * of them together. */
export const MAX_CONCURRENT_RUN_FETCHES = 4

interface LoaderEvents {
  loaded: (id: string, detail: RunDetail) => void
  gone: (id: string) => void
  failed: (id: string) => void
}

/**
 * Fetches run details one id at a time, at most MAX_CONCURRENT_RUN_FETCHES
 * together, and never asks for the same id twice unless `retry` is called.
 *
 * Plain TypeScript, with no React in it, on purpose: what a change in the
 * wanted list does to fetches that are already in flight is the thing this
 * exists to get right. An in-flight fetch is never cancelled because the
 * list changed - its result is still wanted, or harmless - only `dispose`
 * (unmount) drops results.
 */
export class RunDetailLoader {
  // Every id ever requested: queued, in flight, or settled. Settled ids
  // stay here, which is what stops a re-render from fetching them again.
  private known = new Set<string>()
  private queue: string[] = []
  private active = 0
  private wanted = new Set<string>()
  private live = true
  private readonly events: LoaderEvents

  constructor(events: LoaderEvents) {
    this.events = events
  }

  /** Re-arms a loader whose effect was cleaned up and set up again
   * (React StrictMode does this on mount). */
  attach(): void {
    this.live = true
  }

  /** Drops every later result. */
  dispose(): void {
    this.live = false
  }

  /** Makes `ids` the wanted set: any not requested yet is queued. */
  want(ids: readonly string[]): void {
    this.wanted = new Set(ids)
    for (const id of ids) {
      if (this.known.has(id)) continue
      this.known.add(id)
      this.queue.push(id)
    }
    this.pump()
  }

  /** Forgets that `ids` were requested, so the next `want` asks again. */
  retry(ids: readonly string[]): void {
    for (const id of ids) this.known.delete(id)
    this.want([...this.wanted])
  }

  private pump(): void {
    while (this.active < MAX_CONCURRENT_RUN_FETCHES && this.queue.length > 0) {
      const id = this.queue.shift() as string
      if (!this.wanted.has(id)) {
        // Wanted no longer (the run was deleted, or linked runs changed):
        // forget it so a later want fetches it after all.
        this.known.delete(id)
        continue
      }
      this.active += 1
      fetchRun(id)
        .then((detail) => {
          if (this.live) this.events.loaded(id, detail)
        })
        .catch((e: unknown) => {
          if (!this.live) return
          // Only a 404 says the run is really gone. Anything else - a 500,
          // a dropped connection - says nothing about the run, so it must
          // not be reported as deleted.
          if (e instanceof ApiError && e.status === 404) this.events.gone(id)
          else this.events.failed(id)
        })
        .finally(() => {
          this.active -= 1
          this.pump()
        })
    }
  }
}

export interface UseRunDetails {
  /** Fetched details, by run id. Never evicted: a run deleted later stays
   * here, so callers decide what exists from their own current run list. */
  details: Record<string, RunDetail>
  /** Ids the server answered 404 for - really gone. */
  gone: ReadonlySet<string>
  /** Ids that could not be fetched for any other reason. `retry` asks again. */
  failed: ReadonlySet<string>
  /** Some wanted id is neither loaded, gone, nor failed - a fetch is still
   * queued or in flight. */
  pending: boolean
  retry: () => void
}

interface DetailsState {
  details: Record<string, RunDetail>
  gone: ReadonlySet<string>
  failed: ReadonlySet<string>
}

const EMPTY: DetailsState = { details: {}, gone: new Set(), failed: new Set() }

function withId(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  return new Set(set).add(id)
}

/** Loads full detail for `wantedIds` as they appear. `enabled` false loads
 * nothing (demo mode). Every id costs one request however often the list
 * changes; see RunDetailLoader. */
export function useRunDetails(wantedIds: readonly string[], enabled: boolean): UseRunDetails {
  const [state, setState] = useState<DetailsState>(EMPTY)
  const [loader] = useState(
    () =>
      new RunDetailLoader({
        loaded: (id, detail) =>
          setState((prev) => ({ ...prev, details: { ...prev.details, [id]: detail } })),
        gone: (id) => setState((prev) => ({ ...prev, gone: withId(prev.gone, id) })),
        failed: (id) => setState((prev) => ({ ...prev, failed: withId(prev.failed, id) })),
      }),
  )

  useEffect(() => {
    loader.attach()
    return () => loader.dispose()
  }, [loader])

  // A string key, so a new array with the same ids does not re-run this.
  const key = wantedIds.join('\n')
  useEffect(() => {
    if (!enabled) return
    loader.want(key === '' ? [] : key.split('\n'))
  }, [loader, enabled, key])

  const retry = useCallback(() => {
    const ids = [...state.failed]
    if (ids.length === 0) return
    setState((prev) => ({ ...prev, failed: new Set() }))
    loader.retry(ids)
  }, [loader, state.failed])

  const pending =
    enabled &&
    wantedIds.some((id) => !(id in state.details) && !state.gone.has(id) && !state.failed.has(id))

  return { details: state.details, gone: state.gone, failed: state.failed, pending, retry }
}
