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

/** Derived from GET /api/data's `link` field, not just HTTP reachability:
 * the server can be up while the Pico link itself is down. */
export function useConnectionStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  const handleData = (data: LiveSweepState) => setStatus(statusFromLink(data.link))
  const handleError = (_error: unknown) => setStatus('disconnected')

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS)

  return status
}
