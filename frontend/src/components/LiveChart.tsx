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
 * Renders whichever of `partial`/`points` is authoritative right now: while
 * `active`, points stream in one at a time (mocked today - the real source
 * will be per-point firmware frames as a sweep runs); once a sweep
 * completes, `points` takes over.
 */
export function LiveChart({
  partial,
  points,
  active,
}: {
  partial: CurvePoint[]
  points: CurvePoint[]
  active: boolean
}) {
  const shown = active || points.length === 0 ? partial : points

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

  const options: ChartOptions<'line'> = {
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
  }

  return (
    <div className="h-72 w-full">
      <Line data={data} options={options} />
    </div>
  )
}
