import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurveWorkbench } from './CurveWorkbench'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { SetupModeContext, type SetupMode } from '@/lib/setupMode'
import type { CurveRecord, PanelSetup } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(() => new Promise(() => {})),
  startSweep: vi.fn().mockResolvedValue(undefined),
  startDemoSweep: vi.fn().mockResolvedValue(undefined),
  releaseRelay: vi.fn().mockResolvedValue(undefined),
  saveCurve: vi.fn().mockResolvedValue({ path: '/data/curves/new.json' }),
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

import { fetchLiveSweep, releaseRelay, saveCurve, startDemoSweep, startSweep } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.localStorage.clear()
})

function renderWorkbench(
  demo: boolean,
  opts: {
    emphasizeReplay?: boolean
    setup?: SetupMode
    onSaved?: (kind: string) => void
    initialPanels?: PanelSetup[]
    records?: CurveRecord[]
  } = {},
) {
  const tree = (setup: SetupMode) => (
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeContext.Provider value={{ mode: setup, setMode: vi.fn() }}>
          <CurveWorkbench
            kind="baseline"
            records={opts.records ?? []}
            connected={!demo}
            onSaved={opts.onSaved ?? vi.fn()}
            demo={demo}
            emphasizeReplay={opts.emphasizeReplay ?? false}
            initialPanels={opts.initialPanels}
          />
        </SetupModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>
  )
  const result = render(tree(opts.setup ?? 'full'))
  // Re-renders the same tree with another setup, so the form stays mounted
  // and keeps its state, as it does when the header toggle is used.
  return { ...result, setSetup: (setup: SetupMode) => result.rerender(tree(setup)) }
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

describe('CurveWorkbench setup mode', () => {
  async function renderWithCapture(opts: Parameters<typeof renderWorkbench>[1] = {}) {
    vi.mocked(fetchLiveSweep).mockResolvedValue({
      points: [
        { v: 0, i: 0.2 },
        { v: 20, i: 0 },
      ],
      partial: [],
      active: false,
      link: 'ok',
      seq: 1,
      commandError: null,
      demoSource: false,
    })
    const view = renderWorkbench(false, opts)
    // A default label so Save curve's enablement below depends only on
    // `hasCapture` - tests that care about a specific label set their own
    // afterward, overwriting this one.
    fireEvent.change(screen.getByPlaceholderText(/label, e.g/), { target: { value: 'capture' } })
    await waitFor(() => expect(isDisabled(button('Save curve'))).toBe(false))
    return view
  }

  it('drops panel B from a save after switching from Full to Single with the form open', async () => {
    const view = await renderWithCapture({ setup: 'full' })
    view.setSetup('single')
    expect(screen.queryByText('Panel B tilt')).toBeNull()
    fireEvent.click(button('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    expect(vi.mocked(saveCurve).mock.calls[0][0].panels).toEqual([{ id: 'A', tilt_deg: 90 }])
  })

  it('shows Panel B tilt in Full setup (today\'s behaviour)', () => {
    renderWorkbench(false, { setup: 'full' })
    expect(screen.getByText('Panel B tilt')).toBeTruthy()
  })

  it('hides Panel B tilt in Single setup, and explains the one-panel setup instead', () => {
    renderWorkbench(false, { setup: 'single' })
    expect(screen.queryByText('Panel B tilt')).toBeNull()
    expect(screen.getByText(/Single setup: one panel/)).toBeTruthy()
  })

  it('sends exactly one panel on a Single-setup save', async () => {
    await renderWithCapture({ setup: 'single' })
    fireEvent.change(screen.getByPlaceholderText(/label, e.g/), {
      target: { value: 'single panel save' },
    })
    fireEvent.click(button('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    const call = vi.mocked(saveCurve).mock.calls[0][0]
    expect(call.panels).toEqual([{ id: 'A', tilt_deg: 90 }])
  })

  it('sends both panels on a Full-setup save', async () => {
    await renderWithCapture({ setup: 'full' })
    fireEvent.change(screen.getByPlaceholderText(/label, e.g/), {
      target: { value: 'full setup save' },
    })
    fireEvent.click(button('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    const call = vi.mocked(saveCurve).mock.calls[0][0]
    expect(call.panels).toHaveLength(2)
  })

  it('remeasuring a two-panel curve in Single setup keeps panel B, rather than silently dropping it', async () => {
    await renderWithCapture({
      setup: 'single',
      initialPanels: [
        { id: 'A', tilt_deg: 90 },
        { id: 'B', tilt_deg: 60 },
      ],
    })
    // The field itself is back, driven by the curve being replaced, even
    // though the global setup is Single - and a note says why.
    expect(screen.getByText('Panel B tilt')).toBeTruthy()
    expect(screen.getByText(/keeps both, even though setup is Single/)).toBeTruthy()

    fireEvent.click(button('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    const call = vi.mocked(saveCurve).mock.calls[0][0]
    expect(call.panels).toEqual([
      { id: 'A', tilt_deg: 90 },
      { id: 'B', tilt_deg: 60 },
    ])
  })

  it('remeasuring a one-panel curve in Full setup does not gain a panel B it never had', async () => {
    await renderWithCapture({
      setup: 'full',
      initialPanels: [{ id: 'A', tilt_deg: 90 }],
    })
    expect(screen.queryByText('Panel B tilt')).toBeNull()

    fireEvent.click(button('Save curve'))

    await waitFor(() => expect(saveCurve).toHaveBeenCalled())
    const call = vi.mocked(saveCurve).mock.calls[0][0]
    expect(call.panels).toEqual([{ id: 'A', tilt_deg: 90 }])
  })
})

describe('CurveWorkbench save form accessibility', () => {
  // Both fields used to carry only a placeholder, which disappears the
  // moment someone types into them and isn't a reliable accessible name
  // for a screen reader - give them a real one.
  it('gives the label and notes inputs an accessible name', () => {
    renderWorkbench(false)
    expect(screen.getByRole('textbox', { name: 'Curve label' })).toBeTruthy()
    expect(screen.getByRole('textbox', { name: 'Notes' })).toBeTruthy()
  })
})

describe('CurveWorkbench saved-curves table', () => {
  const record: CurveRecord = {
    id: 'saved-1',
    path: '/data/curves/saved-1.json',
    captured_at: '2026-01-01T00:00:00Z',
    label: 'Saved curve',
    measurement: 'baseline',
    panels: [{ id: 'A', tilt_deg: 90 }],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 20,
    isc: 0.25,
    p_mpp: 3.5,
    points: [
      { v: 0, i: 0.25 },
      { v: 20, i: 0 },
    ],
  }

  // Every other reading on the page (CurveMetadata, run readouts) follows
  // the header's A/mA unit toggle - this table used to hardcode mA/mW
  // regardless of it, which meant it could disagree with the rest of the
  // screen about what unit a number was in.
  it('shows Isc/P_mpp in milliamps/milliwatts by default', () => {
    renderWorkbench(false, { records: [record] })
    expect(screen.getByText('250.0 mA')).toBeTruthy()
    expect(screen.getByText('3500.0 mW')).toBeTruthy()
  })

  it('follows the unit toggle into amps/watts', () => {
    window.localStorage.setItem('mpp-sdk.units', 'base')
    renderWorkbench(false, { records: [record] })
    expect(screen.getByText('0.250 A')).toBeTruthy()
    expect(screen.getByText('3.500 W')).toBeTruthy()
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
