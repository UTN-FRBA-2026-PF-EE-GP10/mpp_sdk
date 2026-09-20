import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { ImportedSessionProvider } from '@/components/ImportedSessionProvider'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { buildSessionFile, readOnlyReasonText, type SessionFile } from '@/lib/sessionFile'
import type { SessionRecord } from '@/lib/sessions'
import type { CurveRecord } from '@/types'

// Same reasoning as App.test.tsx: this suite is about view mode's data
// swap and read-only gating, not chart rendering or live polling.
vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  fetchCurves: vi.fn(),
  fetchMeasurementKinds: vi.fn(() => Promise.resolve([])),
  fetchRuns: vi.fn(),
  fetchSessions: vi.fn(() => Promise.resolve([])),
  fetchSession: vi.fn(),
  createSession: vi.fn(),
  patchSession: vi.fn(),
  deleteSession: vi.fn(),
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
  createSession,
  deleteCurve,
  deleteCurvesBatch,
  deleteRun,
  deleteRunsBatch,
  deleteSession,
  fetchCurves,
  fetchRun,
  fetchRuns,
  fetchSession,
  fetchSessions,
  patchSession,
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

function testSessionRecord(): SessionRecord {
  return {
    id: '20260919T160000Z-imported',
    title: 'Imported test session',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:05:00+00:00',
    fields: { panel: 'Luxen LN-10P, 10 W, 12 V' },
    steps: [
      {
        id: 'firmware-config',
        section: 'Before energizing',
        title: 'Firmware configuration',
        instructions: 'Check the firmware build.',
        kind: 'check',
        status: 'done',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: [],
        repeats: 1,
      },
      {
        id: 'po-run',
        section: 'Runs',
        title: 'P&O run',
        instructions: 'Run P&O for 10 s.',
        kind: 'run',
        status: 'done',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: ['session-r1'],
        repeats: 1,
      },
    ],
    open_questions: [],
  }
}

function testSessionFile(): SessionFile {
  return buildSessionFile({
    title: 'Imported test session',
    setup: 'single',
    session: testSessionRecord(),
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

  // The stub this replaced only said "report view coming soon" - this is
  // the real wiring: SessionView fed straight from the file's own bundled
  // records, no fetch, no PATCH.
  it('"View session" renders the file\'s own session - real steps and statistics, no fetch at all', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await importSessionFile(testSessionFile())

    fireEvent.click(screen.getByText('View session'))

    await screen.findByText('Imported test session')
    expect(screen.getByText('Firmware configuration')).toBeTruthy()
    expect(screen.getByText('P&O run')).toBeTruthy()
    expect(screen.getByText('2 / 2')).toBeTruthy() // n_done / n_steps - both steps 'done'
    // The linked run's own held power, computed from its bundled samples -
    // proof the statistics come from the file, not a fetch.
    expect(screen.getAllByText(/Held/).length).toBeGreaterThan(0)
    expect(fetchSession).not.toHaveBeenCalled()
    expect(fetchRun).not.toHaveBeenCalled()
  })

  it('"View session" is read-only: no Delete session button, no edit calls possible', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await importSessionFile(testSessionFile())

    fireEvent.click(screen.getByText('View session'))

    await screen.findByText('Imported test session')
    expect(screen.getByText('Read-only')).toBeTruthy()
    expect(screen.queryByText('Delete session')).toBeNull()
    expect(patchSession).not.toHaveBeenCalled()
    expect(deleteSession).not.toHaveBeenCalled()
  })
})

// Two write paths an adversarial review found reachable while the banner
// says "read-only - nothing here is saved or sent to a server": the
// sidebar's "New session" row, and a live SessionPane left mounted when a
// session-only import (no curves/runs) never redirects the selection away
// from it. Both must be closed off.
describe('write paths stay closed while an imported session is active', () => {
  function liveSessionSummary() {
    return {
      id: 'live-1',
      title: 'Live editable session',
      template_id: 'single-panel-characterization',
      setup: 'single',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      n_steps: 1,
      n_done: 0,
      n_failed: 0,
    }
  }

  function liveSessionRecord(): SessionRecord {
    return {
      id: 'live-1',
      title: 'Live editable session',
      template_id: 'single-panel-characterization',
      template_version: 1,
      setup: 'single',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
      fields: {},
      steps: [
        {
          id: 'firmware-config',
          section: 'Before energizing',
          title: 'Firmware configuration',
          instructions: '',
          kind: 'check',
          status: 'todo',
          value: null,
          unit: null,
          notes: '',
          curve_ids: [],
          run_ids: [],
          repeats: 1,
        },
      ],
      open_questions: [],
    }
  }

  it('hides the sidebar\'s "New session" row while viewing an imported session', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    renderApp()
    await screen.findByText('New session')

    await importSessionFile(testSessionFile())

    expect(screen.queryByText('New session')).toBeNull()
    expect(createSession).not.toHaveBeenCalled()
  })

  it('a session-only import over an open live session closes it off instead of leaving it writable', async () => {
    vi.mocked(fetchCurves).mockResolvedValue([])
    vi.mocked(fetchRuns).mockResolvedValue([])
    vi.mocked(fetchSessions).mockResolvedValue([liveSessionSummary()])
    vi.mocked(fetchSession).mockResolvedValue(liveSessionRecord())
    renderApp()

    // Open the live, writable session first.
    fireEvent.click(await screen.findByText('Live editable session'))
    await screen.findByText('Delete session')

    // A session-only bundle (no curves, no runs) never redirects the
    // selection (see useSessionFileImport's onImported in App.tsx), so it
    // stays on this same session id - the exact scenario the review found.
    const sessionOnlyFile = buildSessionFile({
      title: 'Session-only file',
      setup: 'single',
      curves: [],
      runs: [],
      session: testSessionRecord(),
    })
    await importSessionFile(sessionOnlyFile)

    expect(screen.getByText('Sessions are unavailable')).toBeTruthy()
    expect(screen.queryByText('Delete session')).toBeNull()
    expect(patchSession).not.toHaveBeenCalled()
    expect(deleteSession).not.toHaveBeenCalled()
  })
})
