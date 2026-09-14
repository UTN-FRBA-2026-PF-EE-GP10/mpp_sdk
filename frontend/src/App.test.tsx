import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  fetchCurves: vi.fn(),
  fetchMeasurementKinds: vi.fn(() => Promise.resolve([])),
  fetchRuns: vi.fn(),
  saveCurve: vi.fn(),
  startSweep: vi.fn(),
  startDemoSweep: vi.fn(),
  releaseRelay: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  deleteCurve: vi.fn(),
}))

// Switching capture mode re-renders CurveWorkbench's LiveChart with a
// fresh (empty) data array, a genuine chart.js update that crashes under
// jsdom regardless of content - see the same note in
// CurveWorkbench.test.tsx. This suite is about what data/controls are on
// screen, not chart rendering, so the chart itself is stubbed out.
vi.mock('react-chartjs-2', () => ({ Line: () => null }))

import { deleteCurve, fetchCurves, fetchLiveSweep, fetchRuns, saveCurve } from '@/lib/api'

function liveCurve(n: number): CurveRecord {
  return {
    id: `live-${n}`,
    path: `/data/curves/live-${n}.json`,
    captured_at: '2026-01-01T00:00:00Z',
    label: `Live bench curve ${n}`,
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 20,
    isc: 0.2,
    p_mpp: 3,
    points: [
      { v: 0, i: 0.2 },
      { v: 20, i: 0 },
    ],
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.localStorage.clear()
})

// "Baseline" appears twice on screen at once - once as the sidebar's nav
// row (what these tests care about), once as MeasurePane's kind tab. The
// sidebar renders first in the DOM.
function baselineNavRow() {
  return screen.getAllByText('Baseline')[0].closest('button')!
}

function renderApp() {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeProvider>
          <App />
        </CaptureModeProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

/** Opens the connection indicator's menu and picks the named mode -
 * mirrors how an operator actually switches capture mode. */
async function pickCaptureMode(name: 'Pi connected' | 'Demo with Pi' | 'Demo') {
  fireEvent.click(screen.getByRole('button', { name: /capture mode/i }))
  const label = await screen.findByText(name)
  fireEvent.click(label)
}

describe('App capture mode', () => {
  it('loads live curves on start, swaps to the bundled fixture in Demo mode, and restores live data going back', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1), liveCurve(2)])
    vi.mocked(fetchRuns).mockResolvedValue([])

    renderApp()

    await waitFor(() => {
      expect(within(baselineNavRow()).getByText('2')).toBeTruthy()
    })
    expect(fetchCurves).toHaveBeenCalledTimes(1)

    await pickCaptureMode('Demo')

    await waitFor(() => expect(screen.getByText(/bundled sample data/i)).toBeTruthy())
    await waitFor(() => {
      expect(within(baselineNavRow()).getByText('1')).toBeTruthy() // DEMO_CURVE_BRIGHT is the only baseline fixture
    })
    // No extra fetch while sandboxed - the fixture swap does not touch the API.
    expect(fetchCurves).toHaveBeenCalledTimes(1)

    await pickCaptureMode('Pi connected')

    await waitFor(() => expect(fetchCurves).toHaveBeenCalledTimes(2))
    await waitFor(() => {
      expect(within(baselineNavRow()).getByText('2')).toBeTruthy()
    })
    expect(screen.queryByText(/bundled sample data/i)).toBeNull()
  })

  it('presents the Measure pane as inert, not silently dead, in Demo mode', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    await pickCaptureMode('Demo')

    await waitFor(() => expect(screen.getByText('Start Measurement').closest('button')?.disabled).toBe(true))
    expect(screen.getByText('Release Relay').closest('button')?.disabled).toBe(true)
    expect(screen.getByText('Demo curve (bright)').closest('button')?.disabled).toBe(false)
  })

  it('cannot select Demo with Pi while disconnected - the option is unavailable, not silently broken', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    // fetchLiveSweep never resolves (mocked above), so the link stays
    // 'connecting' - not 'connected' - for the life of this test.
    fireEvent.click(screen.getByRole('button', { name: /capture mode/i }))
    const item = (await screen.findByText('Demo with Pi')).closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')
  })
})

const REMEASURE_TITLE = 'Capture a replacement, then remove this curve'

async function startRemeasureFromBaselinePane() {
  fireEvent.click(baselineNavRow())
  fireEvent.click(await screen.findByTitle(REMEASURE_TITLE))
  await screen.findByText(/Remeasure pending/)
}

describe('App remeasure workflow', () => {
  it('confirms, then navigates to Measure prefilled and shows a banner naming the curve', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    await startRemeasureFromBaselinePane()

    expect(screen.getByDisplayValue('Live bench curve 1')).toBeTruthy() // prefilled label
    expect(screen.getByText(/replacing/)).toBeTruthy()
    expect(screen.getAllByText(/Live bench curve 1/).length).toBeGreaterThan(1) // form input + banner
  })

  it('does nothing when the remeasure confirmation is declined', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    fireEvent.click(baselineNavRow())
    fireEvent.click(await screen.findByTitle(REMEASURE_TITLE))

    expect(screen.queryByText(/Remeasure pending/)).toBeNull()
    // Still looking at the curves pane, not bounced to Measure.
    expect(screen.getByText('Live bench curve 1')).toBeTruthy()
  })

  it('dropping the pending remeasure via Cancel never deletes the old curve', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())
    await startRemeasureFromBaselinePane()

    fireEvent.click(screen.getByText('Cancel remeasure'))

    expect(screen.queryByText(/Remeasure pending/)).toBeNull()
    expect(deleteCurve).not.toHaveBeenCalled()
  })

  it('survives navigating to a different section - old curve untouched, banner still visible', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())
    await startRemeasureFromBaselinePane()

    // Wander off to a different curves kind without saving or cancelling.
    fireEvent.click(screen.getAllByText('Dimmed')[0].closest('button')!)

    expect(screen.getByText(/Remeasure pending/)).toBeTruthy() // never a hidden mode
    expect(deleteCurve).not.toHaveBeenCalled()
  })

  it('fires the pending deletion only once the replacement capture is actually saved', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.mocked(fetchLiveSweep).mockResolvedValue({
      points: [
        { v: 0, i: 0.2 },
        { v: 20, i: 0 },
      ],
      partial: [],
      active: false,
      link: 'ok',
      seq: 1,
      commandError: null,
      demoSource: false,
    })
    vi.mocked(saveCurve).mockResolvedValue({ path: '/data/curves/new.json' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    await startRemeasureFromBaselinePane()
    // Confirming/navigating must never have deleted anything by itself.
    expect(deleteCurve).not.toHaveBeenCalled()

    await waitFor(() =>
      expect(screen.getByText('Save curve').closest('button')?.disabled).toBe(false),
    )
    fireEvent.click(screen.getByText('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    await waitFor(() => expect(deleteCurve).toHaveBeenCalledWith('live-1'))
    await waitFor(() => expect(screen.queryByText(/Remeasure pending/)).toBeNull())
  })
})
