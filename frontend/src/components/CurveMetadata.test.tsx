import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { CurveMetadata } from './CurveMetadata'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { CurveRecord, PanelSetup } from '@/types'

afterEach(cleanup)

function record(panels: PanelSetup[]): CurveRecord {
  return {
    id: '2026-09-19T16-00-00Z-panel-a',
    path: '/data/curves/2026-09-19T16-00-00Z-panel-a.json',
    captured_at: '2026-09-19T16:00:00Z',
    label: 'panel a',
    measurement: 'baseline',
    panels,
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 21.3,
    isc: 0.5,
    p_mpp: 7.2,
    points: [
      { v: 21.3, i: 0 },
      { v: 0, i: 0.5 },
    ],
  }
}

describe('CurveMetadata', () => {
  it('shows "1 panel" for a Single-setup curve', () => {
    render(
      <UnitsProvider>
        <CurveMetadata record={record([{ id: 'A', tilt_deg: 90 }])} />
      </UnitsProvider>,
    )
    expect(screen.getByText('1 panel')).toBeTruthy()
  })

  it('shows "2 panels" for a Full-setup curve', () => {
    render(
      <UnitsProvider>
        <CurveMetadata
          record={record([
            { id: 'A', tilt_deg: 90 },
            { id: 'B', tilt_deg: 45 },
          ])}
        />
      </UnitsProvider>,
    )
    expect(screen.getByText('2 panels')).toBeTruthy()
  })
})
