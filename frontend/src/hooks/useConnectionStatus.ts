import { useEffect, useState } from 'react'
import type { ConnectionStatus } from '@/types'

/**
 * Stands in for a real link check (e.g. polling `/data`'s `link` field)
 * until the frontend talks to a backend. Starts "connecting" then settles
 * "connected" - the shape a real poll-based check would have.
 */
export function useConnectionStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')

  useEffect(() => {
    const id = setTimeout(() => setStatus('connected'), 700)
    return () => clearTimeout(id)
  }, [])

  return status
}
