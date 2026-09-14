import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from './ThemeProvider'
import { useTheme } from '@/lib/theme'

function mockMatchMedia(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({ matches, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  )
}

function Probe() {
  const { mode, setMode, resolvedDark } = useTheme()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="dark">{String(resolvedDark)}</span>
      <button type="button" onClick={() => setMode('dark')}>
        dark
      </button>
      <button type="button" onClick={() => setMode('light')}>
        light
      </button>
    </div>
  )
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.classList.remove('dark')
  vi.unstubAllGlobals()
})

describe('ThemeProvider', () => {
  it('defaults to system, resolved against the OS preference', () => {
    mockMatchMedia(true)
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('mode').textContent).toBe('system')
    expect(screen.getByTestId('dark').textContent).toBe('true')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('toggles the html.dark class and persists the choice', () => {
    mockMatchMedia(false)
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    fireEvent.click(screen.getByText('dark'))
    expect(screen.getByTestId('dark').textContent).toBe('true')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(window.localStorage.getItem('mpp-sdk.theme')).toBe('dark')

    fireEvent.click(screen.getByText('light'))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('throws outside a provider, same convention as useUnits', () => {
    expect(() => render(<Probe />)).toThrow(/ThemeProvider/)
  })
})
