import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunPlayerDialog } from './RunPlayerDialog'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
}))

import { deleteRun, fetchRun } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

function renderDialog(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function renderDialogInSandbox(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
          {ui}
        </CaptureModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: '20260913T080000Z-po-run',
    path: '/data/runs/20260913T080000Z-po-run.json',
    captured_at: '2026-09-13T08:00:00Z',
    label: 'P&O bench run',
    algorithm: 'P&O',
    n_samples: 3,
    duration_s: 2,
    aborted: false,
    curve_ref: null,
    notes: '',
    ...overrides,
  }
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runSummary(),
    downsampled: false,
    samples: [
      { t: 0, v: 10, i: 0.2, d: 0.3 },
      { t: 1, v: 15, i: 0.18, d: 0.4 },
      { t: 2, v: 18, i: 0.15, d: 0.45 },
    ],
    ...overrides,
  }
}

function curveRecord(path: string): CurveRecord {
  return {
    id: path,
    path,
    captured_at: '2026-09-13T07:00:00Z',
    label: 'baseline',
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 21.3,
    isc: 0.215,
    p_mpp: 3.51,
    points: [
      { v: 0, i: 0.215 },
      { v: 21.3, i: 0 },
    ],
  }
}

describe('RunPlayerDialog', () => {
  it('renders nothing when no run is selected', () => {
    renderDialog(<RunPlayerDialog run={null} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />)
    expect(screen.queryByText('Untitled run')).toBeNull()
  })

  it('shows a loading state before the run detail arrives', () => {
    vi.mocked(fetchRun).mockReturnValue(new Promise(() => {}))
    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    expect(screen.getByText('Loading run...')).toBeTruthy()
  })

  it('says so when the run has no reference curve', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() =>
      expect(screen.getByText('No reference curve was captured for this run.')).toBeTruthy(),
    )
  })

  it('says the reference curve is missing, distinctly from never having one', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail({ curve_ref: 'gone.json' }))
    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() =>
      expect(screen.getByText(/Reference curve "gone.json" was not found/)).toBeTruthy(),
    )
  })

  it('shows no missing-reference message once the curve resolves', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail({ curve_ref: 'a.json' }))
    renderDialog(
      <RunPlayerDialog
        run={runSummary()}
        curves={[curveRecord('/data/curves/a.json')]}
        onClose={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByLabelText('Playback position')).toBeTruthy())
    expect(screen.queryByText(/No reference curve/)).toBeNull()
    expect(screen.queryByText(/was not found/)).toBeNull()
  })

  it('marks an aborted run unmistakably', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail({ aborted: true }))
    renderDialog(
      <RunPlayerDialog
        run={runSummary({ aborted: true })}
        curves={[]}
        onClose={vi.fn()}
        onDeleted={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getAllByText('Aborted').length).toBeGreaterThan(0))
    expect(screen.getByText(/safety cutoff fired/)).toBeTruthy()
  })

  it('flags a downsampled trace instead of showing it silently', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail({ downsampled: true, n_samples: 50000 }))
    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText(/downsampled for playback/)).toBeTruthy())
    expect(screen.getByText(/of 50000 samples/)).toBeTruthy()
  })

  it('shows the first sample\'s readouts as soon as the run loads, paused', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText('0.00 s')).toBeTruthy())
    expect(screen.getByText('10.00 V')).toBeTruthy()
    expect(screen.getByLabelText('Play')).toBeTruthy()
  })

  it('deletes only after confirming, then reports success upward', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    vi.mocked(deleteRun).mockResolvedValue(undefined)
    const onDeleted = vi.fn()
    const onClose = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={onClose} onDeleted={onDeleted} />,
    )
    await waitFor(() => expect(screen.getByText('Delete run')).toBeTruthy())
    fireEvent.click(screen.getByText('Delete run'))

    await waitFor(() => expect(deleteRun).toHaveBeenCalledWith('20260913T080000Z-po-run'))
    expect(onDeleted).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('does not delete when the confirmation is declined', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    const onDeleted = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderDialog(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={onDeleted} />,
    )
    await waitFor(() => expect(screen.getByText('Delete run')).toBeTruthy())
    fireEvent.click(screen.getByText('Delete run'))

    expect(deleteRun).not.toHaveBeenCalled()
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('disables delete in demo mode and explains why, instead of leaving it silently dead', async () => {
    vi.mocked(fetchRun).mockResolvedValue(runDetail())
    renderDialogInSandbox(
      <RunPlayerDialog run={runSummary()} curves={[]} onClose={vi.fn()} onDeleted={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText('Delete run')).toBeTruthy())

    const button = screen.getByText('Delete run').closest('button')
    expect(button?.disabled).toBe(true)
    expect(screen.getByText(/unavailable in demo mode/i)).toBeTruthy()

    fireEvent.click(screen.getByText('Delete run'))
    expect(deleteRun).not.toHaveBeenCalled()
  })
})
