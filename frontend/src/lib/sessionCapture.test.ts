import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LiveSweepState } from '@/lib/api'
import type { LiveRunState } from '@/lib/runs'
import type { SessionStep } from '@/lib/sessions'
import { CaptureError, captureIntoStep } from './sessionCapture'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
  fetchLiveRun: vi.fn(),
  fetchRunConfig: vi.fn(),
  saveCurve: vi.fn(),
  startRun: vi.fn(),
  startSweep: vi.fn(),
}))

import {
  fetchLiveRun,
  fetchLiveSweep,
  fetchRunConfig,
  saveCurve,
  startRun,
  startSweep,
} from '@/lib/api'

const TIMINGS = { pollMs: 0, sweepTimeoutMs: 40, runGraceMs: 40 }

function step(kind: 'curve' | 'run'): SessionStep {
  return {
    id: `${kind}-step`,
    section: 'S',
    title: kind === 'curve' ? 'Baseline sweep' : 'P&O run',
    instructions: '',
    kind,
    status: 'todo',
    value: null,
    unit: null,
    notes: '',
    curve_ids: [],
    run_ids: [],
    repeats: 1,
  }
}

function sweep(overrides: Partial<LiveSweepState> = {}): LiveSweepState {
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

const FINISHED_SWEEP = sweep({ seq: 2, points: [{ v: 10, i: 0.1 }] })

function liveRun(overrides: Partial<LiveRunState> = {}): LiveRunState {
  return {
    status: 'done',
    algorithm: 'P&O',
    label: 'P&O run',
    curve_ref: null,
    n_samples: 3,
    downsampled: false,
    samples: [],
    voltage: null,
    current: null,
    duty: null,
    vout: null,
    aborted: false,
    abort_reason: null,
    saved_run_id: 'run-1',
    source: 'hardware',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(fetchRunConfig).mockResolvedValue({
    algorithms: ['P&O', 'InCond'],
    maxDurationS: 600,
    defaultDurationS: 0,
    defaultInitialDuty: 0.5,
    defaultVMax: 40,
    defaultIMax: 1,
    defaultVOutMax: 25,
  })
})

afterEach(() => {
  vi.resetAllMocks()
})

describe('captureIntoStep - curve step', () => {
  it('sweeps, saves stamped with the session, then links the saved curve - in that order', async () => {
    vi.mocked(fetchLiveSweep)
      .mockResolvedValueOnce(sweep()) // baseline
      .mockResolvedValueOnce(sweep({ active: true })) // sweeping
      .mockResolvedValue(FINISHED_SWEEP)
    vi.mocked(startSweep).mockResolvedValue()
    vi.mocked(saveCurve).mockResolvedValue({ path: '/data/curves/new.json', id: 'new' })
    const order: string[] = []
    vi.mocked(startSweep).mockImplementation(async () => void order.push('start'))
    vi.mocked(saveCurve).mockImplementation(async () => {
      order.push('save')
      return { path: '/data/curves/new.json', id: 'new' }
    })
    const link = vi.fn(async () => void order.push('link'))

    await captureIntoStep({ sessionId: 'sess-1', step: step('curve'), link, timings: TIMINGS })

    expect(order).toEqual(['start', 'save', 'link'])
    expect(saveCurve).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Baseline sweep', measurement: 'other', session_id: 'sess-1' }),
    )
    expect(link).toHaveBeenCalledWith('curve', 'new')
  })

  it('does not take the previous curve for this sweep: waits for a new seq', async () => {
    const old = sweep({ seq: 1, points: [{ v: 1, i: 1 }] })
    vi.mocked(fetchLiveSweep)
      .mockResolvedValueOnce(old)
      .mockResolvedValueOnce(old) // still the old curve, same seq
      .mockResolvedValue(FINISHED_SWEEP)
    vi.mocked(saveCurve).mockResolvedValue({ path: 'p', id: 'new' })
    const link = vi.fn().mockResolvedValue(undefined)

    await captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS })

    expect(fetchLiveSweep).toHaveBeenCalledTimes(3)
    expect(link).toHaveBeenCalledTimes(1)
  })

  it('a sweep that will not start saves and links nothing', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(sweep())
    vi.mocked(startSweep).mockRejectedValue(new Error('POST /api/start-sweep: HTTP 500'))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS }),
    ).rejects.toThrow(/Capture failed.*500/)
    expect(saveCurve).not.toHaveBeenCalled()
    expect(link).not.toHaveBeenCalled()
  })

  it('a sweep already in progress is refused before anything starts', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(sweep({ active: true }))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS }),
    ).rejects.toThrow(/already in progress/)
    expect(startSweep).not.toHaveBeenCalled()
    expect(saveCurve).not.toHaveBeenCalled()
    expect(link).not.toHaveBeenCalled()
  })

  it('a command error reported by the board saves and links nothing', async () => {
    vi.mocked(fetchLiveSweep)
      .mockResolvedValueOnce(sweep())
      .mockResolvedValue(sweep({ commandError: 'start_sweep failed: SPI timeout' }))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS }),
    ).rejects.toThrow(/did not start.*SPI timeout/)
    expect(saveCurve).not.toHaveBeenCalled()
    expect(link).not.toHaveBeenCalled()
  })

  it('a sweep that never finishes times out, saving and linking nothing', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(sweep({ active: true }))
    // The first (baseline) read must not look active.
    vi.mocked(fetchLiveSweep).mockResolvedValueOnce(sweep())
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS }),
    ).rejects.toThrow(/did not finish in time/)
    expect(saveCurve).not.toHaveBeenCalled()
    expect(link).not.toHaveBeenCalled()
  })

  it('a save that fails (e.g. the session was deleted meanwhile) links nothing', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValueOnce(sweep()).mockResolvedValue(FINISHED_SWEEP)
    vi.mocked(saveCurve).mockRejectedValue(new Error('POST /api/save-curve: session not found'))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('curve'), link, timings: TIMINGS }),
    ).rejects.toThrow(/session not found/)
    expect(link).not.toHaveBeenCalled()
  })

  it('a link that fails after the save says the curve is saved and where to find it', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValueOnce(sweep()).mockResolvedValue(FINISHED_SWEEP)
    vi.mocked(saveCurve).mockResolvedValue({ path: 'p', id: 'new' })
    const link = vi.fn().mockRejectedValue(new Error('PATCH failed'))

    const error = await captureIntoStep({
      sessionId: 's',
      step: step('curve'),
      link,
      timings: TIMINGS,
    }).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(CaptureError)
    expect((error as Error).message).toMatch(/saved the curve, but linking it to this step failed/)
    expect((error as Error).message).toMatch(/picker/)
  })
})

