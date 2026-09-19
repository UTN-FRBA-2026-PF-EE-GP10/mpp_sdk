import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunDatePane } from './RunDatePane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import type { RunSummary } from '@/lib/runs'

vi.mock('@/lib/api', () => ({
  deleteRunsBatch: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
}))

import { deleteRunsBatch } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

// RunPlayerDialog (rendered by RunDatePane, closed by default here) reads
// the theme via useTheme - the provider is enough, no UnitsProvider is
// needed since none of these tests open a run.
function renderPane(ui: Parameters<typeof render>[0]) {
  return render(<ThemeProvider>{ui}</ThemeProvider>)
}

function renderPaneInSandbox(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        {ui}
      </CaptureModeContext.Provider>
    </ThemeProvider>,
  )
}

function run(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'run-a',
    path: '/data/runs/run-a.json',
    captured_at: '2026-09-13T08:00:00Z',
    label: 'run a',
    algorithm: 'P&O',
    n_samples: 100,
    duration_s: 5.0,
    aborted: false,
    curve_ref: null,
    notes: '',
    source: 'hardware',
    ...overrides,
  }
}

function twoRuns(): RunSummary[] {
  return [run({ id: 'run-a', label: 'run a' }), run({ id: 'run-b', label: 'run b' })]
}

describe('RunDatePane - batch delete', () => {
  it('has no Select toggle when no runs were captured this date', () => {
    renderPane(<RunDatePane date="2026-09-13" runs={[]} curves={[]} onRunsChanged={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Select' })).toBeNull()
  })

  it('shows a checkbox per row once Select is toggled on', () => {
    renderPane(
      <RunDatePane date="2026-09-13" runs={twoRuns()} curves={[]} onRunsChanged={vi.fn()} />,
    )
    expect(screen.queryByLabelText('Select "run a" for batch delete')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Select' }))

    expect(screen.getByLabelText('Select "run a" for batch delete')).toBeTruthy()
    expect(screen.getByLabelText('Select "run b" for batch delete')).toBeTruthy()
  })

  it('names the count in one confirm, then deletes the selected runs and refreshes', async () => {
    vi.mocked(deleteRunsBatch).mockResolvedValue({ deleted: ['run-a'], failed: [] })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onRunsChanged = vi.fn()

    renderPane(
      <RunDatePane
        date="2026-09-13"
        runs={twoRuns()}
        curves={[]}
        onRunsChanged={onRunsChanged}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "run a" for batch delete'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 1 selected/ }))

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(confirmSpy.mock.calls[0][0]).toContain('1 selected run')
    expect(confirmSpy.mock.calls[0][0]).toContain('2026-09-13')

    await waitFor(() => expect(deleteRunsBatch).toHaveBeenCalledWith(['run-a']))
    await waitFor(() => expect(onRunsChanged).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByRole('button', { name: 'Select' })).toBeTruthy())
  })

  it('deletes nothing when the confirmation is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderPane(
      <RunDatePane date="2026-09-13" runs={twoRuns()} curves={[]} onRunsChanged={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "run a" for batch delete'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 1 selected/ }))

    expect(deleteRunsBatch).not.toHaveBeenCalled()
  })

  it('on a partial failure, reports which run failed and keeps only it selected', async () => {
    vi.mocked(deleteRunsBatch).mockResolvedValue({
      deleted: ['run-a'],
      failed: [{ id: 'run-b', error: 'boom' }],
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderPane(
      <RunDatePane date="2026-09-13" runs={twoRuns()} curves={[]} onRunsChanged={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select all'))
    fireEvent.click(screen.getByRole('button', { name: /Delete 2 selected/ }))

    await waitFor(() => expect(screen.getByText(/Failed to delete 1 run/)).toBeTruthy())
    expect(screen.getByText(/run b.*boom/)).toBeTruthy()
    const checkbox = screen.getByLabelText('Select "run b" for batch delete') as HTMLInputElement
    expect(checkbox.checked).toBe(true)
  })

  it('is unavailable in demo (simulated) mode - the button is disabled and nothing is ever sent', () => {
    const confirmSpy = vi.spyOn(window, 'confirm')

    renderPaneInSandbox(
      <RunDatePane date="2026-09-13" runs={twoRuns()} curves={[]} onRunsChanged={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    fireEvent.click(screen.getByLabelText('Select "run a" for batch delete'))

    // Distinct from RunPlayerDialog's own single-run delete button, which
    // is not even mounted here (no row is open) but shares the same
    // disabled title text elsewhere in the app - matched by its visible
    // "Delete 1 selected" label instead.
    const button = screen.getByRole('button', { name: /Delete 1 selected/ })
    expect(button.getAttribute('aria-disabled')).toBe('true')
    expect(button.getAttribute('title')).toBe('Deleting is unavailable in demo mode')

    fireEvent.click(button)
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(deleteRunsBatch).not.toHaveBeenCalled()
  })
})
