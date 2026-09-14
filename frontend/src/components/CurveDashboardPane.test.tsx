import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurveDashboardPane } from './CurveDashboardPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  deleteCurve: vi.fn(),
}))

import { deleteCurve } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

function renderPane(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function renderPaneInSandbox(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
          {ui}
        </CaptureModeContext.Provider>
      </UnitsProvider>
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
      { v: 18.0, i: 0.215 },
      { v: 8.0, i: 0.215 },
    ],
    ...overrides,
  }
}

function baseProps(overrides: Partial<Parameters<typeof CurveDashboardPane>[0]> = {}) {
  return {
    record: record(),
    onOpen: vi.fn(),
    onDeleted: vi.fn(),
    onRemeasure: vi.fn(),
    ...overrides,
  }
}

describe('CurveDashboardPane - opening', () => {
  it('opens the expanded view when the card itself is clicked', () => {
    const props = baseProps()
    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /both flat/ }))
    expect(props.onOpen).toHaveBeenCalled()
  })

  it('does not open the expanded view when an action button is clicked', () => {
    const props = baseProps()
    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Delete this curve'))
    expect(props.onOpen).not.toHaveBeenCalled()
  })

  it('does not open the expanded view when the save (download) trigger is clicked', () => {
    const props = baseProps()
    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Save (download)'))
    expect(props.onOpen).not.toHaveBeenCalled()
  })
})

describe('CurveDashboardPane - delete', () => {
  it('names the curve in the confirmation, then deletes and refreshes', async () => {
    vi.mocked(deleteCurve).mockResolvedValue(undefined)
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const props = baseProps()

    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Delete this curve'))

    expect(confirmSpy.mock.calls[0][0]).toContain('both flat')
    expect(confirmSpy.mock.calls[0][0]).not.toMatch(/are you sure/i)

    await waitFor(() => expect(deleteCurve).toHaveBeenCalledWith('2026-09-13T08-00-00Z-both-flat'))
    expect(props.onDeleted).toHaveBeenCalled()
  })

  it('does not delete when the confirmation is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const props = baseProps()

    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Delete this curve'))

    expect(deleteCurve).not.toHaveBeenCalled()
    expect(props.onDeleted).not.toHaveBeenCalled()
  })

  it('is disabled with an explanation in demo (simulated) mode, and never calls the endpoint', () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const props = baseProps()

    renderPaneInSandbox(<CurveDashboardPane {...props} />)
    const button = screen.getByTitle('Deleting is unavailable in demo mode')
    expect((button as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(button)
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(deleteCurve).not.toHaveBeenCalled()
  })
})

describe('CurveDashboardPane - remeasure', () => {
  it('confirms first, then hands the whole record to onRemeasure - nothing deleted here', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const props = baseProps()

    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Capture a replacement, then remove this curve'))

    expect(props.onRemeasure).toHaveBeenCalledWith(props.record)
    expect(deleteCurve).not.toHaveBeenCalled()
  })

  it('does not start a remeasure when the confirmation is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const props = baseProps()

    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Capture a replacement, then remove this curve'))

    expect(props.onRemeasure).not.toHaveBeenCalled()
  })

  it('is disabled with an explanation in demo (simulated) mode', () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const props = baseProps()

    renderPaneInSandbox(<CurveDashboardPane {...props} />)
    const button = screen.getByTitle('Remeasure needs real hardware - unavailable in demo mode')
    expect((button as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(button)
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(props.onRemeasure).not.toHaveBeenCalled()
  })

  it('disables both remeasure and delete while a replacement for this curve is already pending', () => {
    const props = baseProps({ remeasurePending: true })
    renderPane(<CurveDashboardPane {...props} />)

    const buttons = screen.getAllByTitle('A replacement capture is already pending for this curve')
    expect(buttons).toHaveLength(2) // both remeasure and delete
    for (const b of buttons) expect((b as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('CurveDashboardPane - save/download', () => {
  it('stays enabled in demo (simulated) mode - a download touches nothing', () => {
    const props = baseProps()
    renderPaneInSandbox(<CurveDashboardPane {...props} />)
    const trigger = screen.getByTitle('Save (download)')
    expect((trigger as HTMLButtonElement).disabled).toBeFalsy()
  })

  it('offers both JSON and CSV once opened', async () => {
    const props = baseProps()
    renderPane(<CurveDashboardPane {...props} />)
    fireEvent.click(screen.getByTitle('Save (download)'))

    await waitFor(() => expect(screen.getByText('Download JSON')).toBeTruthy())
    expect(screen.getByText('Download CSV')).toBeTruthy()
  })
})
