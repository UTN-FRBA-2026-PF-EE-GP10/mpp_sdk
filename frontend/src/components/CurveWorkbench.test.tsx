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

describe('CurveWorkbench outside demo mode', () => {
  it('leaves Start Measurement enabled once connected', () => {
    renderWorkbench(false)
    expect(button('Start Measurement').disabled).toBe(false)
  })

  it('shows no demo-mode callout', () => {
    renderWorkbench(false)
    expect(screen.queryByText(/Demo mode:/)).toBeNull()
  })
})

describe('CurveWorkbench in demo mode', () => {
  it('disables Start Measurement and Release Relay, and never calls their hardware endpoints', () => {
    renderWorkbench(true)
    expect(button('Start Measurement').disabled).toBe(true)
    expect(button('Release Relay').disabled).toBe(true)

    fireEvent.click(button('Start Measurement'))
    fireEvent.click(button('Release Relay'))
    expect(startSweep).not.toHaveBeenCalled()
    expect(releaseRelay).not.toHaveBeenCalled()
  })

  it('leaves the demo-curve buttons enabled, replaying locally instead of over SPI', async () => {
    renderWorkbench(true)
    expect(button('Demo curve (bright)').disabled).toBe(false)

    fireEvent.click(button('Demo curve (bright)'))
    await waitFor(() => expect(screen.getByText(/capturing/)).toBeTruthy())
    expect(startDemoSweep).not.toHaveBeenCalled()
  })

  it('disables Save curve even before/after a replay, since a replay must not enter the real library', () => {
    renderWorkbench(true)
    expect(button('Save curve').disabled).toBe(true)

    fireEvent.click(button('Save curve'))
    expect(saveCurve).not.toHaveBeenCalled()
  })

  it('explains itself with a visible demo-mode callout', () => {
    renderWorkbench(true)
    expect(screen.getByText(/Demo mode:/)).toBeTruthy()
  })
})

describe('CurveWorkbench in Demo with Pi mode (emphasizeReplay, not demo)', () => {
  it('sends the real SPI command - this is not a local replay', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(button('Demo curve (bright)').disabled).toBe(false)

    fireEvent.click(button('Demo curve (bright)'))
    expect(startDemoSweep).toHaveBeenCalledWith(true)
  })

  it('leaves Start Measurement and Save curve fully working', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(button('Start Measurement').disabled).toBe(false)
    // Save curve is still gated on having a completed capture and a
    // label, same as hardware mode - not on emphasizeReplay.
    expect(button('Save curve').disabled).toBe(true)
  })

  it('explains itself with a distinct callout from the fully-offline Demo mode', () => {
    renderWorkbench(false, { emphasizeReplay: true })
    expect(screen.getByText(/Demo with Pi:/)).toBeTruthy()
    expect(screen.queryByText(/^Demo mode:/)).toBeNull()
  })
})
