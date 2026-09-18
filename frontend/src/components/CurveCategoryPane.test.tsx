import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurveCategoryPane } from './CurveCategoryPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  deleteCurvesBatch: vi.fn(),
}))

import { deleteCurvesBatch } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

// The chart and metadata read the page's unit and theme settings, so
// anything rendering them needs the providers the app root supplies.
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

function twoRecords(): CurveRecord[] {
  return [
    record({ id: 'curve-a', path: '/data/curves/curve-a.json', label: 'curve a' }),
    record({ id: 'curve-b', path: '/data/curves/curve-b.json', label: 'curve b' }),
  ]
}

describe('CurveCategoryPane - batch delete', () => {
  it('has no Select toggle when there is nothing saved under this kind', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={[]} />)
    expect(screen.queryByRole('button', { name: 'Select' })).toBeNull()
  })

  it('shows a checkbox per pane once Select is toggled on', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={twoRecords()} />)
    expect(screen.queryByLabelText('Select "curve a" for batch delete')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Select' }))

    expect(screen.getByLabelText('Select "curve a" for batch delete')).toBeTruthy()
    expect(screen.getByLabelText('Select "curve b" for batch delete')).toBeTruthy()
  })

  it('names the count in one confirm, then deletes the selected curves and refreshes', async () => {
    vi.mocked(deleteCurvesBatch).mockResolvedValue({ deleted: ['curve-a'], failed: [] })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onDeleted = vi.fn()

    renderPane(<CurveCategoryPane kind="baseline" records={twoRecords()} onDeleted={onDeleted} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "curve a" for batch delete'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 1 selected/ }))

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(confirmSpy.mock.calls[0][0]).toContain('1 selected curve')

    await waitFor(() => expect(deleteCurvesBatch).toHaveBeenCalledWith(['curve-a']))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    // A fully successful batch drops back out of select mode.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Select' })).toBeTruthy())
  })

  it('deletes nothing when the confirmation is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderPane(<CurveCategoryPane kind="baseline" records={twoRecords()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "curve a" for batch delete'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 1 selected/ }))

    expect(deleteCurvesBatch).not.toHaveBeenCalled()
  })

  it('selects every visible curve at once via Select all', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPane(<CurveCategoryPane kind="baseline" records={twoRecords()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))

    fireEvent.click(screen.getByLabelText('Select all'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 2 selected/ }))

    expect(window.confirm).toHaveBeenCalled()
    expect((window.confirm as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain(
      '2 selected curves',
    )
  })

  it('on a partial failure, reports which curve failed and keeps only it selected', async () => {
    vi.mocked(deleteCurvesBatch).mockResolvedValue({
      deleted: ['curve-a'],
      failed: [{ id: 'curve-b', error: 'boom' }],
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderPane(<CurveCategoryPane kind="baseline" records={twoRecords()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select all'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 2 selected/ }))

    await waitFor(() => expect(screen.getByText(/Failed to delete 1 curve/)).toBeTruthy())
    expect(screen.getByText(/curve b.*boom/)).toBeTruthy()
    // Still in select mode, and the failed one is still checked.
    const checkbox = screen.getByLabelText(
      'Select "curve b" for batch delete',
    ) as HTMLInputElement
    expect(checkbox.checked).toBe(true)
  })

  it('is unavailable in demo (simulated) mode - the button is disabled and nothing is ever sent', () => {
    const confirmSpy = vi.spyOn(window, 'confirm')

    renderPaneInSandbox(<CurveCategoryPane kind="baseline" records={twoRecords()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "curve a" for batch delete'))

    // Distinct from CurveDashboardPane's own per-pane delete buttons,
    // which share the same disabled title text - matched by its visible
    // "Delete 1 selected" label instead.
    const button = screen.getByRole('button', { name: /Delete 1 selected/ })
    expect(button.getAttribute('aria-disabled')).toBe('true')
    expect(button.getAttribute('title')).toBe('Deleting is unavailable in demo mode')

    fireEvent.click(button)
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(deleteCurvesBatch).not.toHaveBeenCalled()
  })
})
