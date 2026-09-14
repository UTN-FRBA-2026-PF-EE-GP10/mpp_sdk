import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import {
  CURRENT_COLOR,
  CURRENT_DRAW_ORDER,
  ivChartOptions,
  markerRingColor,
  MPP_COLOR,
  MPP_DRAW_ORDER,
  POWER_COLOR,
  POWER_DRAW_ORDER,
} from '@/lib/chartConfig'
import { mppPoint } from '@/lib/curveMath'
import { useTheme } from '@/lib/theme'
import { useUnits } from '@/lib/units'
import type { CurvePoint } from '@/types'

/**
 * A saved curve's I(V)/P(V) plot, with the maximum-power point marked as
 * its own dataset rather than by an annotation plugin (the frontend has
 * an explicit no-new-dependencies rule; see the frontend README). Static:
 * unlike LiveChart, `points` never changes after mount, since a saved
 * record is not still being swept.
 */
export function CurveChart({
  points,
  heightClassName = 'h-64',
}: {
  points: CurvePoint[]
  heightClassName?: string
}) {
  const { factor, currentLabel, powerLabel } = useUnits()
  const { resolvedDark } = useTheme()
  const mpp = useMemo(() => mppPoint(points), [points])

  const data = useMemo(
    () => ({
      datasets: [
        {
          label: 'I(V)',
          data: points.map((p) => ({ x: p.v, y: p.i * factor })),
          borderColor: CURRENT_COLOR,
          backgroundColor: CURRENT_COLOR,
          pointRadius: 4,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'y',
          order: CURRENT_DRAW_ORDER,
        },
        {
          label: 'P(V)',
          data: points.map((p) => ({ x: p.v, y: p.v * p.i * factor })),
          borderColor: POWER_COLOR,
          backgroundColor: POWER_COLOR,
          pointRadius: 4,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'p',
          order: POWER_DRAW_ORDER,
        },
        {
          label: 'MPP',
          // Marked on the P(V) trace, not I(V): the maximum-power point
          // IS the peak of the power curve, so putting it there shows
          // what it means instead of just where it happens to sit.
          data: mpp ? [{ x: mpp.v, y: mpp.v * mpp.i * factor }] : [],
          showLine: false,
          // Ringed in the surface colour so the marker stays readable on
          // top of the trace, in either theme.
          borderColor: markerRingColor(resolvedDark),
          backgroundColor: MPP_COLOR,
          borderWidth: 2,
          pointStyle: 'circle',
          pointRadius: 7,
          pointHoverRadius: 9,
          yAxisID: 'p',
          order: MPP_DRAW_ORDER,
        },
      ],
    }),
    [points, mpp, factor, resolvedDark],
  )

  const options = useMemo(
    () => ivChartOptions(currentLabel, powerLabel, resolvedDark),
    [currentLabel, powerLabel, resolvedDark],
  )

  return (
    <div className={`${heightClassName} w-full`}>
      <Line data={data} options={options} />
    </div>
  )
}
