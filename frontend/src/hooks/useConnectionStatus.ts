import { useEffect, useState } from 'react'
import { fetchLiveSweep } from '@/lib/api'
import type { ConnectionStatus } from '@/types'

const POLL_MS = 2000

function statusFromLink(link: string): ConnectionStatus {
  if (link === 'no data yet') return 'connecting'
  if (link.startsWith('error')) return 'disconnected'
  if (link === 'demo') return 'demo' // curve_tracer_server.py --demo - simulated, no board
  return 'connected' // "ok" or "waiting for sweep" - the Pi is talking to the Pico either way
}

/** Derived from GET /api/data's `link` field, not just HTTP reachability -
 * the server can be up while the Pico link itself is down. */
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
