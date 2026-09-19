import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { SetupModeProvider } from './SetupModeProvider'
import { useSetupMode } from '@/lib/setupMode'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function Probe() {
  const { mode, setMode } = useSetupMode()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <button type="button" onClick={() => setMode('single')}>
        single
      </button>
      <button type="button" onClick={() => setMode('full')}>
        full
      </button>
    </div>
  )
}

function renderProbe() {
  return render(
    <SetupModeProvider>
      <Probe />
    </SetupModeProvider>,
  )
}

describe('SetupModeProvider', () => {
  it('defaults to full', () => {
    renderProbe()
    expect(screen.getByTestId('mode').textContent).toBe('full')
  })

  it('persists the choice across a remount, the same way units/theme do', () => {
    const { unmount } = renderProbe()
    fireEvent.click(screen.getByText('single'))
    expect(screen.getByTestId('mode').textContent).toBe('single')
    expect(window.localStorage.getItem('mpp-sdk.setup-mode')).toBe('single')
    unmount()

    renderProbe()
    expect(screen.getByTestId('mode').textContent).toBe('single')
  })

  it('throws outside a provider, same convention as useUnits/useTheme', () => {
    expect(() => render(<Probe />)).toThrow(/SetupModeProvider/)
  })
})
