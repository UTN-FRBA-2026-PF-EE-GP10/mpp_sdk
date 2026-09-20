import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurveWorkbench } from './CurveWorkbench'
import { MeasurePane } from './MeasurePane'
import { RunPane } from './RunPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { ActiveSessionContext, type ActiveSessionValue } from '@/lib/activeSession'
import { CaptureModeContext } from '@/lib/captureMode'
import { SetupModeContext } from '@/lib/setupMode'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
  startSweep: vi.fn().mockResolvedValue(undefined),
  startDemoSweep: vi.fn().mockResolvedValue(undefined),
  releaseRelay: vi.fn().mockResolvedValue(undefined),
  saveCurve: vi.fn(),
  fetchRunConfig: vi.fn(),
  fetchRuns: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  fetchLiveRun: vi.fn(),
}))

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

import { fetchLiveRun, fetchLiveSweep, fetchRunConfig, saveCurve, startRun } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
  vi.restoreAllMocks()
})

const ACTIVE: ActiveSessionValue = {
  active: { id: 'sess-1', title: 'Panel A alone' },
  setActive: vi.fn(),
  clear: vi.fn(),
}

const NONE: ActiveSessionValue = { active: null, setActive: vi.fn(), clear: vi.fn() }

function inProviders(
  ui: ReactElement,
  session: ActiveSessionValue,
  captureMode: 'hardware' | 'simulated' = 'hardware',
) {
  return (
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeContext.Provider value={{ mode: 'full', setMode: vi.fn() }}>
          <CaptureModeContext.Provider value={{ mode: captureMode, setMode: vi.fn() }}>
            <ActiveSessionContext.Provider value={session}>{ui}</ActiveSessionContext.Provider>
          </CaptureModeContext.Provider>
        </SetupModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>
  )
}

function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true'
}

async function saveWithCapture(session: ActiveSessionValue) {
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
  render(
    inProviders(
      <CurveWorkbench kind="baseline" records={[]} connected onSaved={vi.fn()} />,
      session,
    ),
  )
  fireEvent.change(screen.getByPlaceholderText(/label, e.g/), { target: { value: 'capture' } })
  const save = screen.getByText('Save curve').closest('button')!
  await waitFor(() => expect(isDisabled(save)).toBe(false))
  fireEvent.click(save)
  await waitFor(() => expect(saveCurve).toHaveBeenCalled())
}

describe('Measure > Save curve', () => {
  it('sends the active session with the save, so the server can stamp it', async () => {
    await saveWithCapture(ACTIVE)
    expect(vi.mocked(saveCurve).mock.calls[0][0].session_id).toBe('sess-1')
  })

  it('sends no session when none is active', async () => {
    await saveWithCapture(NONE)
    expect(vi.mocked(saveCurve).mock.calls[0][0].session_id).toBeNull()
  })
})

const RUN_CONFIG = {
  algorithms: ['P&O', 'InCond'],
  maxDurationS: 600,
  defaultDurationS: 10,
  defaultInitialDuty: 0.5,
  defaultVMax: 40,
  defaultIMax: 1,
  defaultVOutMax: 25,
}

async function startWith(session: ActiveSessionValue, captureMode: 'hardware' | 'simulated') {
  vi.mocked(fetchRunConfig).mockResolvedValue(RUN_CONFIG)
  vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
  vi.mocked(startRun).mockResolvedValue({
    status: 'running',
    algorithm: 'P&O',
    label: 'x',
    duration_s: 10,
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(
    inProviders(
      <RunPane curves={[]} connectionStatus="connected" onRunSaved={vi.fn()} />,
      session,
      captureMode,
    ),
  )
  await waitFor(() => expect(screen.getByText('InCond')).toBeTruthy())
  fireEvent.change(screen.getByLabelText('Algorithm'), { target: { value: 'P&O' } })
  fireEvent.click(screen.getByText(captureMode === 'simulated' ? 'Start simulated run' : 'Start run'))
  await waitFor(() => expect(startRun).toHaveBeenCalled())
}

describe('Measure > Run form', () => {
  it('sends the active session when starting a run', async () => {
    await startWith(ACTIVE, 'hardware')
    expect(vi.mocked(startRun).mock.calls[0][0].session_id).toBe('sess-1')
  })

  it('sends no session when none is active', async () => {
    await startWith(NONE, 'hardware')
    expect(vi.mocked(startRun).mock.calls[0][0].session_id).toBeNull()
  })

  it('files nothing in demo mode, even with a session remembered', async () => {
    await startWith(ACTIVE, 'simulated')
    expect(vi.mocked(startRun).mock.calls[0][0].session_id).toBeNull()
  })

  it('says which session the run will be filed into', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue(RUN_CONFIG)
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    render(
      inProviders(
        <RunPane curves={[]} connectionStatus="connected" onRunSaved={vi.fn()} />,
        ACTIVE,
      ),
    )
    await waitFor(() =>
      expect(screen.getByTestId('active-session-notice').textContent).toContain('Panel A alone'),
    )
  })
})

describe('Measure pane', () => {
  function pane() {
    const byKind = new Map<string, CurveRecord[]>([['baseline', []]])
    return (
      <MeasurePane
        kinds={['baseline']}
        byKind={byKind}
        curves={[]}
        connected
        connectionStatus="connected"
        onSaved={vi.fn()}
        onRunSaved={vi.fn()}
      />
    )
  }

  it('says which session the next curve will be filed into', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchRunConfig).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    render(inProviders(pane(), ACTIVE))
    expect(screen.getByTestId('active-session-notice').textContent).toContain(
      'This curve will be filed into session',
    )
    expect(screen.getByTestId('active-session-notice').textContent).toContain('Panel A alone')
  })

  it('says plainly that nothing is filed when no session is active', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchRunConfig).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    render(inProviders(pane(), NONE))
    expect(screen.getByTestId('active-session-notice').textContent).toContain(
      'Not filed into any session',
    )
  })
})
