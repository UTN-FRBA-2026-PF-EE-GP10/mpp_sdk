import { useCallback, useEffect, useRef, useState } from 'react'
import { DEMO_CURVE_BRIGHT, DEMO_CURVE_DIM } from '@/lib/demoFixtures'
import type { CurvePoint } from '@/types'

// Matches useLiveSweep's own real-world pace (see LiveChart/CurveWorkbench)
// so a replayed demo sweep looks like a real one animating in, not a
// paste.
const STEP_MS = 250

export interface DemoCaptureState {
  partial: CurvePoint[]
  points: CurvePoint[]
  active: boolean
  commandError: string | null
  demoSource: boolean
  start: () => void
  startDemo: (bright: boolean) => void
  releaseRelay: () => void
}

/**
 * Stands in for useLiveSweep while client demo mode is on: replays one of
 * the two bundled golden curves into the capture pane point by point, at
 * roughly a real sweep's pace, instead of polling a board that isn't
 * there - see CurveWorkbench, which picks this hook or useLiveSweep based
 * on `demo`.
 *
 * `start` (Start Measurement) and `releaseRelay` have no local equivalent
 * - they talk to real hardware, full stop - so they're deliberately inert
 * here. The buttons that call them also stay disabled in the UI; these
 * are a second, defense-in-depth guarantee that clicking one (a stray
 * event handler, a future refactor) can't reach anything.
 */
export function useDemoCapture(): DemoCaptureState {
  const [partial, setPartial] = useState<CurvePoint[]>([])
  const [points, setPoints] = useState<CurvePoint[]>([])
  const [active, setActive] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(
    () => () => {
      if (timerRef.current !== null) clearInterval(timerRef.current)
    },
    [],
  )

  const startDemo = useCallback((bright: boolean) => {
    const curvePoints = bright ? DEMO_CURVE_BRIGHT.points : DEMO_CURVE_DIM.points
    if (timerRef.current !== null) clearInterval(timerRef.current)

    setPoints([])
    setPartial([])
    setActive(true)

    let index = 0
    timerRef.current = setInterval(() => {
      index += 1
      setPartial(curvePoints.slice(0, index))
      if (index >= curvePoints.length) {
        if (timerRef.current !== null) clearInterval(timerRef.current)
        timerRef.current = null
        setPoints(curvePoints)
        setPartial([])
        setActive(false)
      }
    }, STEP_MS)
  }, [])

  return {
    partial,
    points,
    active,
    commandError: null,
    // Always true: everything this hook ever shows is a replay, never a
    // measurement - see ProvenanceBadge/CurveWorkbench's "replayed from
    // firmware, not measured" caption, which reads this flag.
    demoSource: true,
    start: () => {},
    startDemo,
    releaseRelay: () => {},
  }
}
