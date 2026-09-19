// Batches ReportView's edits behind a short debounce so fast typing (a
// notes box, a number field) doesn't fire one PATCH per keystroke. A
// discrete action (a status button, a link/unlink) can flush right away
// with `sendNow` instead of waiting out the debounce. Edits landing inside
// the same window merge into one request (mergeReportPatch) rather than
// racing each other or overwriting one another's change.

import { useCallback, useEffect, useRef, useState } from 'react'
import { isEmptyPatch, mergeReportPatch, type ReportPatch, type ReportRecord } from '@/lib/reports'

export type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const DEBOUNCE_MS = 600

export function useDebouncedPatch(
  onPatch: ((patch: ReportPatch) => Promise<ReportRecord>) | undefined,
) {
  const pendingRef = useRef<ReportPatch>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [state, setState] = useState<SaveState>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    [],
  )

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const patch = pendingRef.current
    pendingRef.current = {}
    if (!onPatch || isEmptyPatch(patch)) return
    setState('saving')
    setError(null)
    onPatch(patch)
      .then(() => setState('saved'))
      .catch((e) => {
        setState('error')
        setError(e instanceof Error ? e.message : String(e))
      })
  }, [onPatch])

  /** Queues `patch`, merging with anything already pending, and (re)starts
   * the debounce timer - for edits from typing. */
  const schedule = useCallback(
    (patch: ReportPatch) => {
      pendingRef.current = mergeReportPatch(pendingRef.current, patch)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(flush, DEBOUNCE_MS)
    },
    [flush],
  )

  /** Queues `patch` and sends immediately - for a discrete click (status,
   * link/unlink) that should not wait out the debounce. */
  const sendNow = useCallback(
    (patch: ReportPatch) => {
      pendingRef.current = mergeReportPatch(pendingRef.current, patch)
      flush()
    },
    [flush],
  )

  return { schedule, sendNow, state, error }
}
