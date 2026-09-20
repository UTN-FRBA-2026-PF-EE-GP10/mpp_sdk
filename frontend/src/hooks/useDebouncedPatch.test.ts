import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedPatch } from './useDebouncedPatch'
import type { ReportRecord } from '@/lib/reports'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.resetAllMocks()
})

function patcher() {
  return vi.fn().mockResolvedValue({} as ReportRecord)
}

describe('useDebouncedPatch', () => {
  it('merges edits inside the debounce window into one request', async () => {
    vi.useFakeTimers()
    const onPatch = patcher()
    const { result } = renderHook(() => useDebouncedPatch(onPatch))

    act(() => result.current.schedule({ steps: [{ id: 'a', notes: 'one' }] }))
    act(() => result.current.schedule({ steps: [{ id: 'a', notes: 'one two' }] }))
    expect(onPatch).not.toHaveBeenCalled()

    act(() => void vi.advanceTimersByTime(700))
    expect(onPatch).toHaveBeenCalledTimes(1)
    expect(onPatch.mock.calls[0][0]).toEqual({ steps: [{ id: 'a', notes: 'one two' }] })
  })

  it('sends a pending edit when the view goes away, rather than losing it', async () => {
    const onPatch = patcher()
    const { result, unmount } = renderHook(() => useDebouncedPatch(onPatch))

    act(() => result.current.schedule({ steps: [{ id: 'a', notes: 'typed then left' }] }))
    unmount()

    await waitFor(() => expect(onPatch).toHaveBeenCalledTimes(1))
    expect(onPatch.mock.calls[0][0]).toEqual({ steps: [{ id: 'a', notes: 'typed then left' }] })
  })

  it('sends nothing on unmount when there is no pending edit', () => {
    const onPatch = patcher()
    const { unmount } = renderHook(() => useDebouncedPatch(onPatch))
    unmount()
    expect(onPatch).not.toHaveBeenCalled()
  })

  it('reports a failed save', async () => {
    const onPatch = vi.fn().mockRejectedValue(new Error('server said no'))
    const { result } = renderHook(() => useDebouncedPatch(onPatch))

    act(() => result.current.sendNow({ steps: [{ id: 'a', status: 'done' }] }))

    await waitFor(() => expect(result.current.state).toBe('error'))
    expect(result.current.error).toBe('server said no')
  })
})
