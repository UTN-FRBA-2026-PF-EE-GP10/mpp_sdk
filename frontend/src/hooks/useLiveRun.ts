import { useCallback, useEffect, useRef, useState } from 'react'
import { usePolling } from './usePolling'
import { fetchLiveRun, startRun, stopRun } from '@/lib/api'
import type { StartRunInput } from '@/lib/api'
import type { LiveRunState } from '@/lib/runs'

// Fast enough that the operating point visibly moves as the algorithm
// steps, without polling a Pi-hosted page harder than GET /api/data's own
// 700ms cadence (useLiveSweep) needs - a closed-loop run has no bulk-dump
// handshake to protect the way a sweep's request_sweep() does.
const POLL_MS = 400

/** Local view of the run this session has started or adopted. A run
 * already in progress on the server is adopted on mount (see the
 * mount-sync effect in `useLiveRun` below), so this session always has a
 * working Stop for it - but a previous session's already-*finished* run
 * is not: a page opened while the server's last-known state is a run that
 * is merely done must not read as "a run just completed" the moment this
 * hook mounts. `phase` only ever advances forward (idle -> live -> done);
 * `reset()` is the one way back to idle, for "start another run". */
export type RunPhase = 'idle' | 'live' | 'done'

export interface UseLiveRun {
  phase: RunPhase
  /** The latest poll result - null until the first one lands after a
   * successful start, even though `phase` is already 'live' by then. */
  live: LiveRunState | null
  starting: boolean
  startError: string | null
  stopping: boolean
  stopError: string | null
  start: (input: StartRunInput) => Promise<void>
  stop: () => Promise<void>
  /** Back to 'idle' - only meaningful once `phase` is 'done'. */
  reset: () => void
}

export interface UseLiveRunOptions {
  /** Called with the error of a start the server refused. Returns the text
   * to show as `startError` instead of the error's own message, or nothing
   * to keep it. */
  onStartError?: (e: unknown) => string | void
}

export function useLiveRun(options: UseLiveRunOptions = {}): UseLiveRun {
  // Read through a ref so `start` keeps one identity however the caller
  // writes the callback.
  const onStartError = useRef(options.onStartError)
  useEffect(() => {
    onStartError.current = options.onStartError
  })
  const [phase, setPhase] = useState<RunPhase>('idle')
  const [live, setLive] = useState<LiveRunState | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const [stopError, setStopError] = useState<string | null>(null)
  // Set synchronously the instant this session calls start() - guards the
  // mount-sync effect below against clobbering a run this tab just kicked
  // off with its own stale response, which can only describe the state
  // from before that call ever happened.
  const startedRef = useRef(false)

  const handleData = useCallback((data: LiveRunState) => {
    setLive(data)
    // Polling is only ever enabled while phase is 'live' (see usePolling's
    // `enabled` below), so a "done" snapshot here always means a run this
    // hook itself started (or adopted on mount, below) just finished -
    // never a stale previous run.
    if (data.status === 'done') setPhase('done')
  }, [])

  const handleError = useCallback((e: unknown) => {
    console.error('polling /api/runs/live failed', e)
  }, [])

  usePolling(fetchLiveRun, handleData, handleError, POLL_MS, phase === 'live')

  // The server is the source of truth for what is actually driving the
  // converter, not this hook's own state - a run started from an earlier
  // mount of this component (a tab switch, or a page reload) keeps
  // running server-side with nothing here to show it, leaving no UI path
  // to stop it. Sync once on mount and adopt an already-running run
  // straight into the live/monitoring state with a working Stop, instead
  // of defaulting to idle and showing the setup form over a run that
  // never stopped (see RunPane).
  useEffect(() => {
    let cancelled = false
    async function sync() {
      try {
        const data = await fetchLiveRun()
        // A run this session already started takes precedence - it can
        // only describe state from before that call, so it must never
        // override it. An idle or already-finished run needs no
        // adoption: there is nothing to stop, and treating a stale
        // finished run as newly completed would be misleading (see
        // RunPhase above).
        if (cancelled || startedRef.current || data?.status !== 'running') return
        setLive(data)
        setPhase('live')
      } catch (e) {
        if (!cancelled) console.error('failed to sync live run state on mount', e)
      }
    }
    sync()
    return () => {
      cancelled = true
    }
    // Deliberately runs once, on mount only - not on every phase change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const start = useCallback(async (input: StartRunInput) => {
    startedRef.current = true
    setStarting(true)
    setStartError(null)
    try {
      await startRun(input)
      // The server accepts a start synchronously (_LiveRunCache.try_start
      // claims the slot before responding) - by the time this resolves,
      // GET /api/runs/live already reports "running", so there is nothing
      // to wait for before switching phase.
      setLive(null)
      setPhase('live')
    } catch (e) {
      const replacement = onStartError.current?.(e)
      setStartError(replacement ?? (e instanceof Error ? e.message : String(e)))
    } finally {
      setStarting(false)
    }
  }, [])

  const stop = useCallback(async () => {
    setStopping(true)
    setStopError(null)
    try {
      await stopRun()
    } catch (e) {
      setStopError(e instanceof Error ? e.message : String(e))
    } finally {
      setStopping(false)
    }
  }, [])

  const reset = useCallback(() => {
    setPhase('idle')
    setLive(null)
    setStartError(null)
    setStopError(null)
  }, [])

  return { phase, live, starting, startError, stopping, stopError, start, stop, reset }
}
