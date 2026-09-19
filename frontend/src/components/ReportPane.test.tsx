import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportPane } from './ReportPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { DEMO_REPORT, DEMO_RUN } from '@/lib/demoFixtures'
import type { ReportRecord } from '@/lib/reports'
import type { RunDetail, RunSummary } from '@/lib/runs'

vi.mock('react-chartjs-2', () => ({ Line: () => null }))

vi.mock('@/lib/api', () => ({
  fetchReport: vi.fn(),
  fetchRun: vi.fn(),
  patchReport: vi.fn(),
  deleteReport: vi.fn(),
}))

import { deleteReport, fetchReport, fetchRun, patchReport } from '@/lib/api'

function renderPane(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function report(overrides: Partial<ReportRecord> = {}): ReportRecord {
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

describe('ReportPane - loading', () => {
  it('shows a loading state, then the report once fetched', async () => {
    vi.mocked(fetchReport).mockResolvedValue(report())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderPane(
      <ReportPane id="r1" curves={[]} runs={[runSummary()]} sandbox={false} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    expect(screen.getByText('Loading report...')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Panel A alone')).toBeTruthy())
  })

  it('surfaces a load error without crashing', async () => {
    vi.mocked(fetchReport).mockRejectedValue(new Error('report not found'))
    renderPane(
      <ReportPane id="r1" curves={[]} runs={[]} sandbox={false} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText(/Failed to load report: report not found/)).toBeTruthy())
  })

  it('lazily fetches full detail for every run a step links, to compute statistics', async () => {
    vi.mocked(fetchReport).mockResolvedValue(report())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderPane(
      <ReportPane
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
    vi.mocked(fetchReport).mockResolvedValue(report())
    vi.mocked(fetchRun).mockRejectedValue(new Error('run not found'))
    renderPane(
      <ReportPane
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

describe('ReportPane - sandbox', () => {
  it('shows the bundled demo report read-only, with no fetch at all', async () => {
    renderPane(
      <ReportPane
        id={DEMO_REPORT.id}
        curves={[]}
        runs={[]}
        sandbox
        onChanged={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    expect(screen.getByText(DEMO_REPORT.title)).toBeTruthy()
    expect(screen.getByText('Read-only')).toBeTruthy()
    expect(fetchReport).not.toHaveBeenCalled()
    expect(fetchRun).not.toHaveBeenCalled()
  })

  it("shows the demo run's statistics with no fetch, from the bundled fixture", async () => {
    renderPane(
      <ReportPane id={DEMO_REPORT.id} curves={[]} runs={[DEMO_RUN]} sandbox onChanged={vi.fn()} onDeleted={vi.fn()} />,
    )
    expect(screen.getAllByText(/Held/).length).toBeGreaterThan(0)
  })
})

describe('ReportPane - mutation wiring', () => {
  it('calls PATCH and refreshes onChanged when ReportView edits a step', async () => {
    vi.mocked(fetchReport).mockResolvedValue(report())
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    vi.mocked(patchReport).mockResolvedValue({ ...report(), title: 'Panel A alone (updated)' })
    const onChanged = vi.fn()
    renderPane(
      <ReportPane
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

    await waitFor(() => expect(patchReport).toHaveBeenCalledWith('r1', { steps: [{ id: 'po-run', status: 'done' }] }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('calls deleteReport and onDeleted when the report is deleted', async () => {
    vi.mocked(fetchReport).mockResolvedValue(report({ steps: [] }))
    vi.mocked(deleteReport).mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onDeleted = vi.fn()
    renderPane(
      <ReportPane id="r1" curves={[]} runs={[]} sandbox={false} onChanged={vi.fn()} onDeleted={onDeleted} />,
    )
    await waitFor(() => expect(screen.getByText('Panel A alone')).toBeTruthy())

    screen.getByText('Delete report').click()

    await waitFor(() => expect(deleteReport).toHaveBeenCalledWith('r1'))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
  })
})
