import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLiveSweep } from './useLiveSweep'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
  startSweep: vi.fn().mockResolvedValue(undefined),
  releaseRelay: vi.fn().mockResolvedValue(undefined),
}))

import { fetchLiveSweep, releaseRelay, startSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'

function mockData(overrides: Partial<LiveSweepState>): LiveSweepState {
  return {
    points: [],
    partial: [],
    active: false,
    link: 'ok',
    seq: 0,
    commandError: null,
    demoSource: false,
    ...overrides,
  }
}

beforeEach(() => {
  // afterEach resets every mock implementation, so restore the action
  // endpoints' Promise contract before each test. useLiveSweep calls
  // .catch() on both return values.
  vi.mocked(startSweep).mockResolvedValue(undefined)
  vi.mocked(releaseRelay).mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('useLiveSweep', () => {
  it('starts with empty points/partial and inactive', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    expect(result.current.points).toEqual([])
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(false)
  })

  it('draws partial points live while a sweep is active', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(
      mockData({ active: true, partial: [{ v: 10, i: 0.5 }] }),
    )
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }]))
    expect(result.current.active).toBe(true)
    expect(result.current.points).toEqual([])
  })

  it('adopts points and clears partial once a sweep completes', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(
      mockData({ active: false, seq: 1, points: [{ v: 20, i: 0.1 }] }),
    )
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(result.current.points).toEqual([{ v: 20, i: 0.1 }]))
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(false)
  })

  it(
    'does not re-apply points on a later poll with the same seq',
    async () => {
      vi.mocked(fetchLiveSweep)
        .mockResolvedValueOnce(mockData({ seq: 1, points: [{ v: 1, i: 1 }] }))
        .mockResolvedValue(mockData({ seq: 1, points: [{ v: 2, i: 2 }] }))

      const { result } = renderHook(() => useLiveSweep())
      await waitFor(() => expect(result.current.points).toEqual([{ v: 1, i: 1 }]))

      // One more real poll interval (700ms) elapses with a different
      // payload but the same seq - `points` must not change. This is the
      // one genuinely load-bearing test in this file: the seq gate is
      // exactly what stops a completed sweep from being redrawn on every
      // poll.
      await new Promise((r) => setTimeout(r, 900))
      expect(result.current.points).toEqual([{ v: 1, i: 1 }])
    },
    3000,
  )

  // The first poll only establishes the sweep counter (seq), so every
  // sequence below spends one payload on that before the interesting
  // part starts - see "does not re-apply points on a later poll" above.
  it(
    "keeps the stale partial while a finished sweep's bulk result may still be on the way",
    async () => {
      vi.mocked(fetchLiveSweep)
        .mockResolvedValueOnce(mockData({ active: false }))
        .mockResolvedValueOnce(mockData({ active: true, partial: [{ v: 10, i: 0.5 }] }))
        .mockResolvedValue(mockData({ active: false, partial: [] }))

      const { result } = renderHook(() => useLiveSweep())
      await waitFor(() => expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }]), {
        timeout: 2000,
      })

      // Two inactive polls land - still inside the window a real bulk
      // fetch can occupy, so the trace must stay put.
      await new Promise((r) => setTimeout(r, 1600))
      expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }])
    },
    8000,
  )

  it(
    'clears the stale partial once enough inactive polls report no new result (abort or dropped link)',
    async () => {
      vi.mocked(fetchLiveSweep)
        .mockResolvedValueOnce(mockData({ active: false }))
        .mockResolvedValueOnce(mockData({ active: true, partial: [{ v: 10, i: 0.5 }] }))
        .mockResolvedValue(mockData({ active: false, partial: [] }))

      const { result } = renderHook(() => useLiveSweep())
      await waitFor(() => expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }]), {
        timeout: 2000,
      })

      // Enough inactive polls in a row, same seq, nothing new - clear.
      await waitFor(() => expect(result.current.partial).toEqual([]), { timeout: 5000 })
    },
    10000,
  )

  it(
    'never shows an empty chart between the last partial and the completed curve landing',
    async () => {
      vi.mocked(fetchLiveSweep)
        .mockResolvedValueOnce(mockData({ active: false }))
        .mockResolvedValueOnce(mockData({ active: true, partial: [{ v: 10, i: 0.5 }] }))
        // Firmware reports done, but the server has not fetched the bulk
        // result yet - the gap this whole rule exists to tolerate.
        .mockResolvedValueOnce(mockData({ active: false, partial: [] }))
        .mockResolvedValue(mockData({ active: false, seq: 1, points: [{ v: 20, i: 0.1 }] }))

      const { result } = renderHook(() => useLiveSweep())
      await waitFor(() => expect(result.current.partial).toEqual([{ v: 10, i: 0.5 }]), {
        timeout: 2000,
      })
      expect(result.current.points).toEqual([])

      // The completed curve lands - partial clears and points populate
      // together, never an in-between render with both empty.
      await waitFor(() => expect(result.current.points).toEqual([{ v: 20, i: 0.1 }]), {
        timeout: 3000,
      })
      expect(result.current.partial).toEqual([])
    },
    8000,
  )

  it('start() calls the start-sweep endpoint', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    result.current.start()
    expect(vi.mocked(startSweep)).toHaveBeenCalledTimes(1)
  })

  it('shows a start request the server refused, and clears it on the next attempt', async () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    vi.mocked(startSweep).mockRejectedValueOnce(new Error('409 a run is in progress'))
    const { result } = renderHook(() => useLiveSweep())
    act(() => result.current.start())
    await waitFor(() =>
      expect(result.current.commandError).toBe('start-sweep failed: 409 a run is in progress'),
    )
    act(() => result.current.start())
    await waitFor(() => expect(result.current.commandError).toBeNull())
  })

  it('releaseRelay() calls the release-relay endpoint', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useLiveSweep())
    result.current.releaseRelay()
    expect(vi.mocked(releaseRelay)).toHaveBeenCalledTimes(1)
  })

  it('does not poll /api/data at all when disabled - client demo mode relies on this', () => {
    renderHook(() => useLiveSweep(false))
    expect(fetchLiveSweep).not.toHaveBeenCalled()
  })

  it('swallows a poll failure without throwing', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useLiveSweep())
    await waitFor(() => expect(errorSpy).toHaveBeenCalled())
    expect(result.current.active).toBe(false)
    errorSpy.mockRestore()
  })
})
