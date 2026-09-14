import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CaptureModeContext } from '@/lib/captureMode'
import { useSandbox } from './sandbox'

afterEach(cleanup)

function Probe() {
  const { enabled } = useSandbox()
  return <span data-testid="enabled">{String(enabled)}</span>
}

function renderWithMode(mode: 'hardware' | 'firmware-replay' | 'simulated') {
  return render(
    <CaptureModeContext.Provider value={{ mode, setMode: vi.fn() }}>
      <Probe />
    </CaptureModeContext.Provider>,
  )
}

describe('useSandbox', () => {
  it('defaults to off outside a provider - the safe fallback, not a throw', () => {
    render(<Probe />)
    expect(screen.getByTestId('enabled').textContent).toBe('false')
  })

  it('is disabled for hardware mode', () => {
    renderWithMode('hardware')
    expect(screen.getByTestId('enabled').textContent).toBe('false')
  })

  it('is disabled for firmware-replay mode - still a real, live mode', () => {
    renderWithMode('firmware-replay')
    expect(screen.getByTestId('enabled').textContent).toBe('false')
  })

  it('is enabled only for simulated mode', () => {
    renderWithMode('simulated')
    expect(screen.getByTestId('enabled').textContent).toBe('true')
  })
})
