import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ActiveSessionProvider } from './ActiveSessionProvider'
import { SessionPane } from './SessionPane'
import { SessionView } from './SessionView'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { ACTIVE_SESSION_STORAGE_KEY } from '@/lib/activeSession'
import { DEMO_SESSION } from '@/lib/demoFixtures'
import type { LiveSweepState } from '@/lib/api'
import type { LiveRunState, RunDetail, RunSummary } from '@/lib/runs'
import type { SessionRecord } from '@/lib/sessions'
import type { CurveRecord } from '@/types'

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

vi.mock('@/lib/api', () => ({
  fetchSession: vi.fn(),
  fetchRun: vi.fn(),
  fetchRunConfig: vi.fn(),
  fetchLiveSweep: vi.fn(),
  fetchLiveRun: vi.fn(),
  patchSession: vi.fn(),
  deleteSession: vi.fn(),
  saveCurve: vi.fn(),
  startSweep: vi.fn(),
  startRun: vi.fn(),
}))

import {
  deleteSession,
  fetchLiveRun,
  fetchLiveSweep,
  fetchRun,
  fetchRunConfig,
  fetchSession,
  patchSession,
  saveCurve,
  startRun,
  startSweep,
} from '@/lib/api'

// The capture flow polls on a real 500 ms cadence, so a whole capture takes
// about that long.
const SLOW = { timeout: 4000 }

function renderPane(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <ActiveSessionProvider>{ui}</ActiveSessionProvider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function session(overrides: Partial<SessionRecord> = {}): SessionRecord {
  const base = {
    section: 'Measure',
    instructions: '',
    status: 'todo',
    value: null,
    unit: null,
    notes: '',
    curve_ids: [] as string[],
    run_ids: [] as string[],
    repeats: 1,
  }
  return {
    id: 'sess-1',
    title: 'Panel A alone',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:00:00+00:00',
    fields: {},
    steps: [
      { ...base, id: 'sweep', title: 'Baseline sweep', kind: 'curve' },
      { ...base, id: 'po-run', title: 'P&O run', kind: 'run' },
    ],
    open_questions: [],
    ...overrides,
  }
}

function curve(overrides: Partial<CurveRecord> = {}): CurveRecord {
  return {
    id: 'c1',
    path: '/data/curves/c1.json',
    captured_at: '2026-09-19T16:00:00Z',
    label: 'Stamped sweep',
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 19,
    isc: 0.6,
    p_mpp: 7,
    points: [
      { v: 0, i: 0.6 },
      { v: 19, i: 0 },
    ],
    ...overrides,
  }
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'r1',
    path: '/data/runs/r1.json',
    captured_at: '2026-09-19T16:10:00Z',
    label: 'Stamped run',
    algorithm: 'P&O',
    n_samples: 2,
    duration_s: 10,
    aborted: false,
    curve_ref: null,
    notes: '',
    source: 'hardware',
    ...overrides,
  }
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runSummary(),
    downsampled: false,
    samples: [{ t: 0, v: 10, i: 0.5, d: 0.3 }],
    ...overrides,
  }
}

function sweepState(overrides: Partial<LiveSweepState> = {}): LiveSweepState {
  return {
    points: [],
    partial: [],
    active: false,
    link: 'ok',
    seq: 1,
    commandError: null,
    demoSource: false,
    ...overrides,
  }
}

function doneRun(overrides: Partial<LiveRunState> = {}): LiveRunState {
  return {
    status: 'done',
    algorithm: 'P&O',
    label: 'P&O run',
    curve_ref: null,
    n_samples: 2,
    downsampled: false,
    samples: [],
    voltage: null,
    current: null,
    duty: null,
    vout: null,
    aborted: false,
    abort_reason: null,
    saved_run_id: 'run-new',
    source: 'hardware',
    ...overrides,
  }
}

function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true'
}

function paneFor(props: Partial<Parameters<typeof SessionPane>[0]> = {}) {
  return (
    <SessionPane
      id="sess-1"
      curves={[]}
      runs={[]}
      sandbox={false}
      onChanged={vi.fn()}
      onDeleted={vi.fn()}
      {...props}
    />
  )
}

