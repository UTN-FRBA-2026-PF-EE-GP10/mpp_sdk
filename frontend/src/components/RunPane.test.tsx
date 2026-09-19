import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunPane } from './RunPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import { DEMO_CURVES } from '@/lib/demoFixtures'
import type { LiveRunState, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchRunConfig: vi.fn(),
  fetchRuns: vi.fn(),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  fetchLiveRun: vi.fn(),
}))

// jsdom has no real 2D canvas context, so the genuine chart.js instance
// (used elsewhere in this file's tests) silently draws nothing - fine for
// tests that only check surrounding text, but not enough to prove the
// grey reference curve actually reaches the chart. Stand in for the real
// Line component here and surface the dataset shape RunChart built as
// plain DOM attributes, so a test can assert on it directly instead of
// trusting that a prop was merely passed somewhere upstream.
vi.mock('react-chartjs-2', () => ({
  Line: ({ data }: { data: { datasets: { label: string; data: unknown[] }[] } }) => (
    <div
      data-testid="run-chart"
      data-datasets={JSON.stringify(data.datasets.map((d) => ({ label: d.label, n: d.data.length })))}
    />
  ),
}))

import { fetchLiveRun, fetchRun, fetchRunConfig, fetchRuns, startRun, stopRun } from '@/lib/api'

/** The dataset shapes every currently mounted RunChart was actually
 * handed - label plus point count, enough to tell "no reference" from
 * "the chosen curve's reference, in full" without decoding chart.js's own
 * internal state. */
function chartDatasets(scope: HTMLElement = document.body): { label: string; n: number }[] {
  return within(scope)
    .getAllByTestId('run-chart')
    .flatMap((el) => JSON.parse(el.getAttribute('data-datasets') ?? '[]'))
}

function renderPane(curves: CurveRecord[] = []) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <RunPane curves={curves} connectionStatus="connected" onRunSaved={vi.fn()} />
      </UnitsProvider>
    </ThemeProvider>,
  )
}

/** Demo (sandbox) mode - the connector is never live from the app's own
 * perspective (there is no board at all), so `connectionStatus` here is
 * 'disconnected', the same as App.tsx would report with polling turned
 * off. A simulated run must still be startable through this. */
function renderPaneInSandbox(curves: CurveRecord[] = []) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
          <RunPane curves={curves} connectionStatus="disconnected" onRunSaved={vi.fn()} />
        </CaptureModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

/** Waits for the algorithm roster to load, then explicitly picks one -
 * see the note above on why this is more reliable than waiting for the
 * select's own displayed value. */
async function selectAlgorithm(label: string) {
  await waitFor(() => expect(screen.getByText(label)).toBeTruthy())
  fireEvent.change(screen.getByLabelText('Algorithm'), { target: { value: label } })
}

