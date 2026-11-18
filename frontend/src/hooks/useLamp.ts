import { useCallback, useEffect, useState } from 'react'
import { fetchLamp, lampOff, setLamp, type LampStatus } from '@/lib/api'
import { ApiError } from '@/lib/apiError'

const POLL_MS = 1000
export const UNKNOWN_AFTER_FAILURES = 3

export interface LampHook {
  status: LampStatus | null
  /** When `status` was received, in ms (Date.now), for the countdowns. */
  receivedAt: number
  /** Consecutive failed polls; 0 means the last poll worked. */
  failures: number
  busy: boolean
  message: string | null
  turnOn: (power: number, maxOnS: number) => Promise<void>
  turnOff: () => Promise<void>
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : 'Request failed'
}

/** Polls GET /api/dimmer while the page is visible. Never sends a command
 * by itself and never retries one: the server owns the window deadline. */
export function useLamp(enabled = true): LampHook {
  const [status, setStatus] = useState<LampStatus | null>(null)
  const [receivedAt, setReceivedAt] = useState(() => Date.now())
  const [failures, setFailures] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let inFlight = false

    const schedule = () => {
      clearTimeout(timer)
      if (!cancelled && document.visibilityState !== 'hidden') timer = setTimeout(poll, POLL_MS)
    }
    async function poll() {
      if (cancelled || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      try {
        const s = await fetchLamp()
        if (cancelled) return
        setStatus(s)
        setReceivedAt(Date.now())
        setFailures(0)
      } catch {
        if (!cancelled) setFailures((n) => n + 1)
      } finally {
        inFlight = false
        schedule()
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') clearTimeout(timer)
      else poll()
    }
    document.addEventListener('visibilitychange', onVisibility)
    poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled])

  const apply = (s: LampStatus) => {
    setStatus(s)
    setReceivedAt(Date.now())
    setFailures(0)
  }

  const turnOn = useCallback(async (power: number, maxOnS: number) => {
    setBusy(true)
    setMessage(null)
    try {
      apply(await setLamp({ power, max_on_s: maxOnS }))
    } catch (e) {
      setMessage(errorText(e))
    } finally {
      setBusy(false)
    }
  }, [])

  // Not guarded by `busy`: Off must work at any time.
  const turnOff = useCallback(async () => {
    setMessage(null)
    try {
      apply(await lampOff())
    } catch (e) {
      setMessage(`Off request failed: ${errorText(e)}`)
    }
  }, [])

  return { status, receivedAt, failures, busy, message, turnOn, turnOff }
}
