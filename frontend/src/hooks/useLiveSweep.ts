import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchLiveSweep, releaseRelay as releaseRelayRequest, startSweep as startSweepRequest } from '@/lib/api'
import type { CurvePoint } from '@/types'

const POLL_MS = 700

/**
 * Polls GET /api/data on a timer: while `active`, `partial` is drawn live
 * (redrawn every tick - it has no seq of its own, and waiting for one
 * would show nothing move); once `active` goes false, `points` (the last
 * completed sweep) takes over, gated on the server's `seq` counter so a
 * sweep isn't re-applied on every poll.
 */
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
