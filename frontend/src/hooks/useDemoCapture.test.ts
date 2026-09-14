import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoCapture } from './useDemoCapture'
import { DEMO_CURVE_BRIGHT, DEMO_CURVE_DIM } from '@/lib/demoFixtures'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('useDemoCapture', () => {
  it('starts empty and inactive', () => {
    const { result } = renderHook(() => useDemoCapture())
    expect(result.current.points).toEqual([])
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(false)
  })

  it('replays the bright curve point by point, at the real sweep pace, then completes', () => {
    const { result } = renderHook(() => useDemoCapture())

    act(() => result.current.startDemo(true))
    expect(result.current.active).toBe(true)
    expect(result.current.partial).toEqual([])

    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(result.current.partial).toHaveLength(1)
    expect(result.current.active).toBe(true)

    act(() => {
      vi.advanceTimersByTime(250 * DEMO_CURVE_BRIGHT.points.length)
    })
    expect(result.current.active).toBe(false)
    expect(result.current.points).toEqual(DEMO_CURVE_BRIGHT.points)
    expect(result.current.partial).toEqual([])
  })

  it('replays the dim curve when bright is false', () => {
    const { result } = renderHook(() => useDemoCapture())
    act(() => result.current.startDemo(false))
    act(() => {
      vi.advanceTimersByTime(250 * DEMO_CURVE_DIM.points.length)
    })
    expect(result.current.points).toEqual(DEMO_CURVE_DIM.points)
  })

  it('marks every replay as demoSource, never as a live measurement', () => {
    const { result } = renderHook(() => useDemoCapture())
    expect(result.current.demoSource).toBe(true)
  })

  it('never reports a command error - there is no hardware to fail talking to', () => {
    const { result } = renderHook(() => useDemoCapture())
    expect(result.current.commandError).toBeNull()
  })

  it('start() and releaseRelay() are safe no-ops - no hardware to reach', () => {
    const { result } = renderHook(() => useDemoCapture())
    expect(() => result.current.start()).not.toThrow()
    expect(() => result.current.releaseRelay()).not.toThrow()
    expect(result.current.active).toBe(false)
  })

  it('restarting mid-replay resets rather than appending to the previous one', () => {
    const { result } = renderHook(() => useDemoCapture())
    act(() => result.current.startDemo(true))
    act(() => {
      vi.advanceTimersByTime(250 * 5)
    })
    expect(result.current.partial.length).toBeGreaterThan(0)

    act(() => result.current.startDemo(false))
    expect(result.current.partial).toEqual([])
    expect(result.current.active).toBe(true)
  })
})