function liveState(overrides: Partial<LiveRunState> = {}): LiveRunState {
  return {
    status: 'running',
    algorithm: 'P&O',
    label: 'bench run',
    curve_ref: null,
    n_samples: 1,
    downsampled: false,
    samples: [{ t: 0, v: 12, i: 0.25, d: 0.4 }],
    voltage: 12,
    current: 0.25,
    duty: 0.4,
    vout: 28,
    aborted: false,
    abort_reason: null,
    saved_run_id: null,
    source: 'hardware',
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('RunPane', () => {
  it('blocks starting when there is no live link to the board', () => {
    vi.mocked(fetchRunConfig).mockReturnValue(new Promise(() => {}))
    render(
      <ThemeProvider>
        <UnitsProvider>
          <RunPane curves={[]} connectionStatus="disconnected" onRunSaved={vi.fn()} />
        </UnitsProvider>
      </ThemeProvider>,
    )
    const startButton = screen.getByText('Start run').closest('button')
    expect(startButton?.getAttribute('aria-disabled')).toBe('true')
    expect(screen.getByText(/No live link to the board/)).toBeTruthy()
  })

  it('confirms before starting, and does not start when declined', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O', 'InCond'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    expect(window.confirm).toHaveBeenCalled()
    expect(startRun).not.toHaveBeenCalled()
  })

  it('starts a run once confirmed, sending the picked algorithm', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O', 'InCond'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    await waitFor(() =>
      expect(startRun).toHaveBeenCalledWith(
        expect.objectContaining({ algorithm: 'P&O', curve_ref: null }),
      ),
    )
  })

  it('renders both input and output voltage, current, power and duty while live', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    // The mount-sync call must see "idle" - this test is about the poll
    // that starts once the operator clicks Start, not mount adoption.
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(liveState())
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    await waitFor(() => expect(screen.getByText('12.00 V')).toBeTruthy())
    expect(screen.getByText('28.00 V')).toBeTruthy()
    expect(screen.getByText('V in')).toBeTruthy()
    expect(screen.getByText('V out')).toBeTruthy()
    expect(screen.getByText('40.0 %')).toBeTruthy() // duty
  })

  it('surfaces an abort reason unmistakably, not as a quiet status word', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(
      liveState({ status: 'done', aborted: true, abort_reason: 'overcurrent', saved_run_id: 'r1' }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    await waitFor(() => expect(screen.getAllByText('Aborted').length).toBeGreaterThan(0))
    expect(screen.getByText(/safety cutoff fired/)).toBeTruthy()
    expect(screen.getByText(/i_max limit/)).toBeTruthy()
  })

  it('shows a completed run distinctly from an aborted one, and offers to open it', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'done', saved_run_id: 'r1' }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    await waitFor(() => expect(screen.getByText('Completed')).toBeTruthy())
    expect(screen.getByText('Completed the full run.')).toBeTruthy()
    expect(screen.getByText('Open in player').closest('button')?.disabled).toBe(false)
  })

  it('flags a downsampled live window, as the player does for a saved run', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    // See the voltage/current/power/duty test above for why the mount-sync
    // call needs "idle" ahead of the intended (running) polled value.
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(liveState({ downsampled: true, n_samples: 5000 }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))

    await waitFor(() => expect(screen.getByText(/downsampled for display/)).toBeTruthy())
    expect(screen.getByText(/of 5000 samples/)).toBeTruthy()
  })

  it('opens the finished run in the player once its id resolves in the library', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'done', saved_run_id: 'r1' }))
    const summary: RunSummary = {
      id: 'r1',
      path: '/data/runs/r1.json',
      captured_at: '2026-09-14T08:00:00Z',
      label: 'bench run',
      algorithm: 'P&O',
      n_samples: 1,
      duration_s: 1,
      aborted: false,
      curve_ref: null,
      notes: '',
      source: 'hardware',
    }
    vi.mocked(fetchRuns).mockResolvedValue([summary])
    vi.mocked(fetchRun).mockResolvedValue({
      ...summary,
      downsampled: false,
      samples: [{ t: 0, v: 12, i: 0.25, d: 0.4 }],
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPane()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start run'))
    await waitFor(() => expect(screen.getByText('Open in player')).toBeTruthy())

    fireEvent.click(screen.getByText('Open in player'))
    await waitFor(() => expect(fetchRuns).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByLabelText('Playback position')).toBeTruthy())
  })

  it('adopts a run already in progress on mount, showing the monitor with a working stop instead of the setup form', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState())
    vi.mocked(stopRun).mockResolvedValue(undefined)
    renderPane()

    // A run in progress server-side must be reflected the moment this
    // pane mounts - no setup form to click through, since the converter
    // is already being driven (see useLiveRun's mount-sync effect).
    await waitFor(() => expect(screen.getByText('Stop run')).toBeTruthy())
    expect(screen.queryByLabelText('Algorithm')).toBeNull()
    expect(startRun).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('Stop run'))
    await waitFor(() => expect(stopRun).toHaveBeenCalledTimes(1))
  })

  it('shows the setup form when the server reports no run in progress on mount', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'idle' }))
    renderPane()

    await waitFor(() => expect(fetchLiveRun).toHaveBeenCalled())
    expect(screen.getByText('Start run')).toBeTruthy()
    expect(screen.queryByText('Stop run')).toBeNull()
  })
})