beforeEach(() => {
  vi.mocked(fetchSession).mockResolvedValue(session())
  vi.mocked(fetchRunConfig).mockResolvedValue({
    algorithms: ['P&O', 'InCond'],
    maxDurationS: 600,
    defaultDurationS: 0,
    defaultInitialDuty: 0.5,
    defaultVMax: 40,
    defaultIMax: 1,
    defaultVOutMax: 25,
  })
  vi.mocked(fetchRun).mockResolvedValue(runDetail())
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('Capture into this step - curve step', () => {
  it('sweeps, saves stamped with this session, then links the new curve to the step', async () => {
    vi.mocked(fetchLiveSweep)
      .mockResolvedValueOnce(sweepState())
      .mockResolvedValue(sweepState({ seq: 2, points: [{ v: 10, i: 0.1 }] }))
    vi.mocked(startSweep).mockResolvedValue()
    vi.mocked(saveCurve).mockResolvedValue({ path: '/data/curves/new.json', id: 'new-curve' })
    vi.mocked(patchSession).mockResolvedValue(
      session({
        steps: [
          { ...session().steps[0], curve_ids: ['new-curve'] },
          session().steps[1],
        ],
      }),
    )
    const onChanged = vi.fn()
    renderPane(paneFor({ onChanged }))
    await screen.findByText('Baseline sweep')

    fireEvent.click(screen.getAllByText('Capture into this step')[0])

    await waitFor(
      () =>
        expect(patchSession).toHaveBeenCalledWith('sess-1', {
          steps: [{ id: 'sweep', curve_ids: ['new-curve'] }],
        }),
      SLOW,
    )
    expect(saveCurve).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'sess-1' }))
    expect(onChanged).toHaveBeenCalled()
    // Saved before linked.
    expect(vi.mocked(saveCurve).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(patchSession).mock.invocationCallOrder[0],
    )
  })

  it('a failed capture leaves the step untouched: nothing saved, nothing linked, error shown', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(sweepState())
    vi.mocked(startSweep).mockRejectedValue(new Error('POST /api/start-sweep: HTTP 500'))
    renderPane(paneFor())
    await screen.findByText('Baseline sweep')

    fireEvent.click(screen.getAllByText('Capture into this step')[0])

    await screen.findByText(/Capture failed: POST \/api\/start-sweep: HTTP 500/)
    expect(saveCurve).not.toHaveBeenCalled()
    expect(patchSession).not.toHaveBeenCalled()
    // Ready to try again.
    expect(isDisabled(screen.getAllByText('Capture into this step')[0].closest('button')!)).toBe(false)
  })

  it('a sweep that finishes but cannot be saved links nothing', async () => {
    vi.mocked(fetchLiveSweep)
      .mockResolvedValueOnce(sweepState())
      .mockResolvedValue(sweepState({ seq: 2, points: [{ v: 10, i: 0.1 }] }))
    vi.mocked(startSweep).mockResolvedValue()
    vi.mocked(saveCurve).mockRejectedValue(new Error('POST /api/save-curve: session not found'))
    renderPane(paneFor())
    await screen.findByText('Baseline sweep')

    fireEvent.click(screen.getAllByText('Capture into this step')[0])

    await screen.findByText(/session not found/, undefined, SLOW)
    expect(patchSession).not.toHaveBeenCalled()
  })

  it('is disabled with the reason when there is no live link, and does nothing when clicked', async () => {
    renderPane(
      paneFor({ captureUnavailable: { curve: 'No live link to the board', run: null } }),
    )
    await screen.findByText('Baseline sweep')

    const button = screen.getAllByText('Capture into this step')[0].closest('button')!
    expect(isDisabled(button)).toBe(true)
    expect(screen.getByText('No live link to the board')).toBeTruthy()
    fireEvent.click(button)
    expect(startSweep).not.toHaveBeenCalled()
  })

  it('keeps the existing picker and "link most recent" alongside it', async () => {
    renderPane(paneFor({ curves: [curve()] }))
    await screen.findByText('Baseline sweep')
    expect(screen.getByText('Link most recent curve')).toBeTruthy()
    expect(screen.getByLabelText('Pick a curve to link')).toBeTruthy()
  })
})

describe('Capture into this step - run step', () => {
  it('confirms (it drives the real converter), then starts the run stamped with this session and links it', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O run',
      duration_s: 0,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(doneRun())
    vi.mocked(patchSession).mockResolvedValue(session())
    renderPane(paneFor())
    await screen.findByText('P&O run', { selector: 'p' })

    fireEvent.click(screen.getAllByText('Capture into this step')[1])

    await waitFor(
      () =>
        expect(patchSession).toHaveBeenCalledWith('sess-1', {
          steps: [{ id: 'po-run', run_ids: ['run-new'] }],
        }),
      SLOW,
    )
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('drives the real converter'))
    expect(startRun).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'sess-1' }))
  })

  it('starts nothing when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPane(paneFor())
    await screen.findByText('P&O run', { selector: 'p' })

    fireEvent.click(screen.getAllByText('Capture into this step')[1])

    await new Promise((r) => setTimeout(r, 30))
    expect(startRun).not.toHaveBeenCalled()
    expect(patchSession).not.toHaveBeenCalled()
  })

  it('a run the server refuses leaves the step untouched', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(startRun).mockRejectedValue(new Error('POST /api/runs/start: a run is already in progress'))
    renderPane(paneFor())
    await screen.findByText('P&O run', { selector: 'p' })

    fireEvent.click(screen.getAllByText('Capture into this step')[1])

    await screen.findByText(/already in progress/)
    expect(patchSession).not.toHaveBeenCalled()
  })
})

