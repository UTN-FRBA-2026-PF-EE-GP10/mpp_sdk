import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  fetchCurves: vi.fn(),
  fetchMeasurementKinds: vi.fn(() => Promise.resolve([])),
  fetchRuns: vi.fn(),
  fetchSessions: vi.fn(() => Promise.resolve([])),
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

// Some CurveWorkbench buttons (Start Measurement, Hand panel to converter, Save
// curve) carry a `title` explaining a demo-mode disablement, so they use
// focusableWhenDisabled (aria-disabled, not the native attribute) to keep
// that title reachable by hover/focus - see button.tsx and
// CurveDashboardPane's note on the same fix. This checks either form.
function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true'
}

function renderApp() {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeProvider>
          <CaptureModeProvider>
            <App />
          </CaptureModeProvider>
        </SetupModeProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

/** Opens the connection indicator's menu and picks the named mode -
 * mirrors how an operator actually switches capture mode. */
async function pickCaptureMode(name: 'PICO connected' | 'Replay on the board' | 'Demo') {
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

    await pickCaptureMode('PICO connected')

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

    await waitFor(() => expect(isDisabled(screen.getByText('Start Measurement').closest('button')!)).toBe(true))
    expect(isDisabled(screen.getByText('Hand panel to converter').closest('button')!)).toBe(true)
    expect(isDisabled(screen.getByText('Replay curve (bright)').closest('button')!)).toBe(false)
  })

  it('cannot select Replay on the board while disconnected - the option is unavailable, not silently broken', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    // fetchLiveSweep never resolves (mocked above), so the link stays
    // 'connecting' - not 'connected' - for the life of this test.
    fireEvent.click(screen.getByRole('button', { name: /capture mode/i }))
    const item = (await screen.findByText('Replay on the board')).closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')
  })

  it(
    'stops polling the link in Demo mode and resumes promptly on leaving it',
    async () => {
      vi.mocked(fetchCurves).mockResolvedValue([])
      vi.mocked(fetchRuns).mockResolvedValue([])
      vi.mocked(fetchLiveSweep).mockResolvedValue({
        points: [],
        partial: [],
        active: false,
        link: 'ok',
        seq: 0,
        commandError: null,
        demoSource: false,
      })
      renderApp()
      await waitFor(() => expect(fetchLiveSweep).toHaveBeenCalled())

      await pickCaptureMode('Demo')
      const callsAtSwitch = vi.mocked(fetchLiveSweep).mock.calls.length

      // useConnectionStatus polls every 2s (POLL_MS) - wait comfortably
      // past one interval and confirm no further call landed.
      await new Promise((r) => setTimeout(r, 2500))
      expect(vi.mocked(fetchLiveSweep).mock.calls.length).toBe(callsAtSwitch)

      await pickCaptureMode('PICO connected')
      // Resumes right away rather than waiting out a full interval.
      await waitFor(
        () => expect(vi.mocked(fetchLiveSweep).mock.calls.length).toBeGreaterThan(callsAtSwitch),
        { timeout: 500 },
      )
    },
    5000,
  )
})

const REMEASURE_TITLE = 'Capture a replacement, then remove this curve'

async function startRemeasureFromBaselinePane() {
  fireEvent.click(baselineNavRow())
  fireEvent.click(await screen.findByTitle(REMEASURE_TITLE))
  await screen.findByText(/Remeasure pending/)
}

