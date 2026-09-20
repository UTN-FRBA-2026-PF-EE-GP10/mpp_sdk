import { describe, expect, it } from 'vitest'
import type { RunDetail } from '@/lib/runs'
import type { SessionRecord } from '@/lib/sessions'
import {
  MAX_SESSION_BYTES,
  SESSION_FORMAT,
  SESSION_SCHEMA,
  SessionParseError,
  buildSessionFile,
  parseSessionFile,
  readSessionFile,
  sessionFileName,
} from './sessionFile'
import type { CurveRecord } from '@/types'

function curve(id: string): CurveRecord {
  return {
    id,
    path: `/data/curves/${id}.json`,
    captured_at: '2026-09-19T16:00:00Z',
    label: `Curve ${id}`,
    measurement: 'baseline',
    panels: [{ id: 'A', tilt_deg: 90 }],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 20,
    isc: 0.5,
    p_mpp: 7,
    points: [
      { v: 0, i: 0.5 },
      { v: 20, i: 0 },
    ],
  }
}

function run(id: string): RunDetail {
  return {
    id,
    path: `/data/runs/${id}.json`,
    captured_at: '2026-09-19T16:05:00Z',
    label: `Run ${id}`,
    algorithm: 'P&O',
    n_samples: 2,
    duration_s: 1,
    aborted: false,
    curve_ref: null,
    notes: '',
    source: 'hardware',
    downsampled: false,
    samples: [
      { t: 0, v: 20, i: 0, d: 0.2 },
      { t: 1, v: 14, i: 0.4, d: 0.4 },
    ],
  }
}

function session(overrides: Partial<SessionRecord> = {}): SessionRecord {
  return {
    id: '20260919T160000Z-panel-a',
    title: 'Panel A alone under the lamp',
    template_id: 'single-panel-characterization',
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T17:30:00+00:00',
    fields: { panel: 'Luxen LN-10P, 10 W, 12 V' },
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
        notes: '',
        curve_ids: [],
        run_ids: [],
        repeats: 1,
      },
    ],
    open_questions: [{ id: 'temperature', text: 'How to record it?', answer: '' }],
    ...overrides,
  }
}

function toFile(content: string, name = 'session.mppsession.json'): File {
  return new File([content], name, { type: 'application/json' })
}

describe('buildSessionFile / parseSessionFile round trip', () => {
  it('parses back exactly what was built, curves and runs both', () => {
    const built = buildSessionFile({
      title: 'Panel A alone under the lamp',
      setup: 'single',
      curves: [curve('c1'), curve('c2')],
      runs: [run('r1')],
    })
    const parsed = parseSessionFile(JSON.parse(JSON.stringify(built)))

    expect(parsed.format).toBe(SESSION_FORMAT)
    expect(parsed.schema).toBe(SESSION_SCHEMA)
    expect(parsed.title).toBe('Panel A alone under the lamp')
    expect(parsed.setup).toBe('single')
    expect(parsed.session).toBeNull()
    expect(parsed.curves.map((e) => e.id)).toEqual(['c1', 'c2'])
    expect(parsed.curves[0].record).toEqual(curve('c1'))
    expect(parsed.runs.map((e) => e.id)).toEqual(['r1'])
    expect(parsed.runs[0].record.samples).toEqual(run('r1').samples)
    expect(parsed.missing).toEqual({ curve_ids: [], run_ids: [] })
  })

  it('round-trips through readSessionFile (JSON serialize + File + parse)', async () => {
    const built = buildSessionFile({
      title: 'Two-panel session',
      setup: 'full',
      curves: [curve('c1')],
      runs: [run('r1')],
      session: session(),
    })
    const file = toFile(JSON.stringify(built))
    const parsed = await readSessionFile(file)

    expect(parsed.title).toBe('Two-panel session')
    expect(parsed.session).toEqual(session())
    expect(parsed.curves[0].record.id).toBe('c1')
    expect(parsed.runs[0].record.samples.length).toBe(2)
  })

  it('carries missing ids through the round trip', () => {
    const built = buildSessionFile({
      title: 't',
      setup: 'single',
      curves: [],
      runs: [],
      missing: { curve_ids: ['gone-curve'], run_ids: ['gone-run'] },
    })
    const parsed = parseSessionFile(JSON.parse(JSON.stringify(built)))
    expect(parsed.missing).toEqual({ curve_ids: ['gone-curve'], run_ids: ['gone-run'] })
  })
})

describe('sessionFileName', () => {
  it('appends the .mppsession.json suffix, keeping spacing and case', () => {
    expect(sessionFileName('Panel A alone under the lamp')).toBe(
      'Panel A alone under the lamp.mppsession.json',
    )
  })

  it('swaps filesystem-illegal characters for a hyphen', () => {
    expect(sessionFileName('A/B: test?')).toBe('A-B- test-.mppsession.json')
  })

  it('falls back to "session" for an empty title', () => {
    expect(sessionFileName('   ')).toBe('session.mppsession.json')
  })
})

describe('rejecting bad session files', () => {
  it('rejects the wrong format', async () => {
    const file = toFile(JSON.stringify({ format: 'something-else', schema: 1 }))
    await expect(readSessionFile(file)).rejects.toThrow(SessionParseError)
  })

  it('rejects an unsupported schema', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [] })
    const file = toFile(JSON.stringify({ ...built, schema: 99 }))
    await expect(readSessionFile(file)).rejects.toThrow(/schema/)
  })

  it('rejects a file over the 50 MB size limit without reading it', async () => {
    const file = toFile('{}')
    Object.defineProperty(file, 'size', { value: MAX_SESSION_BYTES + 1 })
    await expect(readSessionFile(file)).rejects.toThrow(/too large/)
  })

  it('rejects invalid JSON', async () => {
    const file = toFile('{not json')
    await expect(readSessionFile(file)).rejects.toThrow(/JSON/)
  })

  it('rejects a malformed curve record (missing points)', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [curve('c1')], runs: [] })
    const broken = JSON.parse(JSON.stringify(built))
    delete broken.curves[0].record.points
    const file = toFile(JSON.stringify(broken))
    await expect(readSessionFile(file)).rejects.toThrow(SessionParseError)
  })

  it('rejects a malformed run record (a sample missing a field)', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1')] })
    const broken = JSON.parse(JSON.stringify(built))
    broken.runs[0].record.samples[0] = { t: 0, v: 20 } // missing i, d
    const file = toFile(JSON.stringify(broken))
    await expect(readSessionFile(file)).rejects.toThrow(SessionParseError)
  })

  it('rejects a malformed session record (a step missing a field)', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [], session: session() })
    const broken = JSON.parse(JSON.stringify(built))
    delete broken.session.steps[0].kind
    const file = toFile(JSON.stringify(broken))
    await expect(readSessionFile(file)).rejects.toThrow(SessionParseError)
  })

  it('rejects a plain array (not an object) at the top level', async () => {
    const file = toFile(JSON.stringify([1, 2, 3]))
    await expect(readSessionFile(file)).rejects.toThrow(SessionParseError)
  })
})
