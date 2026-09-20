import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ActiveSessionProvider } from '@/components/ActiveSessionProvider'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { ACTIVE_SESSION_STORAGE_KEY } from '@/lib/activeSession'
import type { SessionSummary } from '@/lib/sessions'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  fetchCurves: vi.fn(() => Promise.resolve([])),
  fetchMeasurementKinds: vi.fn(() => Promise.resolve([])),
  fetchRuns: vi.fn(() => Promise.resolve([])),
  fetchSessions: vi.fn(),
  fetchSession: vi.fn(),
  fetchRunConfig: vi.fn(),
  saveCurve: vi.fn(),
  startSweep: vi.fn(),
  startDemoSweep: vi.fn(),
  releaseRelay: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  deleteCurve: vi.fn(),
}))

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

import { fetchSession, fetchSessions } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.localStorage.clear()
})

function summary(id: string, title: string): SessionSummary {
  return {
    id,
    title,
    template_id: 'single-panel-characterization',
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:00:00+00:00',
    n_steps: 3,
    n_done: 0,
    n_failed: 0,
  }
}

function remember(id: string, title: string) {
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify({ id, title }))
}

function renderApp() {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeProvider>
          <CaptureModeProvider>
            <ActiveSessionProvider>
              <App />
            </ActiveSessionProvider>
          </CaptureModeProvider>
        </SetupModeProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

describe('App and the active session', () => {
  it('shows which session captures are filed into, on every section, and lets it be dismissed', async () => {
    vi.mocked(fetchSessions).mockResolvedValue([summary('s1', 'Panel A alone')])
    remember('s1', 'Panel A alone')
    renderApp()

    expect(screen.getByRole('status').textContent).toContain('Panel A alone')
    // The list arrives and still names it: nothing is cleared.
    await waitFor(() => expect(fetchSessions).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.getByRole('status').textContent).toContain('Panel A alone')

    fireEvent.click(within(screen.getByRole('status')).getByText('Stop filing'))
    expect(screen.queryByText(/Filing new captures into/)).toBeNull()
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('stops filing into a session that no longer exists, without touching anything else', async () => {
    vi.mocked(fetchSessions).mockResolvedValue([summary('other', 'Another session')])
    remember('deleted-elsewhere', 'Gone')
    renderApp()

    await waitFor(() => expect(screen.queryByText(/Filing new captures into/)).toBeNull())
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
    // The rest of the app is up.
    expect(screen.getByText('Another session')).toBeTruthy()
  })

  it('keeps the active session when the list fails to load - a failed fetch is not a deletion', async () => {
    vi.mocked(fetchSessions).mockRejectedValue(new Error('offline'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    remember('s1', 'Panel A alone')
    renderApp()

    await waitFor(() => expect(fetchSessions).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.getByRole('status').textContent).toContain('Panel A alone')
  })

  it('opens the active session from the banner', async () => {
    vi.mocked(fetchSessions).mockResolvedValue([summary('s1', 'Panel A alone')])
    // The session itself is not the point here - only that the banner navigated to it.
    vi.mocked(fetchSession).mockRejectedValue(new Error('not needed'))
    remember('s1', 'Panel A alone')
    renderApp()

    fireEvent.click(within(screen.getByRole('status')).getByText('Open session'))
    await waitFor(() => expect(fetchSession).toHaveBeenCalledWith('s1'))
  })
})