describe('App load errors', () => {
  it('shows a banner naming what failed, with a way to retry, instead of a silently empty library', async () => {
    vi.mocked(fetchCurves).mockRejectedValue(new Error('network error'))
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    await waitFor(() => expect(screen.getByText(/Couldn't load your saved curves/)).toBeTruthy())
    expect(screen.getByText(/network error/)).toBeTruthy()
    expect(screen.queryByText(/Couldn't load your saved runs/)).toBeNull()

    vi.mocked(fetchCurves).mockResolvedValue([liveCurve(1)])
    fireEvent.click(screen.getByText('Retry'))

    await waitFor(() => expect(screen.queryByText(/Couldn't load your saved curves/)).toBeNull())
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())
  })

  it('ignores a stale answer from an older request after a newer retry', async () => {
    vi.mocked(fetchCurves).mockRejectedValue(new Error('network error'))
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await waitFor(() => expect(screen.getByText(/Couldn't load your saved curves/)).toBeTruthy())

    let resolveStale: (value: CurveRecord[]) => void = () => {}
    vi.mocked(fetchCurves).mockReturnValueOnce(
      new Promise<CurveRecord[]>((resolve) => {
        resolveStale = resolve
      }),
    )
    fireEvent.click(screen.getByText('Retry'))
    vi.mocked(fetchCurves).mockRejectedValueOnce(new Error('still broken'))
    fireEvent.click(screen.getByText('Retry'))
    await waitFor(() => expect(screen.getByText(/still broken/)).toBeTruthy())

    await act(async () => resolveStale([liveCurve(1)]))
    expect(screen.getByText(/still broken/)).toBeTruthy()
  })

  it('never shows a load-error banner in Demo mode, where nothing is fetched', async () => {
    vi.mocked(fetchCurves).mockRejectedValue(new Error('network error'))
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    await waitFor(() => expect(screen.getByText(/Couldn't load your saved curves/)).toBeTruthy())

    await pickCaptureMode('Demo')

    expect(screen.queryByText(/Couldn't load your saved curves/)).toBeNull()
  })
})

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
    vi.mocked(saveCurve).mockResolvedValue({ path: '/data/curves/new.json', id: 'new' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    await startRemeasureFromBaselinePane()
    // Confirming/navigating must never have deleted anything by itself.
    expect(deleteCurve).not.toHaveBeenCalled()

    await waitFor(() =>
      expect(isDisabled(screen.getByText('Save curve').closest('button')!)).toBe(false),
    )
    fireEvent.click(screen.getByText('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    await waitFor(() => expect(deleteCurve).toHaveBeenCalledWith('live-1'))
    await waitFor(() => expect(screen.queryByText(/Remeasure pending/)).toBeNull())
  })

  it('only consumes a pending remeasure when the save lands under its own kind', async () => {
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
    vi.mocked(saveCurve).mockResolvedValue({ path: '/data/curves/new.json', id: 'new' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    await startRemeasureFromBaselinePane()
    const capturingUnder = screen.getByText('Capturing under:').parentElement!

    // Save under a different kind while the baseline remeasure is still
    // pending - an unrelated save must not consume it or delete anything.
    fireEvent.click(within(capturingUnder).getByText('Dimmed'))
    fireEvent.change(screen.getByPlaceholderText(/label, e.g/), {
      target: { value: 'unrelated dimmed capture' },
    })
    await waitFor(() =>
      expect(isDisabled(screen.getByText('Save curve').closest('button')!)).toBe(false),
    )
    fireEvent.click(screen.getByText('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalledTimes(1))
    expect(deleteCurve).not.toHaveBeenCalled()
    expect(screen.getByText(/Remeasure pending/)).toBeTruthy()

    // Now save under the remeasure's own kind (baseline) - this is the
    // save it was actually waiting for. A successful save clears the
    // label box, so this one needs its own label typed again.
    fireEvent.click(within(capturingUnder).getByText('Baseline'))
    fireEvent.change(screen.getByPlaceholderText(/label, e.g/), {
      target: { value: 'baseline replacement' },
    })
    await waitFor(() =>
      expect(isDisabled(screen.getByText('Save curve').closest('button')!)).toBe(false),
    )
    fireEvent.click(screen.getByText('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(deleteCurve).toHaveBeenCalledWith('live-1'))
    await waitFor(() => expect(screen.queryByText(/Remeasure pending/)).toBeNull())
  })
})

describe('App setup mode', () => {
  it('toggles between Full and Single from the header and persists the choice', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    const toggle = screen.getByTitle(/Setup: Full/i)
    expect(toggle.textContent).toBe('Full')

    fireEvent.click(toggle)

    expect(screen.getByTitle(/Setup: Single/i).textContent).toBe('Single')
    expect(window.localStorage.getItem('mpp-sdk.setup-mode')).toBe('single')
  })

  it('shows the Full-setup ADC reminder only after switching into it, and dismisses on request', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()

    // Full is the default - nothing was switched into, so no reminder yet.
    expect(screen.queryByText(/Move the ADC jumpers to Mid/)).toBeNull()

    fireEvent.click(screen.getByTitle(/Setup: Full/i)) // -> single
    expect(screen.queryByText(/Move the ADC jumpers to Mid/)).toBeNull()

    fireEvent.click(screen.getByTitle(/Setup: Single/i)) // -> full
    expect(screen.getByText(/Move the ADC jumpers to Mid/)).toBeTruthy()

    fireEvent.click(screen.getByText('Dismiss'))
    expect(screen.queryByText(/Move the ADC jumpers to Mid/)).toBeNull()
  })

  it('keeps panel B when remeasuring a two-panel curve while Single setup is active', async () => {
    const twoPanelCurve: CurveRecord = {
      ...liveCurve(1),
      panels: [
        { id: 'A', tilt_deg: 90 },
        { id: 'B', tilt_deg: 60 },
      ],
    }
    vi.mocked(fetchCurves).mockResolvedValue([twoPanelCurve])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await waitFor(() => expect(within(baselineNavRow()).getByText('1')).toBeTruthy())

    // Switching to Single must not silently drop panel B from a curve
    // that already has one - the point of this test.
    fireEvent.click(screen.getByTitle(/Setup: Full/i))

    await startRemeasureFromBaselinePane()

    expect(screen.getByText('Panel B tilt')).toBeTruthy()
    expect(screen.getByText(/keeps both, even though setup is Single/)).toBeTruthy()
  })
})
