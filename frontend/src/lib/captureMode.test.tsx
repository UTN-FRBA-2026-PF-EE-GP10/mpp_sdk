import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { useCaptureMode } from './captureMode'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function Probe() {
  const { mode, setMode } = useCaptureMode()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <button type="button" onClick={() => setMode('firmware-replay')}>
        pick-replay
      </button>
      <button type="button" onClick={() => setMode('simulated')}>
        pick-simulated
      </button>
      <button type="button" onClick={() => setMode('hardware')}>
        pick-hardware
      </button>
    </div>
  )
}

describe('useCaptureMode', () => {
  it('defaults to hardware outside a provider - the safe, fully-capable fallback', () => {
    render(<Probe />)
    expect(screen.getByTestId('mode').textContent).toBe('hardware')
  })

  it('starts at hardware inside a fresh provider, with nothing stored yet', () => {
    render(
      <CaptureModeProvider>
        <Probe />
      </CaptureModeProvider>,
    )
    expect(screen.getByTestId('mode').textContent).toBe('hardware')
  })

  it('moves between all three modes', () => {
    render(
      <CaptureModeProvider>
        <Probe />
      </CaptureModeProvider>,
    )
    fireEvent.click(screen.getByText('pick-replay'))
    expect(screen.getByTestId('mode').textContent).toBe('firmware-replay')
    fireEvent.click(screen.getByText('pick-simulated'))
    expect(screen.getByTestId('mode').textContent).toBe('simulated')
    fireEvent.click(screen.getByText('pick-hardware'))
    expect(screen.getByTestId('mode').textContent).toBe('hardware')
  })

  it('persists the choice across remounts, like the unit toggle', () => {
    const { unmount } = render(
      <CaptureModeProvider>
        <Probe />
      </CaptureModeProvider>,
    )
    fireEvent.click(screen.getByText('pick-simulated'))
    unmount()
    render(
      <CaptureModeProvider>
        <Probe />
      </CaptureModeProvider>,
    )
    expect(screen.getByTestId('mode').textContent).toBe('simulated')
  })

  it('ignores a garbage stored value rather than crashing', () => {
    window.localStorage.setItem('mpp-sdk.capture-mode', 'not-a-real-mode')
    render(
      <CaptureModeProvider>
        <Probe />
      </CaptureModeProvider>,
    )
    expect(screen.getByTestId('mode').textContent).toBe('hardware')
  })
})
