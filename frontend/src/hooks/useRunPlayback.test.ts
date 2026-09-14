import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useRunPlayback } from './useRunPlayback'
import type { RunSample } from '@/lib/runs'

afterEach(cleanup)

function samples(): RunSample[] {
  return [
    { t: 0, v: 5, i: 0.2, d: 0.3 },
    { t: 1, v: 8, i: 0.19, d: 0.35 },
    { t: 2, v: 12, i: 0.15, d: 0.4 },
  ]
}

// This only covers the state transitions, not the requestAnimationFrame
// loop itself - per the brief, the animation is not worth unit testing.
//
// Each test builds its sample array once, outside the renderHook
// callback: calling samples() fresh from inside the callback would give
// the hook a new array reference on every render, tripping its own
// change-of-run detection on every re-render (an infinite loop, not the
// run-switch behaviour that check exists for - see the dedicated test
// below for that).
describe('useRunPlayback', () => {
  it('starts paused at the beginning of the run', () => {
    const { result } = renderHook(() => useRunPlayback(samples()))
    expect(result.current.playing).toBe(false)
    expect(result.current.time).toBe(0)
    expect(result.current.index).toBe(0)
    expect(result.current.duration).toBe(2)
  })

  it('reports index -1 and zero duration for an empty run', () => {
    const empty: RunSample[] = []
    const { result } = renderHook(() => useRunPlayback(empty))
    expect(result.current.index).toBe(-1)
    expect(result.current.duration).toBe(0)
  })

  it('seek moves the clock and pauses playback', () => {
    const s = samples()
    const { result } = renderHook(() => useRunPlayback(s))
    act(() => result.current.play())
    expect(result.current.playing).toBe(true)

    act(() => result.current.seek(1.5))
    expect(result.current.playing).toBe(false)
    expect(result.current.time).toBe(1.5)
    expect(result.current.index).toBe(1)
  })

  it('seek clamps to the run bounds', () => {
    const s = samples()
    const { result } = renderHook(() => useRunPlayback(s))
    act(() => result.current.seek(-10))
    expect(result.current.time).toBe(0)
    act(() => result.current.seek(999))
    expect(result.current.time).toBe(2)
  })

  it('restart resets the clock without changing whether it is playing', () => {
    const s = samples()
    const { result } = renderHook(() => useRunPlayback(s))
    act(() => result.current.seek(1.5))
    act(() => result.current.restart())
    expect(result.current.time).toBe(0)
    expect(result.current.playing).toBe(false)

    act(() => result.current.play())
    act(() => result.current.restart())
    expect(result.current.time).toBe(0)
    expect(result.current.playing).toBe(true)
  })

  it('play() at the end of the run restarts from zero instead of doing nothing', () => {
    const s = samples()
    const { result } = renderHook(() => useRunPlayback(s))
    act(() => result.current.seek(2))
    expect(result.current.time).toBe(2)

    act(() => result.current.play())
    expect(result.current.time).toBe(0)
    expect(result.current.playing).toBe(true)
  })

  it('toggle flips play/pause', () => {
    const s = samples()
    const { result } = renderHook(() => useRunPlayback(s))
    act(() => result.current.toggle())
    expect(result.current.playing).toBe(true)
    act(() => result.current.toggle())
    expect(result.current.playing).toBe(false)
  })

  it('resets to the start when a different run is loaded', () => {
    const first = samples()
    const { result, rerender } = renderHook(({ s }) => useRunPlayback(s), {
      initialProps: { s: first },
    })
    act(() => result.current.seek(1.5))
    expect(result.current.time).toBe(1.5)

    const second = samples()
    rerender({ s: second })
    expect(result.current.time).toBe(0)
    expect(result.current.playing).toBe(false)
  })
})
