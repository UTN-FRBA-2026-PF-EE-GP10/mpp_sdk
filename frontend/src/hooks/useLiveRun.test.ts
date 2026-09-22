import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useLiveRun } from './useLiveRun'

vi.mock('@/lib/api', () => ({
  fetchLiveRun: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
}))

import { fetchLiveRun, startRun, stopRun } from '@/lib/api'
import type { LiveRunState } from '@/lib/runs'

function liveState(overrides: Partial<LiveRunState> = {}): LiveRunState {
  return {
    status: 'running',
    algorithm: 'P&O',
    label: 'bench run',
    curve_ref: null,
    n_samples: 1,
    downsampled: false,
    samples: [{ t: 0, v: 10, i: 0.2, d: 0.3 }],
    voltage: 10,
    current: 0.2,
    duty: 0.3,
    vout: 25,
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

describe('useLiveRun', () => {
  it('syncs once on mount and stays idle when the server has no run in progress', async () => {
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'idle' }))
    const { result } = renderHook(() => useLiveRun())

    await waitFor(() => expect(fetchLiveRun).toHaveBeenCalledTimes(1))
    expect(result.current.phase).toBe('idle')
    expect(result.current.live).toBeNull()

    // Idle means usePolling's own interval never activates - no further
    // calls should follow the one-off mount sync.
    await new Promise((r) => setTimeout(r, 500))
    expect(fetchLiveRun).toHaveBeenCalledTimes(1)
  })

  it('adopts an already-running run found on mount, with a working stop', async () => {
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState())
    const { result } = renderHook(() => useLiveRun())

    await waitFor(() => expect(result.current.phase).toBe('live'))
    expect(result.current.live?.voltage).toBe(10)
    expect(startRun).not.toHaveBeenCalled()

    vi.mocked(stopRun).mockResolvedValue(undefined)
    await act(async () => {
      await result.current.stop()
    })
    expect(stopRun).toHaveBeenCalledTimes(1)
  })

  it('settles an adopted run that has already finished, rather than staying live forever', async () => {
    // Adopted as "running" on mount, then the very next poll (triggered by
    // that adoption) discovers it already finished - resolution can be
    // fast enough that 'live' is never separately observable, so this
    // only asserts the settled end state, not the transition through it.
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState())
      .mockResolvedValue(liveState({ status: 'done', saved_run_id: 'run-1' }))
    const { result } = renderHook(() => useLiveRun())

    await waitFor(() => expect(result.current.phase).toBe('done'))
    expect(result.current.live?.saved_run_id).toBe('run-1')
  })

  it('does not let a stale mount-sync response clobber a run this session just started', async () => {
    let resolveMountSync!: (data: LiveRunState) => void
    vi.mocked(fetchLiveRun)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveMountSync = resolve
          }),
      )
      .mockResolvedValue(liveState())
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })
    expect(result.current.phase).toBe('live')

    // The mount-sync call (still in flight from before start()) finally
    // resolves, describing the world from before this session's run
    // existed - it must not undo what start() already did.
    await act(async () => {
      resolveMountSync(liveState({ status: 'idle' }))
    })
    expect(result.current.phase).toBe('live')
  })

  it('moves to the live phase once start() resolves, and begins polling', async () => {
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })

    expect(result.current.phase).toBe('live')
    await waitFor(() => expect(fetchLiveRun).toHaveBeenCalled())
  })

  it('surfaces a rejected start without leaving the live phase', async () => {
    vi.mocked(startRun).mockRejectedValue(new Error('no board attached'))
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })

    expect(result.current.phase).toBe('idle')
    expect(result.current.startError).toBe('no board attached')
  })

  it('shows the text onStartError returns instead of the error message, and keeps the message when it returns nothing', async () => {
    vi.mocked(startRun).mockRejectedValue(new Error('session not found'))
    const onStartError = vi.fn().mockReturnValueOnce('filing was turned off')
    const { result } = renderHook(() => useLiveRun({ onStartError }))

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })
    expect(onStartError).toHaveBeenCalledTimes(1)
    expect(result.current.startError).toBe('filing was turned off')

    onStartError.mockReturnValueOnce(undefined)
    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })
    expect(result.current.startError).toBe('session not found')
  })

  it('adopts each poll result while running', async () => {
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    // The mount-sync call must see "idle" - the point of this test is the
    // polling loop that starts once `start()` succeeds, not adoption.
    vi.mocked(fetchLiveRun)
      .mockResolvedValueOnce(liveState({ status: 'idle' }))
      .mockResolvedValue(liveState())
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })

    await waitFor(() => expect(result.current.live?.voltage).toBe(10))
    expect(result.current.live?.vout).toBe(25)
  })

  it('moves to done once a poll reports the run finished, and stops polling', async () => {
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'done', saved_run_id: 'run-1' }))
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })

    await waitFor(() => expect(result.current.phase).toBe('done'))
    const callsAtDone = vi.mocked(fetchLiveRun).mock.calls.length
    await new Promise((r) => setTimeout(r, 500))
    expect(vi.mocked(fetchLiveRun).mock.calls.length).toBe(callsAtDone)
  })

  it('stop() calls the stop endpoint and reports a failure', async () => {
    vi.mocked(stopRun).mockRejectedValue(new Error('no run in progress'))
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.stop()
    })

    expect(stopRun).toHaveBeenCalledTimes(1)
    expect(result.current.stopError).toBe('no run in progress')
  })

  it('reset() returns to idle and clears the live snapshot', async () => {
    vi.mocked(startRun).mockResolvedValue({
      status: 'running',
      algorithm: 'P&O',
      label: 'bench run',
      duration_s: 30,
    })
    vi.mocked(fetchLiveRun).mockResolvedValue(liveState({ status: 'done' }))
    const { result } = renderHook(() => useLiveRun())

    await act(async () => {
      await result.current.start({ algorithm: 'P&O' })
    })
    await waitFor(() => expect(result.current.phase).toBe('done'))

    act(() => result.current.reset())

    expect(result.current.phase).toBe('idle')
    expect(result.current.live).toBeNull()
  })
})