describe('Capture into this step - read-only gating', () => {
  it('is not offered in demo (sandbox) mode', async () => {
    renderPane(paneFor({ id: DEMO_SESSION.id, sandbox: true }))
    await screen.findByText(DEMO_SESSION.title)
    expect(screen.queryByText('Capture into this step')).toBeNull()
  })

  it('is not offered while viewing an imported session file (SessionView readOnly)', () => {
    renderPane(<SessionView session={session()} curves={[]} runs={[]} readOnly />)
    expect(screen.queryByText('Capture into this step')).toBeNull()
  })

  it('is not offered when the container supplies no capture handler', () => {
    renderPane(<SessionView session={session()} curves={[]} runs={[]} readOnly={false} />)
    expect(screen.queryByText('Capture into this step')).toBeNull()
  })

  it('never calls the handler in read-only mode, even if one is supplied', () => {
    const onCapture = vi.fn()
    renderPane(
      <SessionView
        session={session()}
        curves={[]}
        runs={[]}
        readOnly
        onCaptureIntoStep={onCapture}
      />,
    )
    expect(screen.queryByText('Capture into this step')).toBeNull()
  })
})

describe('SessionPane and the active session', () => {
  it('makes the opened session the one new captures are filed into', async () => {
    renderPane(paneFor())
    await screen.findByText('Baseline sweep')
    await waitFor(() =>
      expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBe(
        JSON.stringify({ id: 'sess-1', title: 'Panel A alone' }),
      ),
    )
  })

  it('does not, in demo mode', async () => {
    renderPane(paneFor({ id: DEMO_SESSION.id, sandbox: true }))
    await screen.findByText(DEMO_SESSION.title)
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('stops filing into a session once it is deleted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(deleteSession).mockResolvedValue(undefined)
    const onDeleted = vi.fn()
    renderPane(paneFor({ onDeleted }))
    await screen.findByText('Baseline sweep')
    await waitFor(() => expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).not.toBeNull())

    fireEvent.click(screen.getByText('Delete session'))

    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
  })
})

describe('Captured in this session, not linked to a step', () => {
  it('lists curves and runs stamped with this session that no step links', async () => {
    renderPane(
      paneFor({
        curves: [
          curve({ id: 'c-mine', label: 'Filed here', session_id: 'sess-1' }),
          curve({ id: 'c-other', label: 'Filed elsewhere', session_id: 'sess-2' }),
          curve({ id: 'c-none', label: 'Never filed' }),
        ],
        runs: [runSummary({ id: 'r-mine', label: 'Run filed here', session_id: 'sess-1' })],
      }),
    )
    await screen.findByText('Captured in this session, not linked to a step')
    expect(screen.getByText('Filed here')).toBeTruthy()
    expect(screen.getByText('Run filed here')).toBeTruthy()
    expect(screen.queryByText('Filed elsewhere')).toBeNull()
    expect(screen.queryByText('Never filed')).toBeNull()
  })

  it('does not list an item a step already links', async () => {
    vi.mocked(fetchSession).mockResolvedValue(
      session({
        steps: [{ ...session().steps[0], curve_ids: ['c-mine'] }],
      }),
    )
    renderPane(paneFor({ curves: [curve({ id: 'c-mine', session_id: 'sess-1' })] }))
    await screen.findByText('Baseline sweep')
    expect(screen.queryByText('Captured in this session, not linked to a step')).toBeNull()
  })

  it('links a listed curve to a step through the picker', async () => {
    vi.mocked(patchSession).mockResolvedValue(session())
    renderPane(paneFor({ curves: [curve({ id: 'c-mine', label: 'Filed here', session_id: 'sess-1' })] }))
    await screen.findByText('Filed here')

    const picker = screen.getByLabelText('Step to link "Filed here" to')
    fireEvent.change(picker, { target: { value: 'sweep' } })
    fireEvent.click(within(picker.parentElement!).getByText('Link'))

    await waitFor(() =>
      expect(patchSession).toHaveBeenCalledWith('sess-1', {
        steps: [{ id: 'sweep', curve_ids: ['c-mine'] }],
      }),
    )
  })

  it('fetches full detail for a stamped run no step links, so an export can include it', async () => {
    renderPane(paneFor({ runs: [runSummary({ id: 'r-mine', session_id: 'sess-1' })] }))
    await waitFor(() => expect(fetchRun).toHaveBeenCalledWith('r-mine'))
  })

  it('shows the list read-only, without link controls', () => {
    renderPane(
      <SessionView
        session={session()}
        curves={[curve({ id: 'c-mine', label: 'Filed here', session_id: 'sess-1' })]}
        runs={[]}
        readOnly
      />,
    )
    expect(screen.getByText('Filed here')).toBeTruthy()
    expect(screen.queryByLabelText('Step to link "Filed here" to')).toBeNull()
  })

  it('a stamp pointing at a deleted session simply does not appear here, and nothing crashes', async () => {
    renderPane(
      paneFor({ curves: [curve({ id: 'c-orphan', label: 'Orphan', session_id: 'deleted-session' })] }),
    )
    await screen.findByText('Baseline sweep')
    expect(screen.queryByText('Orphan')).toBeNull()
  })
})
