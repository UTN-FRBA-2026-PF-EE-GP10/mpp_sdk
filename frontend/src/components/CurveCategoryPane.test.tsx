import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { CurveCategoryPane } from './CurveCategoryPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { CurveRecord } from '@/types'

afterEach(cleanup)

// The chart and metadata read the page's unit and theme settings, so
// anything rendering them needs the providers the app root supplies.
function renderPane(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function record(overrides: Partial<CurveRecord> = {}): CurveRecord {
  return {
    id: '2026-09-13T08-00-00Z-both-flat',
    path: '/data/curves/2026-09-13T08-00-00Z-both-flat.json',
    captured_at: '2026-09-13T08:00:00Z',
    label: 'both flat',
    measurement: 'baseline',
    panels: [
      { id: 'A', tilt_deg: 90 },
      { id: 'B', tilt_deg: 90 },
    ],
    notes: '',
    n_points: 3,
    source: 'hardware',
    voc: 21.3,
    isc: 0.215,
    p_mpp: 3.51,
    points: [
      { v: 21.3, i: 0.006 },
      { v: 18.0, i: 0.195 },
      { v: 8.0, i: 0.215 },
    ],
    ...overrides,
  }
}

describe('CurveCategoryPane', () => {
  it('shows the empty state when no curves are saved under this kind - the case data/curves/ starts in', () => {
    renderPane(<CurveCategoryPane kind="dimmed" records={[]} />)
    expect(screen.getByText('Nothing saved yet')).toBeTruthy()
  })

  it('renders one pane per saved curve, with a quiet label for a hardware measurement', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={[record()]} />)
    expect(screen.getByText('both flat')).toBeTruthy()
    expect(screen.getByText('Measured')).toBeTruthy()
  })

  it('marks a non-hardware curve with a loud, unmissable provenance label', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={[record({ source: 'simulated' })]} />)
    expect(screen.getByText('Simulated - not measured')).toBeTruthy()
  })

  it('does not crash rendering a curve with no notes and reflects notes when present', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={[record({ notes: 'clear sky' })]} />)
    expect(screen.getByText('clear sky')).toBeTruthy()
  })

  it('opens the same expanded view on click, with download controls', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={[record()]} />)
    fireEvent.click(screen.getByRole('button', { name: /both flat/ }))
    expect(screen.getByText('Download JSON')).toBeTruthy()
    expect(screen.getByText('Download CSV')).toBeTruthy()
  })
})