describe('RunPane in demo (sandbox) mode', () => {
  it('allows starting a simulated run with no live link and no confirmation', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O', 'InCond'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    const confirmSpy = vi.spyOn(window, 'confirm')
    renderPaneInSandbox()

    await selectAlgorithm('P&O')
    const startButton = screen.getByText('Start simulated run').closest('button')
    expect(startButton?.getAttribute('aria-disabled')).not.toBe('true')
    fireEvent.click(screen.getByText('Start simulated run'))

    await waitFor(() =>
      expect(startRun).toHaveBeenCalledWith(
        expect.objectContaining({ algorithm: 'P&O', curve_ref: null, simulated: true }),
      ),
    )
    // Nothing physical happens, so there is nothing to confirm.
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('sends a picked demo curve inline, and draws the reference the server echoes back', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O',
      duration_s: 10,
    })
    const curve = DEMO_CURVES[0]
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(liveState({ source: 'simulated', reference_points: curve.points }))
    renderPaneInSandbox(DEMO_CURVES)

    await selectAlgorithm('P&O')
    fireEvent.change(screen.getByLabelText('Reference curve'), { target: { value: curve.id } })
    fireEvent.click(screen.getByText('Start simulated run'))

    await waitFor(() =>
      expect(startRun).toHaveBeenCalledWith(
        expect.objectContaining({
          curve_ref: null,
          curve_points: curve.points.map((p) => [p.v, p.i]),
          // The demo curve's own id, so the server can save it as the
          // saved run's curve_ref - see StartRunInput's reference_label
          // doc comment. Without this the run player has no way back to
          // a curve that was never in the server's own library.
          reference_label: curve.id,
          simulated: true,
        }),
      ),
    )
    await waitFor(() => expect(screen.getByText('Simulated - not measured')).toBeTruthy())
    // A reference arrived, so the "no reference curve" note must not show.
    expect(screen.queryByText(/No reference curve/)).toBeNull()
    // Not just present in the props somewhere - actually reaches the
    // chart, as both the I(V) and P(V) reference series, one point per
    // curve point.
    await waitFor(() =>
      expect(chartDatasets()).toEqual(
        expect.arrayContaining([
          { label: 'Reference I(V)', n: curve.points.length },
          { label: 'Reference P(V)', n: curve.points.length },
        ]),
      ),
    )
  })

  it('opens a finished demo run in the player and still draws its reference, found by the saved curve_ref label', async () => {
    // The server saves the chosen demo curve's id as curve_ref (via
    // reference_label - see post_start_run), even though that id never
    // named a file in its own curve library. findCurveForRun (lib/
    // runPlayback.ts) then has to resolve it against this pane's own
    // `curves` list, which in demo mode is DEMO_CURVES - proving the
    // whole round trip, not just the live view.
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O',
      duration_s: 10,
    })
    const curve = DEMO_CURVES[0]
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(
        liveState({
          status: 'done',
          source: 'simulated',
          curve_ref: curve.id,
          // Empty on purpose: the preview falls back to the live view's
          // reference points, which would hide a broken curve_ref lookup.
          reference_points: [],
          saved_run_id: 'sim-run-1',
        }),
      )
    const summary: RunSummary = {
      id: 'sim-run-1',
      path: '/data/runs/sim-run-1.json',
      captured_at: '2026-09-18T08:00:00Z',
      label: 'P&O',
      algorithm: 'P&O',
      n_samples: 1,
      duration_s: 1,
      aborted: false,
      curve_ref: curve.id,
      notes: '',
      source: 'simulated',
    }
    vi.mocked(fetchRuns).mockResolvedValue([summary])
    vi.mocked(fetchRun).mockResolvedValue({
      ...summary,
      downsampled: false,
      samples: [{ t: 0, v: 12, i: 0.25, d: 0.4 }],
    })
    renderPaneInSandbox(DEMO_CURVES)

    await selectAlgorithm('P&O')
    fireEvent.change(screen.getByLabelText('Reference curve'), { target: { value: curve.id } })
    fireEvent.click(screen.getByText('Start simulated run'))

    await waitFor(() => expect(screen.getByText('Open in player')).toBeTruthy())
    fireEvent.click(screen.getByText('Open in player'))
    await waitFor(() => expect(screen.getByLabelText('Playback position')).toBeTruthy())

    // Scoped to the player dialog: RunMonitor's live chart stays mounted
    // behind it and draws the same reference from the server's
    // reference_points, so an unscoped check would pass even with the
    // player's own curve_ref lookup broken.
    await waitFor(() =>
      expect(chartDatasets(screen.getByRole('dialog'))).toEqual(
        expect.arrayContaining([{ label: 'Reference I(V)', n: curve.points.length }]),
      ),
    )
  })

  it('keeps the live grey curve in the preview of a run saved with no reference (built-in panel)', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O',
      duration_s: 10,
    })
    const builtIn = DEMO_CURVES[0].points
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(
        liveState({
          status: 'done',
          source: 'simulated',
          curve_ref: null,
          reference_points: builtIn,
          saved_run_id: 'sim-run-2',
        }),
      )
    const summary: RunSummary = {
      id: 'sim-run-2',
      path: '/data/runs/sim-run-2.json',
      captured_at: '2026-09-19T08:00:00Z',
      label: 'P&O',
      algorithm: 'P&O',
      n_samples: 1,
      duration_s: 1,
      aborted: false,
      curve_ref: null,
      notes: '',
      source: 'simulated',
    }
    vi.mocked(fetchRuns).mockResolvedValue([summary])
    vi.mocked(fetchRun).mockResolvedValue({
      ...summary,
      downsampled: false,
      samples: [{ t: 0, v: 12, i: 0.25, d: 0.4 }],
    })
    renderPaneInSandbox(DEMO_CURVES)

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start simulated run'))
    await waitFor(() => expect(screen.getByText('Open in player')).toBeTruthy())
    fireEvent.click(screen.getByText('Open in player'))
    await waitFor(() => expect(screen.getByLabelText('Playback position')).toBeTruthy())

    const dialog = screen.getByRole('dialog')
    await waitFor(() =>
      expect(chartDatasets(dialog)).toEqual(
        expect.arrayContaining([{ label: 'Reference I(V)', n: builtIn.length }]),
      ),
    )
    expect(within(dialog).queryByText(/No reference curve/)).toBeNull()
  })

  it('marks a simulated run unmistakably while it is live', async () => {
    vi.mocked(fetchRunConfig).mockResolvedValue({
      algorithms: ['P&O'],
      maxDurationS: 600,
      defaultDurationS: 10,
      defaultInitialDuty: 0.5,
      defaultVMax: 40,
      defaultIMax: 1,
    })
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O',
      duration_s: 30,
    })
    // See the (non-sandbox) voltage/current/power/duty test for why the
    // mount-sync call needs "idle" ahead of the intended polled value.
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(liveState({ source: 'simulated' }))
    renderPaneInSandbox()

    await selectAlgorithm('P&O')
    fireEvent.click(screen.getByText('Start simulated run'))

    await waitFor(() => expect(screen.getByText('Simulated - not measured')).toBeTruthy())
  })

  it('a hardware run stays unavailable outside demo mode when the link is down', () => {
    vi.mocked(fetchRunConfig).mockReturnValue(new Promise(() => {}))
    renderPane()
    // renderPane's default connectionStatus is 'connected'; the existing
    // "blocks starting when there is no live link" test above already
    // covers the disconnected case for hardware mode - this just confirms
    // the two modes' Start buttons carry different labels, so a screenshot
    // can never be read as "a hardware run that happens to be disabled".
    expect(screen.getByText('Start run')).toBeTruthy()
    expect(screen.queryByText('Start simulated run')).toBeNull()
  })
})
