import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportView } from './ReportView'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { ReportPatch, ReportRecord } from '@/lib/reports'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

// ReportView renders CurveChart (react-chartjs-2/chart.js) for every
// linked curve - jsdom has no canvas backend, so this is stubbed the same
// way App.test.tsx/CurveWorkbench.test.tsx already do for the same reason.
vi.mock('react-chartjs-2', () => ({ Line: () => null }))

function renderView(ui: Parameters<typeof render>[0]) {
  return render(
    <ThemeProvider>
      <UnitsProvider>{ui}</UnitsProvider>
    </ThemeProvider>,
  )
}

function curve(overrides: Partial<CurveRecord> = {}): CurveRecord {
  return {
    id: 'c1',
    path: '/data/curves/c1.json',
    captured_at: '2026-09-19T16:00:00Z',
    label: 'Baseline sweep',
    measurement: 'baseline',
    panels: [{ id: 'A', tilt_deg: 90 }],
    notes: '',
    n_points: 3,
    source: 'hardware',
    voc: 19.3,
    isc: 0.6,
    p_mpp: 7.7,
    points: [
      { v: 0, i: 0.6 },
      { v: 13.9, i: 0.55 },
      { v: 19.3, i: 0 },
    ],
    ...overrides,
  }
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'r1',
    path: '/data/runs/r1.json',
    captured_at: '2026-09-19T16:10:00Z',
    label: 'P&O run 1',
    algorithm: 'P&O',
    n_samples: 2,
    duration_s: 10,
    aborted: false,
    curve_ref: 'c1',
    notes: '',
    source: 'hardware',
    ...overrides,
  }
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runSummary(),
    downsampled: false,
    samples: [
      { t: 0, v: 19, i: 0.01, d: 0.1 },
      { t: 5, v: 13.9, i: 0.55, d: 0.4 },
    ],
    ...overrides,
  }
}

function report(overrides: Partial<ReportRecord> = {}): ReportRecord {
  return {
    id: 'r-panel-a',
    title: 'Panel A alone under the lamp',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T17:30:00+00:00',
    fields: { panel: 'Luxen LN-10P, 10 W, 12 V' },
    steps: [
      {
        id: 'firmware-config',
        section: 'Before energizing',
        title: 'Firmware configuration',
        instructions: 'Check the firmware build.',
        kind: 'check',
        status: 'todo',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: [],
        repeats: 1,
      },
      {
        id: 'panel-label-voc',
        section: 'Before energizing',
        title: 'Panel label Voc',
        instructions: 'Read Voc from the label.',
        kind: 'number',
        status: 'todo',
        value: null,
        unit: 'V',
        notes: '',
        curve_ids: [],
        run_ids: [],
        repeats: 1,
      },
      {
        id: 'baseline-curve',
        section: 'Light and curve',
        title: 'Baseline curve',
        instructions: 'Capture and save one sweep.',
        kind: 'curve',
        status: 'todo',
        value: null,
        unit: null,
        notes: '',
        curve_ids: ['c1', 'missing-curve'],
        run_ids: [],
        repeats: 2,
      },
      {
        id: 'po-run',
        section: 'Runs',
        title: 'P&O run',
        instructions: 'Run P&O for 10 s.',
        kind: 'run',
        status: 'todo',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: [],
        repeats: 1,
      },
    ],
    open_questions: [{ id: 'temperature', text: 'How to record temperature?', answer: '' }],
    ...overrides,
  }
}

function stepCard(id: string): HTMLElement {
  return document.querySelector(`[data-step-id="${id}"]`) as HTMLElement
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('ReportView - document', () => {
  it('renders the header, progress, setup fields, sections and open questions', () => {
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly onPatch={undefined} />,
    )
    expect(screen.getByText('Panel A alone under the lamp')).toBeTruthy()
    expect(screen.getByText(/single-panel-characterization/)).toBeTruthy()
    expect(screen.getByText('0 / 4')).toBeTruthy() // n_done / n_steps
    expect(screen.getByDisplayValue('Luxen LN-10P, 10 W, 12 V')).toBeTruthy()
    expect(screen.getByText('Before energizing')).toBeTruthy()
    expect(screen.getByText('Light and curve')).toBeTruthy()
    expect(screen.getByText('How to record temperature?')).toBeTruthy()
  })

  it('shows a missing linked curve without crashing, alongside the found one', () => {
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly onPatch={undefined} />,
    )
    expect(screen.getByText(/missing-curve.*missing/)).toBeTruthy()
    expect(screen.getByText('Baseline sweep')).toBeTruthy()
  })
})

