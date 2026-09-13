import { useState } from 'react'
import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'
import type { ConnectionStatus } from '@/types'
import { usePolling } from './usePolling'

const POLL_MS = 2000

function statusFromLink(link: string): ConnectionStatus {
  if (link === 'no data yet') return 'connecting'
  if (link.startsWith('error')) return 'disconnected'
  if (link === 'demo') return 'demo' // curve_tracer_server.py --demo - simulated, no board
  return 'connected' // "ok" or "waiting for sweep" - the Pi is talking to the Pico either way
}

export interface LinkState {
  /** Derived from GET /api/data's `link` field, not just HTTP
   * reachability: the server can be up while the Pico link itself is
   * down. */
  status: ConnectionStatus
  /** True while the curve on screen was replayed from the firmware's
   * stored curves. Distinct from `status === 'demo'`, which means the
   * *server* is faking the source and no board is involved at all - a
   * firmware replay is a real board over a real SPI link. */
  demoSource: boolean
}

/** Polls the link once every `POLL_MS`. Shared by the header indicators;
 * `useLiveSweep` polls the same route faster for the curve itself. */
export function useConnectionStatus(): LinkState {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [demoSource, setDemoSource] = useState(false)

  const handleData = (data: LiveSweepState) => {
    setStatus(statusFromLink(data.link))
    setDemoSource(data.demoSource)
  }
  const handleError = (_error: unknown) => setStatus('disconnected')

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS)

  return { status, demoSource }
}
