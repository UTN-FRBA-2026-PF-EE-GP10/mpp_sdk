import { useCallback, useRef, useState } from 'react'
import {
  fetchLiveSweep,
  releaseRelay as releaseRelayRequest,
  startDemoSweep as startDemoSweepRequest,
  startSweep as startSweepRequest,
} from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'
import type { CurvePoint } from '@/types'
import { usePolling } from './usePolling'

const POLL_MS = 700

// Shared so `setPartial(EMPTY)` on a poll that changed nothing is a
// no-op: React bails out on Object.is, and a fresh `[]` every tick would
// re-render the page (and re-feed chart.js) 1.4 times a second forever.
const EMPTY: CurvePoint[] = []

/**
 * Polls GET /api/data on a timer. While `active`, `partial` is drawn
 * live, redrawn every tick - it has no seq of its own, and waiting for
 * one would show nothing move. A completed sweep arrives in `points`,
 * gated on the server's `seq` counter so it is not re-applied on every
 * poll.
 *
 * `partial` is deliberately *not* cleared the moment `active` goes
 * false. The firmware reports the sweep finished before the server has
 * fetched the bulk result, and in that gap `points` still holds the
 * previous sweep - clearing here made the chart snap back to the old
 * curve for a poll or two before the new one landed, which read as a
 * flicker. Instead the live trace stays on screen until the completed
 * curve that supersedes it arrives.
 *
 * `enabled` (default true) stops polling `/api/data` altogether - passed
 * `false` in client demo mode, where CurveWorkbench uses useDemoCapture
 * instead and this hook must not reach the network at all.
 */
export function useLiveSweep(enabled = true) {
  const [partial, setPartial] = useState<CurvePoint[]>(EMPTY)
  const [points, setPoints] = useState<CurvePoint[]>(EMPTY)
  const [active, setActive] = useState(false)
  const [commandError, setCommandError] = useState<string | null>(null)
  // A request the server refused outright (e.g. 409) never reaches the
  // command queue, so the polled `commandError` cannot report it.
  const [actionError, setActionError] = useState<string | null>(null)
  const [demoSource, setDemoSource] = useState(false)
  const lastSeq = useRef(-1)

  const handleData = (data: LiveSweepState) => {
    setActive(data.active)
    setCommandError(data.commandError)
    setDemoSource(data.demoSource)
    if (data.seq !== lastSeq.current) {
      // A completed sweep landed: it replaces the live trace outright.
      setPoints(data.points)
      lastSeq.current = data.seq
      setPartial(EMPTY)
    } else if (data.active) {
      setPartial(data.partial)
    }
  }

  const handleError = (e: unknown) => {
    console.error('polling /api/data failed', e)
  }

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS, enabled)

  const send = useCallback((label: string, request: () => Promise<unknown>) => {
    setActionError(null)
    request().catch((e) =>
      setActionError(`${label} failed: ${e instanceof Error ? e.message : String(e)}`),
    )
  }, [])

  const start = useCallback(() => send('start-sweep', startSweepRequest), [send])

  const releaseRelay = useCallback(() => send('release-relay', releaseRelayRequest), [send])

  const startDemo = useCallback(
    (bright: boolean) => send('start-demo-sweep', () => startDemoSweepRequest(bright)),
    [send],
  )

  return {
    partial,
    points,
    active,
    commandError: actionError ?? commandError,
    demoSource,
    start,
    startDemo,
    releaseRelay,
  }
}
