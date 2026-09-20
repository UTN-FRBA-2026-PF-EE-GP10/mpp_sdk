import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { ImportedSessionProvider } from '@/components/ImportedSessionProvider'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { buildSessionFile, readOnlyReasonText, type SessionFile } from '@/lib/sessionFile'
import type { CurveRecord } from '@/types'

// Same reasoning as App.test.tsx: this suite is about view mode's data
// swap and read-only gating, not chart rendering or live polling.
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
  deleteCurvesBatch: vi.fn(),
  deleteRunsBatch: vi.fn(),
  fetchRunConfig: vi.fn(() => new Promise(() => {})),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  fetchLiveRun: vi.fn(() => new Promise(() => {})),
}))

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

import {
  deleteCurve,
  deleteCurvesBatch,
  deleteRun,
  deleteRunsBatch,
  fetchCurves,
  fetchRun,
  fetchRuns,
  saveCurve,
} from '@/lib/api'

function liveCurve(): CurveRecord {
  return {
    id: 'live-1',
    path: '/data/curves/live-1.json',
    captured_at: '2026-01-01T00:00:00Z',
    label: 'Live bench curve',
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

function testSessionFile(): SessionFile {
  return buildSessionFile({
    title: 'Imported test session',
    setup: 'single',
    curves: [
      {
        id: 'session-c1',
        path: '/data/curves/session-c1.json',
        captured_at: '2026-09-19T16:00:00Z',
        label: 'Session curve',
        measurement: 'baseline',
        panels: [{ id: 'A', tilt_deg: 90 }],
        notes: '',
        n_points: 2,
        source: 'hardware',
        voc: 20,
        isc: 0.5,
        p_mpp: 7,
        points: [
          { v: 0, i: 0.5 },
          { v: 20, i: 0 },
        ],
      },
    ],
    runs: [
      {
        id: 'session-r1',
        path: '/data/runs/session-r1.json',
        captured_at: '2026-09-19T16:05:00Z',
        label: 'Session run',
        algorithm: 'P&O',
        n_samples: 2,
        duration_s: 1,
        aborted: false,
        curve_ref: null,
        notes: '',
        source: 'hardware',
        downsampled: false,
        samples: [
          { t: 0, v: 17.5, i: 0.3, d: 0.4 },
          { t: 1, v: 14, i: 0.4, d: 0.5 },
        ],
      },
    ],
  })
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderApp() {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeProvider>
          <CaptureModeProvider>
            <ImportedSessionProvider>
              <App />
            </ImportedSessionProvider>
          </CaptureModeProvider>
        </SetupModeProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function fileInput(): HTMLInputElement {
  return document.querySelector('input[type="file"]') as HTMLInputElement
}

async function importSessionFile(file: SessionFile) {
  const asFile = new File([JSON.stringify(file)], 'session.mppsession.json', {
    type: 'application/json',
  })
  fireEvent.change(fileInput(), { target: { files: [asFile] } })
  await screen.findByText(/Viewing:/)
}

describe('importing a session file (view mode)', () => {
  it('replaces the data source, shows the Viewing badge, and jumps to the session content', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve()])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await screen.findByText('Live bench curve')

    await importSessionFile(testSessionFile())

    expect(screen.getByText(/Viewing: Imported test session/)).toBeTruthy()
    // Auto-navigated to the session's own curve, not left on the (now
    // inert) Measure pane.
    expect(screen.getByText('Session curve')).toBeTruthy()
    expect(screen.queryByText('Live bench curve')).toBeNull()
  })

  it('drops a pending remeasure, which view mode could never finish', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve()])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderApp()
    await screen.findByText('Live bench curve')
    fireEvent.click(screen.getAllByText('Baseline')[0].closest('button')!)
    fireEvent.click(await screen.findByTitle('Capture a replacement, then remove this curve'))
    await screen.findByText(/Remeasure pending/)

    await importSessionFile(testSessionFile())

    expect(screen.queryByText(/Remeasure pending/)).toBeNull()
  })

  it('never fetches curves/runs again while an imported session is active', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve()])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await screen.findByText('Live bench curve')
    expect(fetchCurves).toHaveBeenCalledTimes(1)
    expect(fetchRuns).toHaveBeenCalledTimes(1)

    await importSessionFile(testSessionFile())
    await new Promise((r) => setTimeout(r, 50))

    expect(fetchCurves).toHaveBeenCalledTimes(1)
    expect(fetchRuns).toHaveBeenCalledTimes(1)
  })

  it('disables delete on the imported curve, and never calls a mutating endpoint', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await importSessionFile(testSessionFile())

    const deleteTitle = readOnlyReasonText('view', 'Deleting')
    const deleteButton = await screen.findByTitle(deleteTitle)
    fireEvent.click(deleteButton) // defense in depth - must be a no-op

    expect(deleteButton.hasAttribute('disabled') || deleteButton.getAttribute('aria-disabled') === 'true').toBe(
      true,
    )
    expect(deleteCurve).not.toHaveBeenCalled()
    expect(deleteCurvesBatch).not.toHaveBeenCalled()
    expect(deleteRun).not.toHaveBeenCalled()
    expect(deleteRunsBatch).not.toHaveBeenCalled()
    expect(saveCurve).not.toHaveBeenCalled()
  })

  it('the run player reads samples from the file, never GET /api/runs/{id}', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await importSessionFile(testSessionFile())

    // Runs starts expanded by default (Sidebar's own initial state).
    fireEvent.click(screen.getByText('2026-09-19').closest('button')!)
    fireEvent.click(await screen.findByText('Session run'))

    // The first sample's own voltage (17.50 V), not anything a mocked
    // fetchRun could have returned - and fetchRun was never called at all.
    await screen.findByText('17.50 V')
    expect(fetchRun).not.toHaveBeenCalled()
  })

  it('Close restores the previous (live) mode', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve()])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await screen.findByText('Live bench curve')

    await importSessionFile(testSessionFile())
    expect(screen.getByText('Session curve')).toBeTruthy()

    fireEvent.click(screen.getByText('Close'))

    await waitFor(() => expect(screen.queryByText(/Viewing:/)).toBeNull())
    expect(screen.getByText('Live bench curve')).toBeTruthy()
    expect(screen.queryByText('Session curve')).toBeNull()
  })

  it('rejects a bad file with a clear message and leaves the current view untouched', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([liveCurve()])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await screen.findByText('Live bench curve')

    const badFile = new File([JSON.stringify({ format: 'not-a-session' })], 'bad.json', {
      type: 'application/json',
    })
    fireEvent.change(fileInput(), { target: { files: [badFile] } })

    await screen.findByText(/Couldn't open that session file/)
    expect(screen.queryByText(/Viewing:/)).toBeNull()
    expect(screen.getByText('Live bench curve')).toBeTruthy()
  })
})
