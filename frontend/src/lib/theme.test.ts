import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolveDark } from './theme'

function mockMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('resolveDark', () => {
  it('is true for mode "dark" regardless of the OS preference', () => {
    mockMatchMedia(false)
    expect(resolveDark('dark')).toBe(true)
  })

  it('is false for mode "light" regardless of the OS preference', () => {
    mockMatchMedia(true)
    expect(resolveDark('light')).toBe(false)
  })

  it('follows the OS preference for mode "system"', () => {
    mockMatchMedia(true)
    expect(resolveDark('system')).toBe(true)
    mockMatchMedia(false)
    expect(resolveDark('system')).toBe(false)
  })

  it('falls back to light if matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(resolveDark('system')).toBe(false)
  })
})
