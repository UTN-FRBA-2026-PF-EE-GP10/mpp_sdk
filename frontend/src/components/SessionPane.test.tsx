import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionPane } from './SessionPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { DEMO_SESSION, DEMO_RUN } from '@/lib/demoFixtures'
import type { SessionRecord } from '@/lib/sessions'
import type { RunDetail, RunSummary } from '@/lib/runs'

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

vi.mock('@/lib/api', () => ({
  fetchSession: vi.fn(),
  fetchRun: vi.fn(),
  patchSession: vi.fn(),
  deleteSession: vi.fn(),
}))

import { deleteSession, fetchRun, fetchSession, patchSession } from '@/lib/api'

function renderPane(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function session(overrides: Partial<SessionRecord> = {}): SessionRecord {
  return {
    id: 'r1',
    title: 'Panel A alone',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:00:00+00:00',
    fields: {},
    steps: [
      {
        id: 'po-run',
        section: 'Runs',
        title: 'P&O run',
        instructions: '',
        kind: 'run',
        status: 'todo',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: ['r-linked'],
        repeats: 1,
      },
    ],
    open_questions: [],
    ...overrides,
  }
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'r-linked',
    path: '/data/runs/r-linked.json',
    captured_at: '2026-09-19T16:10:00Z',
    label: 'P&O run 1',
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

function runDetail(): RunDetail {
  return {
    ...runSummary(),
    downsampled: false,
    samples: [{ t: 0, v: 10, i: 0.5, d: 0.3 }],
  }
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('SessionPane - loading', () => {
  it('shows a loading state, then the session once fetched', async () => {
    vi.mocked(fetchSession).mockResolvedValue(session())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderPane(
      <SessionPane id="r1" curves={[]} runs={[runSummary()]} sandbox={false} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    expect(screen.getByText('Loading session...')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Panel A alone')).toBeTruthy())
  })

  it('surfaces a load error without crashing', async () => {
    vi.mocked(fetchSession).mockRejectedValue(new Error('session not found'))
    renderPane(
      <SessionPane id="r1" curves={[]} runs={[]} sandbox={false} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText(/Failed to load session: session not found/)).toBeTruthy())
  })

  it('lazily fetches full detail for every run a step links, to compute statistics', async () => {
    vi.mocked(fetchSession).mockResolvedValue(session())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderPane(
      <SessionPane
        id="r1"
        curves={[]}
        runs={[runSummary()]}
        sandbox={false}
        onChanged={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    await waitFor(() => expect(fetchRun).toHaveBeenCalledWith('r-linked'))
  })

  it('marks a run detail fetch that 404s as missing rather than retrying forever', async () => {
    vi.mocked(fetchSession).mockResolvedValue(session())
    vi.mocked(fetchRun).mockRejectedValue(new Error('run not found'))
    renderPane(
      <SessionPane
        id="r1"
        curves={[]}
        runs={[runSummary()]}
        sandbox={false}
        onChanged={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    await waitFor(() => expect(fetchRun).toHaveBeenCalledTimes(1))
    // Give any accidental retry a chance to happen, then confirm it didn't.
    await new Promise((r) => setTimeout(r, 50))
    expect(fetchRun).toHaveBeenCalledTimes(1)
  })
})

describe('SessionPane - sandbox', () => {
  it('shows the bundled demo session read-only, with no fetch at all', async () => {
    renderPane(
      <SessionPane
        id={DEMO_SESSION.id}
        curves={[]}
        runs={[]}
        sandbox
        onChanged={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    expect(screen.getByText(DEMO_SESSION.title)).toBeTruthy()
    expect(screen.getByText('Read-only')).toBeTruthy()
    expect(fetchSession).not.toHaveBeenCalled()
    expect(fetchRun).not.toHaveBeenCalled()
  })

  it("shows the demo run's statistics with no fetch, from the bundled fixture", async () => {
    renderPane(
      <SessionPane id={DEMO_SESSION.id} curves={[]} runs={[DEMO_RUN]} sandbox onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    expect(screen.getAllByText(/Held/).length).toBeGreaterThan(0)
  })
})

describe('SessionPane - mutation wiring', () => {
  it('calls PATCH and refreshes onChanged when SessionView edits a step', async () => {
    vi.mocked(fetchSession).mockResolvedValue(session())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    vi.mocked(patchSession).mockResolvedValue({ ...session(), title: 'Panel A alone (updated)' })
    const onChanged = vi.fn()
    renderPane(
      <SessionPane
        id="r1"
        curves={[]}
        runs={[runSummary()]}
        sandbox={false}
        onChanged={onChanged}
        onDeleted={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByText('Panel A alone')).toBeTruthy())

    const select = screen.getByLabelText('Step status') as HTMLSelectElement
    select.value = 'done'
    select.dispatchEvent(new Event('change', { bubbles: true }))

    await waitFor(() => expect(patchSession).toHaveBeenCalledWith('r1', { steps: [{ id: 'po-run', status: 'done' }] }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('calls deleteSession and onDeleted when the session is deleted', async () => {
    vi.mocked(fetchSession).mockResolvedValue(session({ steps: [] }))
    vi.mocked(deleteSession).mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onDeleted = vi.fn()
    renderPane(
      <SessionPane id="r1" curves={[]} runs={[]} sandbox={false} onChanged={vi.fn()} onDeleted={onDeleted} />,
    )
    await waitFor(() => expect(screen.getByText('Panel A alone')).toBeTruthy())

    screen.getByText('Delete session').click()

    await waitFor(() => expect(deleteSession).toHaveBeenCalledWith('r1'))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
  })
})
