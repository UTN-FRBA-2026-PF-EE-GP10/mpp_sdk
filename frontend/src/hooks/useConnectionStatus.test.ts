import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useConnectionStatus } from './useConnectionStatus'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
}))

import { fetchLiveSweep } from '@/lib/api'
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

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('useConnectionStatus', () => {
  it('starts as connecting before the first poll resolves', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current.status).toBe('connecting')
  })

  it('reports connecting when link is "no data yet"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'no data yet' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('connecting'))
  })

  it('reports connected for "ok"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'ok' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('connected'))
  })

  it('reports connected for "waiting for sweep"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'waiting for sweep' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('connected'))
  })

  it('keeps the same state object while the link does not change', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'ok' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('connected'))
    const first = result.current

    // A new object every poll would re-render the whole page twice a
    // second, for a link that has not moved.
    await new Promise((r) => setTimeout(r, 2200))

    expect(result.current).toBe(first)
  })

  it('reports demo for link === "demo"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'demo' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('demo'))
  })

  it('reports disconnected when link starts with "error"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'error: boom' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('disconnected'))
  })

  it('reports disconnected when the fetch itself throws', async () => {
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current.status).toBe('disconnected'))
  })

  it('never touches the network when disabled - demo mode promises no background polling', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'ok' }))
    const { result } = renderHook(() => useConnectionStatus(false))
    await new Promise((r) => setTimeout(r, 10))
    expect(fetchLiveSweep).not.toHaveBeenCalled()
    expect(result.current.status).toBe('connecting') // untouched initial state
  })
})
