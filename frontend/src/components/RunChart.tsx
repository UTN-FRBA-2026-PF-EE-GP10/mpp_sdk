import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import {
  ivChartOptions,
  markerRingColor,
  MPP_COLOR,
  MPP_TH_DRAW_ORDER,
  mppThColor,
  OPERATING_POINT_DRAW_ORDER,
  referenceColor,
  REFERENCE_DRAW_ORDER,
  TRAIL_COLOR,
  TRAIL_DRAW_ORDER,
} from '@/lib/chartConfig'
import { mppPoint } from '@/lib/curveMath'
import { useTheme } from '@/lib/theme'
import { useUnits } from '@/lib/units'
import type { RunSample } from '@/lib/runs'
import type { CurvePoint } from '@/types'

/**
 * The run player's chart: a captured I(V)/P(V) curve drawn faded and
 * static as ground truth, the algorithm's own trajectory drawn as a
 * trail on top of it, and the current operating point marked prominently
 * over both - so the question "did it find the peak, and how did it get
 * there" reads directly off the picture. `referencePoints` is empty when
 * the run has no usable curve_ref; the caller is responsible for saying
 * so elsewhere in the UI (see referenceCurveMessage in lib/runPlayback.ts).
 *
 * MPP_th is the reference curve's maximum-power point (`mppPoint`, the
 * same rule the curve panes use for their MPP), marked on both reference
 * traces: the peak the algorithm should reach.
 */
export function RunChart({
  referencePoints,
  trail,
  current,
}: {
  referencePoints: CurvePoint[]
  trail: RunSample[]
  current: RunSample | null
}) {
  const { factor, currentLabel, powerLabel } = useUnits()
  const { resolvedDark } = useTheme()
  // Also drives the caption below the chart - the legend labels
  // ("MPP_th (I)"/"MPP_th (P)") are the first place a newcomer meets the
  // symbol, in both the live run view and the player, so this is where it
  // gets explained rather than in RunReadouts, which not every screen
  // showing this chart renders.
  const mppThPoint = referencePoints.length > 0 ? mppPoint(referencePoints) : null

  const data = useMemo(() => {
    const datasets = []
    if (referencePoints.length > 0) {
      // Muted neutral, not a categorical series colour - this is
      // background context, not one of the three validated data series
      // (see lib/chartConfig.ts).
      const reference = referenceColor(resolvedDark)
      datasets.push(
        {
          label: 'Reference I(V)',
          data: referencePoints.map((p) => ({ x: p.v, y: p.i * factor })),
          borderColor: reference,
          backgroundColor: reference,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'y',
          order: REFERENCE_DRAW_ORDER,
        },
        {
          label: 'Reference P(V)',
          data: referencePoints.map((p) => ({ x: p.v, y: p.v * p.i * factor })),
          borderColor: reference,
          backgroundColor: reference,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'p',
          order: REFERENCE_DRAW_ORDER,
        },
      )
      const mppTh = mppThPoint
      if (mppTh) {
        const marker = {
          showLine: false,
          borderColor: markerRingColor(resolvedDark),
          backgroundColor: mppThColor(resolvedDark),
          borderWidth: 2,
          pointStyle: 'rectRot' as const,
          pointRadius: 7,
          pointHoverRadius: 9,
          order: MPP_TH_DRAW_ORDER,
        }
        datasets.push(
          {
            ...marker,
            label: 'MPP_th (I)',
            data: [{ x: mppTh.v, y: mppTh.i * factor }],
            yAxisID: 'y',
          },
          {
            ...marker,
            label: 'MPP_th (P)',
            data: [{ x: mppTh.v, y: mppTh.v * mppTh.i * factor }],
            yAxisID: 'p',
          },
        )
      }
    }
    datasets.push(
      {
        label: 'Trail (I)',
        data: trail.map((s) => ({ x: s.v, y: s.i * factor })),
        borderColor: TRAIL_COLOR,
        backgroundColor: TRAIL_COLOR,
        pointRadius: 0,
        borderWidth: 2,
        yAxisID: 'y',
        order: TRAIL_DRAW_ORDER,
      },
      {
        label: 'Trail (P)',
        data: trail.map((s) => ({ x: s.v, y: s.v * s.i * factor })),
        borderColor: TRAIL_COLOR,
        backgroundColor: TRAIL_COLOR,
        pointRadius: 0,
        borderWidth: 2,
        yAxisID: 'p',
        order: TRAIL_DRAW_ORDER,
      },
      {
        label: 'Operating point',
        // Marked on the P(V) trace, same reasoning as CurveChart's MPP
        // marker: power is what "found the peak" means. Full-intensity
        // MPP_COLOR, not the trail's faded version of it - the current
        // point is live, the trail is its history.
        data: current ? [{ x: current.v, y: current.v * current.i * factor }] : [],
        showLine: false,
        borderColor: markerRingColor(resolvedDark),
        backgroundColor: MPP_COLOR,
        borderWidth: 2,
        pointStyle: 'circle',
        pointRadius: 7,
        pointHoverRadius: 9,
        yAxisID: 'p',
        order: OPERATING_POINT_DRAW_ORDER,
      },
    )
    return { datasets }
  }, [referencePoints, trail, current, factor, resolvedDark, mppThPoint])

  const options = useMemo(
    () => ivChartOptions(currentLabel, powerLabel, resolvedDark),
    [currentLabel, powerLabel, resolvedDark],
  )

  return (
    <div>
      <div className="h-80 w-full">
        <Line data={data} options={options} />
      </div>
      {mppThPoint && (
        <p className="mt-1 text-center text-xs text-muted-foreground">
          MPP_th: the theoretical maximum power, the peak of the reference curve.
        </p>
      )}
    </div>
  )
}