describe('captureIntoStep - run step', () => {
  it('starts the run stamped with the session, waits, then links the saved run', async () => {
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'P&O run',
      duration_s: 0,
    })
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveRun({ status: 'running', saved_run_id: null }))
      .mockResolvedValue(liveRun())
    const link = vi.fn().mockResolvedValue(undefined)

    await captureIntoStep({
      sessionId: 'sess-1',
      step: step('run'),
      algorithm: 'InCond',
      link,
      timings: TIMINGS,
    })

    expect(startRun).toHaveBeenCalledWith(
      expect.objectContaining({
        algorithm: 'InCond',
        label: 'P&O run',
        session_id: 'sess-1',
        simulated: false,
      }),
    )
    expect(link).toHaveBeenCalledWith('run', 'run-1')
  })

  it('takes the server first algorithm when none is chosen', async () => {
    vi.mocked(startRun).mockResolvedValue({ status: 'running', algorithm: '', label: '', duration_s: 0 })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveRun())

    await captureIntoStep({
      sessionId: 's',
      step: step('run'),
      link: vi.fn().mockResolvedValue(undefined),
      timings: TIMINGS,
    })

    expect(startRun).toHaveBeenCalledWith(expect.objectContaining({ algorithm: 'P&O' }))
  })

  it('a run the server refuses to start links nothing', async () => {
    vi.mocked(startRun).mockRejectedValue(new Error('POST /api/runs/start: a run is already in progress'))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('run'), link, timings: TIMINGS }),
    ).rejects.toThrow(/already in progress/)
    expect(link).not.toHaveBeenCalled()
  })

  it('an aborted run is not linked, and the message says why', async () => {
    vi.mocked(startRun).mockResolvedValue({ status: 'running', algorithm: '', label: '', duration_s: 0 })
    vi.mocked(fetchLiveRun).mockResolvedValue(
      liveRun({ aborted: true, abort_reason: 'overvoltage', saved_run_id: 'run-aborted' }),
    )
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('run'), link, timings: TIMINGS }),
    ).rejects.toThrow(/ended early.*safety cutoff.*not linked/)
    expect(link).not.toHaveBeenCalled()
  })

  it('a finished run that could not be saved is not linked', async () => {
    vi.mocked(startRun).mockResolvedValue({ status: 'running', algorithm: '', label: '', duration_s: 0 })
    vi.mocked(fetchLiveRun).mockResolvedValue(
      liveRun({ saved_run_id: null, abort_reason: 'completed; failed to save: disk full' }),
    )
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('run'), link, timings: TIMINGS }),
    ).rejects.toThrow(/could not be saved.*disk full/)
    expect(link).not.toHaveBeenCalled()
  })

  it('a run that never finishes times out without linking', async () => {
    vi.mocked(startRun).mockResolvedValue({ status: 'running', algorithm: '', label: '', duration_s: 0 })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveRun({ status: 'running', saved_run_id: null }))
    const link = vi.fn()

    await expect(
      captureIntoStep({ sessionId: 's', step: step('run'), link, timings: TIMINGS }),
    ).rejects.toThrow(/did not finish in time/)
    expect(link).not.toHaveBeenCalled()
  })
})
