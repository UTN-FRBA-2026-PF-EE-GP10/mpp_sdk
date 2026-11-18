import { useCallback, useEffect, useRef, useState } from 'react'
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
  /** True while the tab is hidden: the last status may be old. */
  stale: boolean
  busy: boolean
  message: string | null
  turnOn: (power: number, maxOnS: number) => Promise<void>
  turnOff: () => Promise<void>
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : 'Request failed'
}

// A body without a state string is not a status: never let it reach the UI.
function isStatus(s: unknown): s is LampStatus {
  return !!s && typeof s === 'object' && typeof (s as LampStatus).state === 'string'
}

/** Polls GET /api/dimmer while the page is visible. Never sends a command
 * by itself and never retries one: the server owns the window deadline.
 *
 * Every command bumps a sequence number. A response is applied only if no
 * newer command started since its request began, so a late answer can never
 * show an old state (for example ON after the operator pressed Off). */
export function useLamp(enabled = true): LampHook {
  const [status, setStatus] = useState<LampStatus | null>(null)
  const [receivedAt, setReceivedAt] = useState(() => Date.now())
  const [failures, setFailures] = useState(0)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const seqRef = useRef(0)
  const onAbortRef = useRef<AbortController | null>(null)
  const pollRef = useRef<() => void>(() => {})

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let inFlightSeq = -1

    const schedule = () => {
      clearTimeout(timer)
      if (!cancelled && document.visibilityState !== 'hidden') timer = setTimeout(poll, POLL_MS)
    }
    async function poll() {
      if (cancelled || document.visibilityState === 'hidden') return
      const seq = seqRef.current
      if (inFlightSeq === seq) return
      inFlightSeq = seq
      try {
        const s = await fetchLamp()
        if (cancelled || seq !== seqRef.current) return
        if (!isStatus(s)) throw new Error('bad status')
        setStatus(s)
        setReceivedAt(Date.now())
        setFailures(0)
        setStale(false)
      } catch {
        if (!cancelled && seq === seqRef.current) setFailures((n) => n + 1)
      } finally {
        if (inFlightSeq === seq) inFlightSeq = -1
        schedule()
      }
    }
    pollRef.current = poll
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        clearTimeout(timer)
        setStale(true)
      } else poll()
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
    setStale(false)
  }

  const turnOn = useCallback(async (power: number, maxOnS: number) => {
    const seq = ++seqRef.current
    const ctl = new AbortController()
    onAbortRef.current = ctl
    setBusy(true)
    setMessage(null)
    try {
      const s = await setLamp({ power, max_on_s: maxOnS }, ctl.signal)
      if (seq === seqRef.current && isStatus(s)) apply(s)
    } catch (e) {
      if (seq === seqRef.current) setMessage(errorText(e))
    } finally {
      if (seq === seqRef.current) {
        setBusy(false)
        // The POST body is not trusted as the state: read it back.
        pollRef.current()
      }
    }
  }, [])

  // Not guarded by `busy`: Off must work at any time. It supersedes every
  // older request and cancels an on-request still in flight.
  const turnOff = useCallback(async () => {
    const seq = ++seqRef.current
    onAbortRef.current?.abort()
    onAbortRef.current = null
    setBusy(false)
    setMessage(null)
    try {
      const s = await lampOff()
      if (seq === seqRef.current && isStatus(s)) apply(s)
    } catch (e) {
      if (seq === seqRef.current) setMessage(`Off request failed: ${errorText(e)}`)
    } finally {
      if (seq === seqRef.current) pollRef.current()
    }
  }, [])

  return { status, receivedAt, failures, stale, busy, message, turnOn, turnOff }
}
