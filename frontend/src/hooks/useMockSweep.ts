import { useCallback, useEffect, useRef, useState } from 'react'
import { generateMockPoints } from '@/lib/mockCurves'
import type { CurvePoint } from '@/types'

const POINT_INTERVAL_MS = 220 // approximates the real per-point settle time on hardware

/**
 * Stands in for the real streaming protocol (Pico -> Pi, one point at a
 * time) until that firmware/SPI work lands. `partial` grows one point per
 * tick while `active`; `points` is only set once the "sweep" completes, the
 * same split the real data endpoint is designed to expose.
 */
export function useMockSweep(voc = 21.2, isc = 0.2) {
  const [partial, setPartial] = useState<CurvePoint[]>([])
  const [points, setPoints] = useState<CurvePoint[]>([])
  const [active, setActive] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setActive(false)
  }, [])

  const start = useCallback(() => {
    stop()
    const target = generateMockPoints(voc, isc)
    setPartial([])
    setActive(true)
    let idx = 0
    timerRef.current = setInterval(() => {
      const next = target[idx]
      idx += 1
      setPartial((prev) => [...prev, next])
      if (idx >= target.length) {
        setPoints(target)
        stop()
      }
    }, POINT_INTERVAL_MS)
  }, [voc, isc, stop])

  useEffect(() => stop, [stop])

  return { partial, points, active, start }
}
