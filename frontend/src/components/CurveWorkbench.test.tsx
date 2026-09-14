import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurveWorkbench } from './CurveWorkbench'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  startSweep: vi.fn().mockResolvedValue(undefined),
  startDemoSweep: vi.fn().mockResolvedValue(undefined),
  releaseRelay: vi.fn().mockResolvedValue(undefined),
  saveCurve: vi.fn().mockResolvedValue(undefined),
}))

// This suite drives a real state transition through the demo replay
// (active: false -> true, then point by point), which means LiveChart
// genuinely re-renders with new data - and chart.js's responsive-resize
// codepath crashes on that under jsdom regardless of the data's content
// (a canvas-attachment check chart.js gets right in a real browser but
// not here). The gating behaviour under test - which buttons are
// disabled, which endpoints get called - has nothing to do with chart.js
// actually drawing, so the chart itself is stubbed out rather than
// fighting an unrelated jsdom incompatibility.
vi.mock('react-chartjs-2', () => ({ Line: () => null }))

import { releaseRelay, saveCurve, startDemoSweep, startSweep } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderWorkbench(demo: boolean, opts: { emphasizeReplay?: boolean } = {}) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CurveWorkbench
          kind="baseline"
          records={[]}
          connected={!demo}
          onSaved={vi.fn()}
          demo={demo}
          emphasizeReplay={opts.emphasizeReplay ?? false}
        />
      </UnitsProvider>
    </ThemeProvider>,
  )
}

function button(text: string) {
  const el = screen.getByText(text).closest('button')
  if (!el) throw new Error(`no button ancestor for "${text}"`)
  return el
}

// Start Measurement/Release Relay/Save curve carry a `title` explaining a
// demo-mode disablement, so they use focusableWhenDisabled (aria-disabled,
// not the native attribute) to keep that title reachable by hover/focus -
// see button.tsx and CurveDashboardPane's note on the same fix. The
// Demo-curve buttons have no such title and stay natively disabled. This
// checks either form, so a test doesn't care which mechanism a given
// button happens to use.
function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true'
}

describe('CurveWorkbench outside demo mode', () => {
  it('leaves Start Measurement enabled once connected', () => {
    renderWorkbench(false)
    expect(isDisabled(button('Start Measurement'))).toBe(false)
  })

  it('shows no demo-mode callout', () => {
    renderWorkbench(false)
    expect(screen.queryByText(/Demo mode:/)).toBeNull()
  })
})

describe('CurveWorkbench in demo mode', () => {
  it('disables Start Measurement and Release Relay, and never calls their hardware endpoints', () => {
    renderWorkbench(true)
    expect(isDisabled(button('Start Measurement'))).toBe(true)
    expect(isDisabled(button('Release Relay'))).toBe(true)

    fireEvent.click(button('Start Measurement'))
    fireEvent.click(button('Release Relay'))
    expect(startSweep).not.toHaveBeenCalled()
    expect(releaseRelay).not.toHaveBeenCalled()
  })

  it('leaves the demo-curve buttons enabled, replaying locally instead of over SPI', async () => {
    renderWorkbench(true)
    expect(isDisabled(button('Demo curve (bright)'))).toBe(false)

    fireEvent.click(button('Demo curve (bright)'))
    await waitFor(() => expect(screen.getByText(/capturing/)).toBeTruthy())
    expect(startDemoSweep).not.toHaveBeenCalled()
  })

  it('disables Save curve even before/after a replay, since a replay must not enter the real library', () => {
    renderWorkbench(true)
    expect(isDisabled(button('Save curve'))).toBe(true)

    fireEvent.click(button('Save curve'))
    expect(saveCurve).not.toHaveBeenCalled()
  })

  it('explains the demo-mode disablement without needing to hover it', () => {
    renderWorkbench(true)
    const start = button('Start Measurement')
    expect(start.getAttribute('title')).toMatch(/unavailable in demo mode/i)
    // Also true independent of hover - a persistent callout on screen.
    expect(screen.getByText(/Demo mode:/)).toBeTruthy()
  })

  it('explains itself with a visible demo-mode callout', () => {
    renderWorkbench(true)
    expect(screen.getByText(/Demo mode:/)).toBeTruthy()
  })
})

describe('CurveWorkbench in Demo with PICO mode (emphasizeReplay, not demo)', () => {
  it('sends the real SPI command - this is not a local replay', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(isDisabled(button('Demo curve (bright)'))).toBe(false)

    fireEvent.click(button('Demo curve (bright)'))
    expect(startDemoSweep).toHaveBeenCalledWith(true)
  })

  it('leaves Start Measurement and Save curve fully working', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(isDisabled(button('Start Measurement'))).toBe(false)
    // Save curve is still gated on having a completed capture and a
    // label, same as hardware mode - not on emphasizeReplay.
    expect(isDisabled(button('Save curve'))).toBe(true)
  })

  it('explains itself with a distinct callout from the fully-offline Demo mode', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(screen.getByText(/Demo with PICO:/)).toBeTruthy()
    expect(screen.queryByText(/^Demo mode:/)).toBeNull()
  })
})

describe('CurveWorkbench demo curve buttons', () => {
  it('are absent in hardware mode, where the point is measuring a real panel', () => {
    renderWorkbench(false)
    expect(screen.queryByText('Demo curve (dim)')).toBeNull()
    expect(screen.queryByText('Demo curve (bright)')).toBeNull()
    // The real actions are still there.
    expect(screen.getByText('Start Measurement')).toBeTruthy()
    expect(screen.getByText('Release Relay')).toBeTruthy()
  })

  it('are shown in Demo with PICO, where they are the primary action', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(screen.getByText('Demo curve (dim)')).toBeTruthy()
    expect(screen.getByText('Demo curve (bright)')).toBeTruthy()
  })

  it('are shown in Demo, where they replay a bundled fixture locally', () => {
    renderWorkbench(true)
    expect(screen.getByText('Demo curve (dim)')).toBeTruthy()
    expect(screen.getByText('Demo curve (bright)')).toBeTruthy()
  })
})
