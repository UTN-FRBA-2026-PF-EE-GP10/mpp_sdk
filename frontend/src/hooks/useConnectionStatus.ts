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
  /** The raw `link` field itself, e.g. "ok" or "waiting for sweep" - both
   * fold into `status: 'connected'` above, so this is the only place that
   * still tells them apart. Not used for any decision in the app; it
   * exists purely as an unobtrusive debug readout (see
   * ConnectionIndicator's menu). Empty until the first poll lands. */
  link: string
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
  const [state, setState] = useState<LinkState>({ status: 'connecting', link: '' })

  const handleData = (data: LiveSweepState) => {
    // A fresh object every poll would re-render the whole page twice a
    // second, because React compares by identity. Keep the old one when
    // nothing moved.
    setState((s) => {
      const status = statusFromLink(data.link)
      return s.status === status && s.link === data.link ? s : { status, link: data.link }
    })
  }
  // Keeps the last-seen raw link text on a failed poll rather than
  // blanking it - it's a debug readout, and the most recent real value is
  // more useful than nothing while a poll or two is failing.
  const handleError = (_error: unknown) =>
    setState((s) => (s.status === 'disconnected' ? s : { ...s, status: 'disconnected' }))

  usePolling(fetchLiveSweep, handleData, handleError, POLL_MS, enabled)

  return state
}
