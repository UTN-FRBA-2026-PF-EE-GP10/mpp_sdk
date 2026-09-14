import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MeasurePane } from './MeasurePane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext, type CaptureMode } from '@/lib/captureMode'
import type { CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  startSweep: vi.fn(),
  startDemoSweep: vi.fn(),
  releaseRelay: vi.fn(),
  saveCurve: vi.fn(),
}))

afterEach(cleanup)

function renderPane(mode: CaptureMode) {
  const byKind = new Map<string, CurveRecord[]>([['baseline', []]])
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeContext.Provider value={{ mode, setMode: vi.fn() }}>
          <MeasurePane kinds={['baseline']} byKind={byKind} connected onSaved={vi.fn()} />
        </CaptureModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function button(text: string) {
  const el = screen.getByText(text).closest('button')
  if (!el) throw new Error(`no button ancestor for "${text}"`)
  return el
}

// Start Measurement/Release Relay carry a `title` explaining a demo-mode
// disablement, so they use focusableWhenDisabled (aria-disabled, not the
// native attribute) to keep that title reachable by hover/focus - see
// button.tsx and CurveDashboardPane's note on the same fix. This checks
// either form.
function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true'
}

describe('MeasurePane', () => {
  it('shows live capture controls in hardware mode', () => {
    renderPane('hardware')
    expect(isDisabled(button('Start Measurement'))).toBe(false)
  })

  it('leaves everything live in firmware-replay mode too - only simulated is offline', () => {
    renderPane('firmware-replay')
    expect(isDisabled(button('Start Measurement'))).toBe(false)
    expect(isDisabled(button('Demo curve (bright)'))).toBe(false)
    expect(screen.getByText(/Demo with PICO:/)).toBeTruthy()
  })

  it('disables the hardware-only controls in simulated mode and explains why', () => {
    renderPane('simulated')
    expect(isDisabled(button('Start Measurement'))).toBe(true)
    expect(isDisabled(button('Release Relay'))).toBe(true)
    expect(screen.getByText(/Demo mode:/)).toBeTruthy()
  })

  it('still lets the demo-curve buttons work in simulated mode', () => {
    renderPane('simulated')
    expect(isDisabled(button('Demo curve (bright)'))).toBe(false)
    expect(isDisabled(button('Demo curve (dim)'))).toBe(false)
  })
})
