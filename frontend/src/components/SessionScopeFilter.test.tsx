import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActiveSessionProvider } from './ActiveSessionProvider'
import { CurveCategoryPane } from './CurveCategoryPane'
import { RunDatePane } from './RunDatePane'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { ACTIVE_SESSION_STORAGE_KEY } from '@/lib/activeSession'
import { CaptureModeContext } from '@/lib/captureMode'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'
import type { RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  deleteCurvesBatch: vi.fn(),
  deleteRunsBatch: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
}))

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function rememberSession() {
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, '{"id":"s1","title":"Panel A alone"}')
}

function renderPane(ui: Parameters<typeof render>[0], extra?: (children: ReactNode) => ReactNode) {
  const inner = extra ? extra(ui) : ui
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeProvider>
          <ActiveSessionProvider>{inner}</ActiveSessionProvider>
        </SetupModeProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function curve(id: string, session_id?: string | null): CurveRecord {
  return {
    id,
    path: `/data/curves/${id}.json`,
    captured_at: '2026-09-13T08:00:00Z',
    label: `curve ${id}`,
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
    ...(session_id === undefined ? {} : { session_id }),
  }
}

function run(id: string, session_id?: string | null): RunSummary {
  return {
    id,
    path: `/data/runs/${id}.json`,
    captured_at: '2026-09-13T08:00:00Z',
    label: `run ${id}`,
    algorithm: 'P&O',
    n_samples: 10,
    duration_s: 1,
    aborted: false,
    curve_ref: null,
    notes: '',
    source: 'hardware',
    ...(session_id === undefined ? {} : { session_id }),
  }
}

const CURVES = [
  curve('mine', 's1'),
  curve('other', 's2'),
  curve('orphan', 'deleted-session'),
  curve('plain', null),
  curve('old'),
]
const RUNS = [
  run('mine', 's1'),
  run('other', 's2'),
  run('orphan', 'deleted-session'),
  run('plain', null),
  run('old'),
]

const VIEWING: ImportedSessionValue = {
  active: true,
  title: 'A file',
  setup: null,
  session: null,
  curves: [],
  runs: [],
  missing: { curve_ids: [], run_ids: [] },
  enter: () => {},
  close: () => {},
}

describe('Curves list session filter', () => {
  it('offers no filter while no session is active', () => {
    renderPane(<CurveCategoryPane kind="baseline" records={CURVES} />)
    expect(screen.queryByText('This session')).toBeNull()
    expect(screen.getAllByText(/^curve /).length).toBe(5)
  })

  it('shows everything by default, and only this session\'s curves after "This session"', () => {
    rememberSession()
    renderPane(<CurveCategoryPane kind="baseline" records={CURVES} />)
    expect(screen.getAllByText(/^curve /).length).toBe(5)

    fireEvent.click(screen.getByText('This session'))
    expect(screen.getAllByText(/^curve /).map((e) => e.textContent)).toEqual(['curve mine'])

    fireEvent.click(screen.getByText('Everything'))
    expect(screen.getAllByText(/^curve /).length).toBe(5)
  })

  it('a stamp naming a deleted session is shown under everything and never under this session', () => {
    rememberSession()
    renderPane(<CurveCategoryPane kind="baseline" records={CURVES} />)
    expect(screen.getByText('curve orphan')).toBeTruthy()
    fireEvent.click(screen.getByText('This session'))
    expect(screen.queryByText('curve orphan')).toBeNull()
  })

  it('says so when nothing under this kind was captured in the session', () => {
    rememberSession()
    renderPane(<CurveCategoryPane kind="baseline" records={[curve('other', 's2')]} />)
    fireEvent.click(screen.getByText('This session'))
    expect(screen.getByText(/were captured in this session/)).toBeTruthy()
  })

  it('has no filter in demo mode', () => {
    rememberSession()
    renderPane(<CurveCategoryPane kind="baseline" records={CURVES} />, (children) => (
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        {children}
      </CaptureModeContext.Provider>
    ))
    expect(screen.queryByText('This session')).toBeNull()
  })

  it('has no filter while viewing an imported session file', () => {
    rememberSession()
    renderPane(<CurveCategoryPane kind="baseline" records={CURVES} />, (children) => (
      <ImportedSessionContext.Provider value={VIEWING}>{children}</ImportedSessionContext.Provider>
    ))
    expect(screen.queryByText('This session')).toBeNull()
  })
})

describe('Runs list session filter', () => {
  function pane() {
    return <RunDatePane date="2026-09-13" runs={RUNS} curves={[]} onRunsChanged={vi.fn()} />
  }

  it('offers no filter while no session is active', () => {
    renderPane(pane())
    expect(screen.queryByText('This session')).toBeNull()
    expect(screen.getAllByText(/^run /).length).toBe(5)
  })

  it('narrows to this session\'s runs and back', () => {
    rememberSession()
    renderPane(pane())
    fireEvent.click(screen.getByText('This session'))
    expect(screen.getAllByText(/^run /).map((e) => e.textContent)).toEqual(['run mine'])
    fireEvent.click(screen.getByText('Everything'))
    expect(screen.getAllByText(/^run /).length).toBe(5)
  })

  it('a stamp naming a deleted session is shown under everything and never under this session', () => {
    rememberSession()
    renderPane(pane())
    expect(screen.getByText('run orphan')).toBeTruthy()
    fireEvent.click(screen.getByText('This session'))
    expect(screen.queryByText('run orphan')).toBeNull()
  })

  it('has no filter in demo mode', () => {
    rememberSession()
    renderPane(pane(), (children) => (
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        {children}
      </CaptureModeContext.Provider>
    ))
    expect(screen.queryByText('This session')).toBeNull()
  })

  it('has no filter while viewing an imported session file', () => {
    rememberSession()
    renderPane(pane(), (children) => (
      <ImportedSessionContext.Provider value={VIEWING}>{children}</ImportedSessionContext.Provider>
    ))
    expect(screen.queryByText('This session')).toBeNull()
  })
})
