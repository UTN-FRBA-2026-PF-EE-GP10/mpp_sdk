import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js'
import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import type { CurvePoint } from '@/types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

const ACCENT = '#f97316' // orange - current, matches the curve tracer's existing theme
const POWER = '#ef4444' // red - power

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
  const shown = partial.length > 0 ? partial : points

  const data = useMemo(
    () => ({
      datasets: [
        {
          label: 'I(V)',
          data: shown.map((p) => ({ x: p.v, y: p.i * 1000 })),
          borderColor: ACCENT,
          backgroundColor: ACCENT,
          pointRadius: 4,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'y',
        },
        {
          label: 'P(V)',
          data: shown.map((p) => ({ x: p.v, y: p.v * p.i * 1000 })),
          borderColor: POWER,
          backgroundColor: POWER,
          pointRadius: 2,
          borderWidth: 2,
          tension: 0.15,
          yAxisID: 'p',
        },
      ],
    }),
    [shown],
  )

  // Memoised: a fresh options object every render makes chart.js rebuild
  // its scales on each poll tick.
  const options = useMemo<ChartOptions<'line'>>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      scales: {
        x: {
          type: 'linear',
          min: 0,
          title: { display: true, text: 'Voltage [V]' },
        },
        y: {
          type: 'linear',
          position: 'left',
          min: 0,
          title: { display: true, text: 'Current [mA]' },
        },
        p: {
          type: 'linear',
          position: 'right',
          min: 0,
          title: { display: true, text: 'Power [mW]' },
          grid: { drawOnChartArea: false },
        },
      },
      plugins: {
        legend: { display: true },
      },
    }),
    [],
  )

  return (
    <div className="h-72 w-full">
      <Line data={data} options={options} />
    </div>
  )
}
