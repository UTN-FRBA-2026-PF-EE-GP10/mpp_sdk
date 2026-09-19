import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MeasurePane } from './MeasurePane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext, type CaptureMode } from '@/lib/captureMode'
import { SetupModeContext, type SetupMode } from '@/lib/setupMode'
import type { ConnectionStatus, CurveRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  startSweep: vi.fn(),
  startDemoSweep: vi.fn(),
  releaseRelay: vi.fn(),
  saveCurve: vi.fn(),
  fetchRunConfig: vi.fn(() => new Promise(() => {})),
  fetchRuns: vi.fn(() => new Promise(() => {})),
  fetchRun: vi.fn(),
  deleteRun: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  fetchLiveRun: vi.fn(() => new Promise(() => {})),
}))

afterEach(cleanup)

function renderPane(
  mode: CaptureMode,
  connectionStatus: ConnectionStatus = 'connected',
  opts: { setup?: SetupMode; kinds?: string[] } = {},
) {
  const kinds = opts.kinds ?? ['baseline']
  const byKind = new Map<string, CurveRecord[]>(kinds.map((k) => [k, []]))
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeContext.Provider value={{ mode: opts.setup ?? 'full', setMode: vi.fn() }}>
          <CaptureModeContext.Provider value={{ mode, setMode: vi.fn() }}>
            <MeasurePane
              kinds={kinds}
              byKind={byKind}
              curves={[]}
              connected
              connectionStatus={connectionStatus}
              onSaved={vi.fn()}
              onRunSaved={vi.fn()}
            />
          </CaptureModeContext.Provider>
        </SetupModeContext.Provider>
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

  it('defaults to the curve tab, with Run an algorithm reachable alongside it', () => {
    renderPane('hardware')
    expect(screen.getByText('Capturing under:')).toBeTruthy()
    expect(screen.getByText('Run an algorithm')).toBeTruthy()
  })

  it('switches to the run pane without disturbing the curve flow', () => {
    renderPane('hardware')
    fireEvent.click(screen.getByText('Run an algorithm'))
    expect(screen.getByText('Live MPPT run')).toBeTruthy()
    expect(screen.queryByText('Capturing under:')).toBeNull()

    fireEvent.click(screen.getByText('Capture a curve'))
    expect(screen.getByText('Capturing under:')).toBeTruthy()
    expect(isDisabled(button('Start Measurement'))).toBe(false)
  })

  it('offers a simulated run in simulated (demo) mode instead of blocking it', () => {
    renderPane('simulated')
    fireEvent.click(screen.getByText('Run an algorithm'))
    // A simulated run needs no board, so demo mode does not disable
    // starting one the way it disables Start Measurement above - it
    // labels the run as simulated instead (RunPane's own tests cover the
    // labelling in detail; this only checks the two panes stay
    // consistent about what demo mode blocks and what it doesn't).
    expect(screen.queryByText(/unavailable in demo mode/i)).toBeNull()
    expect(screen.getByText(/drives a simulated converter/i)).toBeTruthy()
  })

  it('blocks starting a run with no live link to the board', () => {
    renderPane('hardware', 'disconnected')
    fireEvent.click(screen.getByText('Run an algorithm'))
    expect(isDisabled(button('Start run'))).toBe(true)
    expect(screen.getByText(/No live link to the board/)).toBeTruthy()
  })
})

describe('MeasurePane setup mode', () => {
  it('offers Tilted as a kind to capture in Full setup', () => {
    renderPane('hardware', 'connected', { setup: 'full', kinds: ['baseline', 'tilted'] })
    const capturingUnder = screen.getByText('Capturing under:').parentElement!
    expect(within(capturingUnder).getByText('Tilted')).toBeTruthy()
  })

  it('hides Tilted as a kind to capture in Single setup, with a one-line note why', () => {
    renderPane('hardware', 'connected', { setup: 'single', kinds: ['baseline', 'tilted'] })
    const capturingUnder = screen.getByText('Capturing under:').parentElement!
    expect(within(capturingUnder).queryByText('Tilted')).toBeNull()
    expect(screen.getByText(/Tilted needs panel B/)).toBeTruthy()
  })
})
