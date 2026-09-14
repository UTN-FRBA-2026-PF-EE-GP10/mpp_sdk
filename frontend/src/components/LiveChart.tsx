import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import { CURRENT_COLOR, ivChartOptions, POWER_COLOR } from '@/lib/chartConfig'
import { useTheme } from '@/lib/theme'
import { useUnits } from '@/lib/units'
import type { CurvePoint } from '@/types'

/**
 * Renders whichever of `partial`/`points` is authoritative right now.
 *
 * The live trace wins whenever there is one. `useLiveSweep` only clears
 * `partial` when the completed sweep that supersedes it arrives, so this
 * rule never shows a stale curve: during a sweep it draws the trace, and
 * the instant the real result lands it draws that instead. Keying off
 * `active` here instead put the previous sweep's curve back on screen for
 * the poll or two between the firmware finishing and the server fetching
 * its result, which read as a flicker.
 */
export function LiveChart({ partial, points }: { partial: CurvePoint[]; points: CurvePoint[] }) {
  const { factor, currentLabel, powerLabel } = useUnits()
  const { resolvedDark } = useTheme()
  const shown = partial.length > 0 ? partial : points

  const data = useMemo(
    () => ({
      datasets: [
        {
          label: 'I(V)',
          data: shown.map((p) => ({ x: p.v, y: p.i * factor })),
          borderColor: CURRENT_COLOR,
          backgroundColor: CURRENT_COLOR,
          pointRadius: 4,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'y',
        },
        {
          label: 'P(V)',
          data: shown.map((p) => ({ x: p.v, y: p.v * p.i * factor })),
          borderColor: POWER_COLOR,
          backgroundColor: POWER_COLOR,
          pointRadius: 4,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'p',
        },
      ],
    }),
    [shown, factor],
  )

  // Memoised: a fresh options object every render makes chart.js rebuild
  // its scales on each poll tick.
  const options = useMemo(
    () => ivChartOptions(currentLabel, powerLabel, resolvedDark),
    [currentLabel, powerLabel, resolvedDark],
  )

  return (
    <div className="h-72 w-full">
      <Line data={data} options={options} />
    </div>
  )
}
