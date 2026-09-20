import { describe, expect, it } from 'vitest'
import { reportFilenameBase, reportToJson, reportToMarkdown } from '@/lib/reportExport'
import type { ReportRecord } from '@/lib/reports'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

function report(overrides: Partial<ReportRecord> = {}): ReportRecord {
  return {
    id: '20260919T160000Z-panel-a',
    title: 'Panel A alone under the lamp',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T17:30:00+00:00',
    fields: { panel: 'Luxen LN-10P, 10 W, 12 V', light_source: '' },
    steps: [
      {
        id: 'meter-vout',
        section: 'Before energizing',
        title: 'Meter check of V out',
        instructions: 'Compare the meter to the board.',
        kind: 'check',
        status: 'done',
        value: null,
        unit: null,
        notes: 'Matched within 0.1 V.',
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
        status: 'done',
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
        status: 'done',
        value: null,
        unit: null,
        notes: '',
        curve_ids: [],
        run_ids: ['r1'],
        repeats: 1,
      },
    ],
    open_questions: [{ id: 'temperature', text: 'How to record it?', answer: 'Not yet decided.' }],
    ...overrides,
  }
}

function curve(overrides: Partial<CurveRecord> = {}): CurveRecord {
  return {
    id: 'c1',
    path: '/data/curves/c1.json',
    captured_at: '2026-09-19T16:05:00Z',
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

describe('reportFilenameBase', () => {
  it('combines the sanitized title with a filesystem-safe timestamp', () => {
    expect(
      reportFilenameBase({ title: 'Panel A alone', created_at: '2026-09-19T16:00:00+00:00' }),
    ).toBe('panel-a-alone_2026-09-19T16-00-00+00-00')
  })
})

describe('reportToJson', () => {
  it('round-trips the record exactly', () => {
    const r = report()
    expect(JSON.parse(reportToJson(r))).toEqual(r)
  })
})

describe('reportToMarkdown', () => {
  it('includes the title, setup fields, and every step', () => {
    const md = reportToMarkdown(report(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('# Panel A alone under the lamp')
    expect(md).toContain('Light source: -')
    expect(md).toContain('#### Meter check of V out (done)')
    expect(md).toContain('Matched within 0.1 V.')
  })

  it('shows a missing linked curve without crashing', () => {
    const md = reportToMarkdown(report(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('missing-curve: missing (deleted)')
  })

  it('includes per-step statistics for a curve step with repeats', () => {
    const md = reportToMarkdown(
      report(),
      [curve({ id: 'c1', voc: 20 }), curve({ id: 'missing-curve' })],
      [runSummary()],
      { r1: runDetail() },
    )
    // Only c1 resolves (missing-curve is dropped, not found in the curves list)
    expect(md).toContain('n = 1')
  })

  it('includes run statistics (held power, P/MPP_th) when a run detail is supplied', () => {
    const md = reportToMarkdown(report(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toMatch(/Held power:.*W/)
  })

  it('shows a missing linked run without crashing', () => {
    const md = reportToMarkdown(
      report({
        steps: [
          {
            id: 'po-run',
            section: 'Runs',
            title: 'P&O run',
            instructions: '',
            kind: 'run',
            status: 'todo',
            value: null,
            unit: null,
            notes: '',
            curve_ids: [],
            run_ids: ['does-not-exist'],
            repeats: 1,
          },
        ],
      }),
      [curve()],
      [],
      {},
    )
    expect(md).toContain('does-not-exist: missing (deleted)')
  })

  it('includes open questions and their answers', () => {
    const md = reportToMarkdown(report(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('How to record it?')
    expect(md).toContain('Not yet decided.')
  })
})