describe('ReportView - editing (online)', () => {
  it('sends a status change immediately, not debounced', async () => {
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly={false} onPatch={onPatch} />,
    )
    const select = within(stepCard('firmware-config')).getByLabelText('Step status')
    fireEvent.change(select, { target: { value: 'done' } })

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith({ steps: [{ id: 'firmware-config', status: 'done' }] }),
    )
  })

  it('debounces a typed number value and sends the merged patch once', async () => {
    vi.useFakeTimers()
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly={false} onPatch={onPatch} />,
    )
    const input = within(stepCard('panel-label-voc')).getByLabelText(/Value/)
    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.change(input, { target: { value: '23' } })
    fireEvent.change(input, { target: { value: '23.5' } })

    expect(onPatch).not.toHaveBeenCalled() // still inside the debounce window

    await vi.advanceTimersByTimeAsync(700)

    expect(onPatch).toHaveBeenCalledTimes(1)
    expect(onPatch).toHaveBeenCalledWith({ steps: [{ id: 'panel-label-voc', value: 23.5 }] })
  })

  it('links a picked curve immediately, appending to the existing links', async () => {
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    const c2 = curve({ id: 'c2', label: 'Second sweep' })
    renderView(
      <ReportView
        report={report()}
        curves={[curve(), c2]}
        runs={[runSummary()]}
        readOnly={false}
        onPatch={onPatch}
      />,
    )
    const card = stepCard('baseline-curve')
    fireEvent.change(within(card).getByLabelText('Pick a curve to link'), {
      target: { value: 'c2' },
    })
    fireEvent.click(within(card).getByText('Link'))

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith({
        steps: [{ id: 'baseline-curve', curve_ids: ['c1', 'missing-curve', 'c2'] }],
      }),
    )
  })

  it('unlinks a missing curve via its "Remove link" action', async () => {
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly={false} onPatch={onPatch} />,
    )
    const card = stepCard('baseline-curve')
    fireEvent.click(within(card).getByText('Remove link'))

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith({
        steps: [{ id: 'baseline-curve', curve_ids: ['c1'] }],
      }),
    )
  })

  it('"Link most recent run" links the newest run by captured_at', async () => {
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    const older = runSummary({ id: 'r-old', captured_at: '2026-09-01T00:00:00Z' })
    const newer = runSummary({ id: 'r-new', captured_at: '2026-09-19T16:10:00Z' })
    renderView(
      <ReportView
        report={report()}
        curves={[curve()]}
        runs={[older, newer]}
        readOnly={false}
        onPatch={onPatch}
      />,
    )
    const card = stepCard('po-run')
    fireEvent.click(within(card).getByText('Link most recent run'))

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith({ steps: [{ id: 'po-run', run_ids: ['r-new'] }] }),
    )
  })

  it('debounces an open-question answer', async () => {
    vi.useFakeTimers()
    const onPatch = vi.fn(async (patch: ReportPatch) => ({ ...report(), ...patch }) as ReportRecord)
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly={false} onPatch={onPatch} />,
    )
    const box = screen.getByLabelText('Answer: How to record temperature?')
    fireEvent.change(box, { target: { value: 'Contact thermometer.' } })

    await vi.advanceTimersByTimeAsync(700)

    expect(onPatch).toHaveBeenCalledWith({
      open_questions: [{ id: 'temperature', answer: 'Contact thermometer.' }],
    })
  })

  it('shows a saving/saved indicator around a patch', async () => {
    let resolvePatch!: (r: ReportRecord) => void
    const onPatch = vi.fn(
      () => new Promise<ReportRecord>((resolve) => { resolvePatch = resolve }),
    )
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly={false} onPatch={onPatch} />,
    )
    const select = within(stepCard('firmware-config')).getByLabelText('Step status')
    fireEvent.change(select, { target: { value: 'done' } })

    await waitFor(() => expect(screen.getByText('Saving...')).toBeTruthy())
    resolvePatch(report())
    await waitFor(() => expect(screen.getByText('Saved')).toBeTruthy())
  })
})

