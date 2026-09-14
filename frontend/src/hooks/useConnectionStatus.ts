import { useState } from 'react'
import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'
import type { ConnectionStatus } from '@/types'
import { usePolling } from './usePolling'

const POLL_MS = 2000

// Exported for ConnectionIndicator's one-shot link check in demo mode
// (see its own docstring) - the same mapping, not reimplemented.
export function statusFromLink(link: string): ConnectionStatus {
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
}

/** Polls the link once every `POLL_MS`. Shared by the header indicators;
 * `useLiveSweep` polls the same route faster for the curve itself.
 *
 * `enabled` (default true) stops polling altogether when false - same
 * contract as `useLiveSweep`'s own flag. App.tsx passes `!sandboxEnabled`:
 * demo mode promises no background network activity, and link status
 * there is instead answered by ConnectionIndicator's one-shot check,
 * fired only when the capture-mode menu is opened. */
export function useConnectionStatus(enabled = true): LinkState {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  const handleData = (data: LiveSweepState) => {
    setStatus(statusFromLink(data.link))
  }
  const handleError = (_error: unknown) => setStatus('disconnected')

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS, enabled)

  return { status }
}
