import { useEffect, useRef } from 'react'

/**
 * Poll `fetcher` on a fixed interval for as long as the calling component
 * is mounted - the scaffold shared by `useLiveSweep` and
 * `useConnectionStatus` (both poll `GET /api/data`, at different
 * intervals, doing different things with the result).
 *
 * `fetcher`/`onSuccess`/`onError` are read through refs, updated every
 * render, so the polling loop always calls the latest closures without
 * needing them in the effect's own dependency array - putting them there
 * directly would restart the interval on every render whenever a caller
 * passes a fresh inline function (the common case), which would prevent
 * polling from ever settling into a steady cadence. `intervalMs` is
 * assumed stable (a literal constant at each call site) and *is* a real
 * effect dependency - if it changes at runtime, the interval restarts,
 * which is the correct behavior for a genuinely changed poll rate.
 *
 * `onSuccess`/`onError` are only called while the component is still
 * mounted - a response or rejection that lands after unmount is silently
 * dropped, never applied to state.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  onSuccess: (data: T) => void,
  onError: (error: unknown) => void,
  intervalMs: number,
): void {
  const fetcherRef = useRef(fetcher)
  const onSuccessRef = useRef(onSuccess)
  const onErrorRef = useRef(onError)
  fetcherRef.current = fetcher
  onSuccessRef.current = onSuccess
  onErrorRef.current = onError

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function tick() {
      try {
        const data = await fetcherRef.current()
        if (!cancelled) onSuccessRef.current(data)
      } catch (e) {
        if (!cancelled) onErrorRef.current(e)
      } finally {
        if (!cancelled) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // fetcher/onSuccess/onError are intentionally read via refs, not
    // listed here - see this function's docstring.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs])
}
