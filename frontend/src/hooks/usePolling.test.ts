import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('usePolling', () => {
  it('calls the fetcher immediately on mount', () => {
    const fetcher = vi.fn().mockReturnValue(new Promise(() => {}))
    renderHook(() => usePolling(fetcher, vi.fn(), vi.fn(), 1000))
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('calls onSuccess with the resolved value', async () => {
    const fetcher = vi.fn().mockResolvedValue('hello')
    const onSuccess = vi.fn()
    renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 1000))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('hello'))
  })

  it('calls onError when the fetcher rejects', async () => {
    const error = new Error('boom')
    const fetcher = vi.fn().mockRejectedValue(error)
    const onError = vi.fn()
    renderHook(() => usePolling(fetcher, vi.fn(), onError, 1000))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(error))
  })

  it('does not call onSuccess for a response that resolves after unmount', async () => {
    let resolveFetch: (value: string) => void = () => {}
    const fetcher = vi.fn().mockReturnValue(
      new Promise<string>((resolve) => {
        resolveFetch = resolve
      }),
    )
    const onSuccess = vi.fn()
    const { unmount } = renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 1000))
    unmount()
    resolveFetch('too late')
    await new Promise((r) => setTimeout(r, 10))
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it(
    'polls again after intervalMs',
    async () => {
      const fetcher = vi.fn().mockResolvedValue('tick')
      const onSuccess = vi.fn()
      renderHook(() => usePolling(fetcher, onSuccess, vi.fn(), 200))
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2), { timeout: 2000 })
    },
    3000,
  )
})
