import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunChart } from './RunChart'
import { RunReadouts } from './RunReadouts'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { CurvePoint } from '@/types'

// chart.js needs a real canvas; the datasets RunChart builds are what
// matter here, so expose them on the DOM instead.
vi.mock('react-chartjs-2', () => ({
  Line: ({ data }: { data: { datasets: { label: string; data: unknown[] }[] } }) => (
    <div data-testid="run-chart" data-datasets={JSON.stringify(data.datasets)} />
  ),
}))

afterEach(() => cleanup())

function renderInApp(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function datasets(): { label: string; data: { x: number; y: number }[]; yAxisID: string }[] {
  return JSON.parse(screen.getByTestId('run-chart').getAttribute('data-datasets') ?? '[]')
}

// Peak power at 14 V x 0.5 A = 7 W, not at the highest current or voltage.
const REFERENCE: CurvePoint[] = [
  { v: 0, i: 0.6 },
  { v: 10, i: 0.58 },
  { v: 14, i: 0.5 },
  { v: 17, i: 0.2 },
  { v: 19, i: 0 },
]

describe('RunChart MPP_th', () => {
  it('marks the reference curve peak on both the I(V) and the P(V) trace', () => {
    renderInApp(<RunChart referencePoints={REFERENCE} trail={[]} current={null} />)
    const byLabel = Object.fromEntries(datasets().map((d) => [d.label, d]))

    // The page's default units are mA and mW, so y is scaled by 1000.
    expect(byLabel['MPP_th (I)'].data).toEqual([{ x: 14, y: 500 }])
    expect(byLabel['MPP_th (I)'].yAxisID).toBe('y')
    expect(byLabel['MPP_th (P)'].data).toEqual([{ x: 14, y: 7000 }])
    expect(byLabel['MPP_th (P)'].yAxisID).toBe('p')
  })

  it('draws no MPP_th when the run has no reference curve', () => {
    renderInApp(<RunChart referencePoints={[]} trail={[]} current={null} />)
    expect(datasets().some((d) => d.label.startsWith('MPP_th'))).toBe(false)
  })

  it('explains MPP_th under the chart, where a newcomer meets the symbol first', () => {
    renderInApp(<RunChart referencePoints={REFERENCE} trail={[]} current={null} />)
    expect(screen.getByText(/MPP_th: the theoretical maximum power/)).toBeTruthy()
  })

  it('leaves out the MPP_th explanation when there is no reference curve to peak', () => {
    renderInApp(<RunChart referencePoints={[]} trail={[]} current={null} />)
    expect(screen.queryByText(/MPP_th: the theoretical maximum power/)).toBeNull()
  })
})

describe('RunReadouts MPP_th', () => {
  it('shows MPP_th and the current power as a percentage of it', () => {
    renderInApp(
      <RunReadouts sample={{ t: 1, v: 13, i: 0.5, d: 0.4 }} mppTh={{ v: 14, i: 0.5 }} />,
    )
    // 13 V x 0.5 A = 6.5 W against the 7 W peak.
    expect(screen.getByText('P / MPP_th')).toBeTruthy()
    expect(screen.getByText('92.9 %')).toBeTruthy()
    expect(screen.getByText(/MPP_th \(peak of the reference curve\): 14\.00 V/)).toBeTruthy()
  })

  it('leaves MPP_th out when there is no reference curve', () => {
    renderInApp(<RunReadouts sample={{ t: 1, v: 13, i: 0.5, d: 0.4 }} />)
    expect(screen.queryByText('P / MPP_th')).toBeNull()
  })
})