describe('ReportView - statistics', () => {
  it('shows per-step curve statistics over the found linked curves', () => {
    const twoLinked = report({
      steps: [
        {
          ...report().steps[2],
          curve_ids: ['c1', 'c2'],
        },
      ],
    })
    renderView(
      <ReportView
        report={twoLinked}
        curves={[curve({ id: 'c1', voc: 19 }), curve({ id: 'c2', voc: 21 })]}
        runs={[]}
        readOnly
        onPatch={undefined}
      />,
    )
    // mean Voc of 19 and 21 is 20.000
    expect(screen.getByText(/Voc: median 20.000 V, mean 20.000 V/)).toBeTruthy()
  })

  it('shows run statistics (held power, P/MPP_th) when run detail is supplied', () => {
    const runStep = report({
      steps: [
        {
          ...report().steps[3],
          run_ids: ['r1'],
        },
      ],
    })
    renderView(
      <ReportView
        report={runStep}
        curves={[curve()]}
        runs={[runSummary()]}
        runDetails={{ r1: runDetail() }}
        readOnly
        onPatch={undefined}
      />,
    )
    expect(screen.getAllByText(/Held/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Held power:/)).toBeTruthy() // the stats block specifically
  })

  it('shows a missing linked run without crashing', () => {
    const runStep = report({
      steps: [
        {
          ...report().steps[3],
          run_ids: ['does-not-exist'],
        },
      ],
    })
    renderView(
      <ReportView report={runStep} curves={[curve()]} runs={[]} readOnly onPatch={undefined} />,
    )
    expect(screen.getByText(/does-not-exist.*missing/)).toBeTruthy()
  })
})

describe('ReportView - read-only (demo)', () => {
  it('shows a Read-only badge and disables every edit control', () => {
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly onPatch={undefined} />,
    )
    expect(screen.getByText('Read-only')).toBeTruthy()
    const select = within(stepCard('firmware-config')).getByLabelText('Step status') as HTMLSelectElement
    expect(select.disabled).toBe(true)
    const fieldInput = screen.getByDisplayValue('Luxen LN-10P, 10 W, 12 V') as HTMLInputElement
    expect(fieldInput.readOnly).toBe(true)
    // No linking controls at all in read-only mode.
    expect(screen.queryByLabelText('Pick a curve to link')).toBeNull()
    expect(screen.queryByText('Link most recent curve')).toBeNull()
  })

  it('never calls onPatch even if a discrete action were somehow triggered (guarded by disabling in the DOM)', () => {
    const onPatch = vi.fn()
    renderView(
      <ReportView report={report()} curves={[curve()]} runs={[runSummary()]} readOnly onPatch={onPatch} />,
    )
    // onPatch is ignored entirely in read-only mode (useDebouncedPatch is
    // constructed with `undefined` whenever readOnly is true - see
    // ReportView's own onPatch wiring).
    expect(onPatch).not.toHaveBeenCalled()
  })
})

