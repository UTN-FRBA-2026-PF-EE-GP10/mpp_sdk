import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useConnectionStatus } from './useConnectionStatus'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
}))

import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'

function mockData(overrides: Partial<LiveSweepState>): LiveSweepState {
  return { points: [], partial: [], active: false, link: 'ok', seq: 0, commandError: null, ...overrides }
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('useConnectionStatus', () => {
  it('starts as connecting before the first poll resolves', () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('connecting')
  })

  it('reports connecting when link is "no data yet"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'no data yet' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connecting'))
  })

  it('reports connected for "ok"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'ok' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connected'))
  })

  it('reports connected for "waiting for sweep"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'waiting for sweep' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('connected'))
  })

  it('reports demo for link === "demo"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'demo' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('demo'))
  })

  it('reports disconnected when link starts with "error"', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockData({ link: 'error: boom' }))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('disconnected'))
  })

  it('reports disconnected when the fetch itself throws', async () => {
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useConnectionStatus())
    await waitFor(() => expect(result.current).toBe('disconnected'))
  })
})
