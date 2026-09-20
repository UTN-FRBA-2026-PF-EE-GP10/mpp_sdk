import { describe, expect, it } from 'vitest'
import { sessionExportFile, sessionFilenameBase, sessionToJson, sessionToMarkdown } from '@/lib/sessionExport'
import type { SessionRecord } from '@/lib/sessions'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

function session(overrides: Partial<SessionRecord> = {}): SessionRecord {
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

describe('sessionFilenameBase', () => {
  it('combines the sanitized title with a filesystem-safe timestamp', () => {
    expect(
      sessionFilenameBase({ title: 'Panel A alone', created_at: '2026-09-19T16:00:00+00:00' }),
    ).toBe('panel-a-alone_2026-09-19T16-00-00+00-00')
  })
})

describe('sessionToJson', () => {
  it('round-trips the record exactly', () => {
    const r = session()
    expect(JSON.parse(sessionToJson(r))).toEqual(r)
  })
})

describe('sessionToMarkdown', () => {
  it('includes the title, setup fields, and every step', () => {
    const md = sessionToMarkdown(session(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('# Panel A alone under the lamp')
    expect(md).toContain('Light source: -')
    expect(md).toContain('#### Meter check of V out (done)')
    expect(md).toContain('Matched within 0.1 V.')
  })

  it('renders an unset panel model snapshot as a dash, never 0, NaN, null or undefined', () => {
    const unset = session({
      fields: {
        panel: 'Acme A-1',
        panel_model_voc: '21',
        panel_model_vmp: '',
        panel_model_imp: '',
      },
    })
    const md = sessionToMarkdown(unset, [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('- Panel model voc: 21')
    expect(md).toContain('- Panel model vmp: -')
    expect(md).toContain('- Panel model imp: -')
    const fieldLines = md.split('\n').filter((line) => line.startsWith('- Panel'))
    for (const line of fieldLines) {
      expect(line).not.toMatch(/NaN|undefined|null|: 0$/)
    }
  })

  it('shows a missing linked curve without crashing', () => {
    const md = sessionToMarkdown(session(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('missing-curve: missing (deleted)')
  })

  it('includes per-step statistics for a curve step with repeats', () => {
    const md = sessionToMarkdown(
      session(),
      [curve({ id: 'c1', voc: 20 }), curve({ id: 'missing-curve' })],
      [runSummary()],
      { r1: runDetail() },
    )
    // Only c1 resolves (missing-curve is dropped, not found in the curves list)
    expect(md).toContain('n = 1')
  })

  it('includes run statistics (held power, P/MPP_th) when a run detail is supplied', () => {
    const md = sessionToMarkdown(session(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toMatch(/Held power:.*W/)
  })

  it('shows a missing linked run without crashing', () => {
    const md = sessionToMarkdown(
      session({
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
    const md = sessionToMarkdown(session(), [curve()], [runSummary()], { r1: runDetail() })
    expect(md).toContain('How to record it?')
    expect(md).toContain('Not yet decided.')
  })
})

describe('sessionExportFile', () => {
  it('bundles the session with every found curve and run its steps link', () => {
    const file = sessionExportFile(session(), [curve()], { r1: runDetail() })
    expect(file.session).toEqual(session())
    expect(file.curves.map((e) => e.id)).toEqual(['c1'])
    expect(file.runs.map((e) => e.id)).toEqual(['r1'])
  })

  it('names a linked curve or run the library does not have in missing', () => {
    // baseline-curve links c1 and missing-curve; po-run links r1 only.
    const file = sessionExportFile(session(), [curve()], { r1: runDetail() })
    expect(file.missing.curve_ids).toEqual(['missing-curve'])
    expect(file.missing.run_ids).toEqual([])
  })

  it('is a pure function of runDetails: an id absent from it is always missing, in flight or not', () => {
    // sessionExportFile itself cannot tell "deleted from the library" apart
    // from "not fetched yet" - that distinction lives in the caller (see
    // SessionPane's runDetailsPending / SessionView's disabled Export
    // button, which exist precisely so this function is never called
    // while a linked run's detail fetch is still in flight).
    const file = sessionExportFile(session(), [curve()], {})
    expect(file.missing.run_ids).toEqual(['r1'])
  })

  it('titles and sets up the file from the session, not from a prompt', () => {
    const file = sessionExportFile(session(), [curve()], { r1: runDetail() })
    expect(file.title).toBe(session().title)
    expect(file.setup).toBe(session().setup)
  })
})