// A linked curve/run used to render as an always-open ~190x96px chart -
// too small to read at the bench. These cover the fix: each linked item
// is now a one-line row that expands on click.
describe('ReportView - expandable linked items', () => {
  function reportWithLinkedItems(): ReportRecord {
    const base = report()
    return report({
      steps: [
        { ...base.steps[2], curve_ids: ['c1'] }, // baseline-curve
        { ...base.steps[3], run_ids: ['r1'] }, // po-run
      ],
    })
  }

  it('a curve row starts collapsed, showing its key numbers, then expands and collapses on click', () => {
    renderView(
      <ReportView
        report={reportWithLinkedItems()}
        curves={[curve()]}
        runs={[runSummary()]}
        runDetails={{ r1: runDetail() }}
        readOnly={false}
        onPatch={vi.fn()}
      />,
    )
    const toggle = screen.getByRole('button', { name: /Baseline sweep/ })
    // Key numbers on the collapsed line - Voc is unit-independent, a
    // simple thing to pin without also pinning the mA/W formatting.
    expect(toggle.textContent).toMatch(/Voc 19\.30 V/)
    expect(toggle.textContent).toMatch(/P_mpp/)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.h-56')).toBeNull() // no chart yet
    expect(screen.queryByText('Open')).toBeNull()

    fireEvent.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('.h-56')).not.toBeNull() // CurveChart, at a readable size
    const row = toggle.parentElement as HTMLElement
    expect(within(row).getByText('Open')).toBeTruthy()
    expect(within(row).getByText('Unlink')).toBeTruthy()

    fireEvent.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.h-56')).toBeNull()
  })

  it('a run row starts collapsed, showing algorithm/duration/held power, then expands to its trace', () => {
    renderView(
      <ReportView
        report={reportWithLinkedItems()}
        curves={[curve()]}
        runs={[runSummary()]}
        runDetails={{ r1: runDetail() }}
        readOnly={false}
        onPatch={vi.fn()}
      />,
    )
    const toggle = screen.getByRole('button', { name: /P&O run 1/ })
    expect(toggle.textContent).toMatch(/P&O/)
    expect(toggle.textContent).toMatch(/10\.0 s/)
    expect(toggle.textContent).toMatch(/Held/)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.h-80')).toBeNull() // no RunChart yet

    fireEvent.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('.h-80')).not.toBeNull() // RunChart, the run's full trace
    const row = toggle.parentElement as HTMLElement
    expect(within(row).getByText('Open')).toBeTruthy()
    expect(within(row).getByText('Unlink')).toBeTruthy()

    fireEvent.click(toggle)

    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  it('"Expand all" opens every linked item and "Collapse all" closes them again', () => {
    renderView(
      <ReportView
        report={reportWithLinkedItems()}
        curves={[curve()]}
        runs={[runSummary()]}
        runDetails={{ r1: runDetail() }}
        readOnly={false}
        onPatch={vi.fn()}
      />,
    )
    const curveToggle = screen.getByRole('button', { name: /Baseline sweep/ })
    const runToggle = screen.getByRole('button', { name: /P&O run 1/ })
    expect(curveToggle.getAttribute('aria-expanded')).toBe('false')
    expect(runToggle.getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(screen.getByText('Expand all'))

    expect(curveToggle.getAttribute('aria-expanded')).toBe('true')
    expect(runToggle.getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('.h-56')).not.toBeNull()
    expect(document.querySelector('.h-80')).not.toBeNull()

    fireEvent.click(screen.getByText('Collapse all'))

    expect(curveToggle.getAttribute('aria-expanded')).toBe('false')
    expect(runToggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.h-56')).toBeNull()
    expect(document.querySelector('.h-80')).toBeNull()

    // A row can still be toggled by itself in between signals.
    fireEvent.click(curveToggle)
    expect(curveToggle.getAttribute('aria-expanded')).toBe('true')
    expect(runToggle.getAttribute('aria-expanded')).toBe('false')
  })

  it('a missing linked curve/run still shows its message and never crashes, with no expand row', () => {
    const missingBoth = report({
      steps: [
        { ...report().steps[2], curve_ids: ['missing-curve'] },
        { ...report().steps[3], run_ids: ['missing-run'] },
      ],
    })
    renderView(
      <ReportView report={missingBoth} curves={[]} runs={[]} readOnly onPatch={undefined} />,
    )
    expect(screen.getByText(/missing-curve.*missing/)).toBeTruthy()
    expect(screen.getByText(/missing-run.*missing/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /missing-curve/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /missing-run/ })).toBeNull()
  })

  it('read-only mode shows no Unlink action on an expanded row', () => {
    renderView(
      <ReportView
        report={reportWithLinkedItems()}
        curves={[curve()]}
        runs={[runSummary()]}
        runDetails={{ r1: runDetail() }}
        readOnly
        onPatch={undefined}
      />,
    )
    const toggle = screen.getByRole('button', { name: /Baseline sweep/ })
    fireEvent.click(toggle)
    const row = toggle.parentElement as HTMLElement
    expect(within(row).getByText('Open')).toBeTruthy()
    expect(within(row).queryByText('Unlink')).toBeNull()
  })
})
