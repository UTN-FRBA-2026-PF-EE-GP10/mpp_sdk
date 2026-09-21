import { describe, expect, it } from 'vitest'
import { findCurveForRun, referenceCurveMessage } from '@/lib/runPlayback'
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
  withoutCurveDirectories,
  withoutRunDirectories,
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
    expect(parsed.curves[0].record).toEqual({ ...curve('c1'), path: 'c1.json' })
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

  it('keeps an unset panel model snapshot unset through a session file, never 0, NaN or null', async () => {
    // A panel model with an unset Vmp/Imp snapshots those two fields as
    // empty strings (see lib/panels.ts); a session file must hand them
    // back as the same empty strings.
    const unset = session({
      fields: {
        panel: 'Acme A-1',
        panel_model_voc: '21',
        panel_model_isc: '',
        panel_model_vmp: '',
        panel_model_imp: '',
      },
    })
    const built = buildSessionFile({
      title: 'Unset snapshot',
      setup: 'single',
      curves: [],
      runs: [],
      session: unset,
    })
    const parsed = await readSessionFile(toFile(JSON.stringify(built)))

    expect(parsed.session?.fields).toEqual(unset.fields)
    for (const key of ['panel_model_isc', 'panel_model_vmp', 'panel_model_imp']) {
      expect(parsed.session?.fields[key]).toBe('')
    }
  })

  it('imports a run exported without duration_s, exactly as the server used to serve it', async () => {
    // The run detail route did not send duration_s, so JSON.stringify
    // dropped the key from every file exported before the server fix.
    const { duration_s: _omitted, ...serverShaped } = run('r1')
    const built = buildSessionFile({
      title: 't',
      setup: 'single',
      curves: [],
      runs: [serverShaped as unknown as RunDetail],
    })
    const file = toFile(JSON.stringify(built))
    expect(JSON.parse(await file.text()).runs[0].record).not.toHaveProperty('duration_s')

    const parsed = await readSessionFile(file)

    expect(parsed.runs[0].record.duration_s).toBe(1)
    expect(parsed.runs[0].record.samples).toEqual(run('r1').samples)
  })

  it('derives an absent duration_s from the first and last sample', () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1')] })
    const raw = JSON.parse(JSON.stringify(built))
    delete raw.runs[0].record.duration_s
    raw.runs[0].record.samples = [
      { t: 2, v: 20, i: 0, d: 0.2 },
      { t: 3.5, v: 18, i: 0.2, d: 0.3 },
      { t: 7.25, v: 14, i: 0.4, d: 0.4 },
    ]
    expect(parseSessionFile(raw).runs[0].record.duration_s).toBeCloseTo(5.25)
  })

  it('gives a run with fewer than two samples a duration of 0 when duration_s is absent', () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1'), run('r2')] })
    const raw = JSON.parse(JSON.stringify(built))
    delete raw.runs[0].record.duration_s
    delete raw.runs[1].record.duration_s
    raw.runs[0].record.samples = [{ t: 4, v: 20, i: 0, d: 0.2 }]
    raw.runs[1].record.samples = []
    const parsed = parseSessionFile(raw)
    expect(parsed.runs[0].record.duration_s).toBe(0)
    expect(parsed.runs[1].record.duration_s).toBe(0)
  })

  it('keeps a present duration_s as written', () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1')] })
    const raw = JSON.parse(JSON.stringify(built))
    raw.runs[0].record.duration_s = 42
    expect(parseSessionFile(raw).runs[0].record.duration_s).toBe(42)
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

describe('server directories in a session file', () => {
  const homeDir = '/home/someone/project/data'

  function absoluteCurve(id: string): CurveRecord {
    return { ...curve(id), path: `${homeDir}/curves/${id}.json` }
  }

  function absoluteRun(id: string): RunDetail {
    return {
      ...run(id),
      path: `${homeDir}/runs/${id}.json`,
      curve_ref: `${homeDir}/curves/c1.json`,
      notes: `error: [Errno 2] No such file or directory: '${homeDir}/runs/${id}.json'`,
    }
  }

  function exported() {
    return buildSessionFile({
      title: 'Panel A alone under the lamp',
      setup: 'single',
      curves: [absoluteCurve('c1')],
      runs: [absoluteRun('x')],
      session: session(),
    })
  }

  it('writes only bare file names, with no directory anywhere in the file text', () => {
    const text = JSON.stringify(exported(), null, 2)

    expect(text).not.toContain('/home/')
    expect(text).not.toContain(homeDir)
    const paths = [...text.matchAll(/"path":\s*"([^"]*)"/g)].map((m) => m[1])
    expect(paths).toEqual(['c1.json', 'x.json'])
    for (const p of paths) expect(p).not.toMatch(/[/\\]/)
    // No string value anywhere may look like an absolute path or an IPv4 address.
    expect(text).not.toMatch(/"\/[^"]*\/[^"]*"/)
    expect(text).not.toMatch(/\b\d{1,3}(\.\d{1,3}){3}\b/)
  })

  it('imports back what it exported', async () => {
    const parsed = await readSessionFile(toFile(JSON.stringify(exported())))

    expect(parsed.curves[0].record.path).toBe('c1.json')
    expect(parsed.runs[0].record.path).toBe('x.json')
    expect(parsed.runs[0].record.curve_ref).toBe('c1.json')
    expect(parsed.runs[0].record.notes).toBe("error: [Errno 2] No such file or directory: 'x.json'")
    expect(findCurveForRun([parsed.curves[0].record], parsed.runs[0].record.curve_ref)).toBe(
      parsed.curves[0].record,
    )
  })

  it('still imports an older file that carries absolute paths, without keeping them', async () => {
    const raw = JSON.parse(JSON.stringify(exported()))
    raw.curves[0].record.path = `${homeDir}/curves/c1.json`
    raw.runs[0].record.path = `${homeDir}/runs/x.json`
    raw.runs[0].record.curve_ref = `${homeDir}/curves/c1.json`
    raw.runs[0].record.notes = `error: ${homeDir}/runs/x.json`

    const parsed = await readSessionFile(toFile(JSON.stringify(raw)))

    expect(parsed.curves[0].record.path).toBe('c1.json')
    expect(parsed.runs[0].record.path).toBe('x.json')
    expect(parsed.runs[0].record.notes).toBe('error: x.json')
    expect(JSON.stringify(parsed)).not.toContain('/home/')
  })

  it('cuts a Windows path with backslashes down to the file name', () => {
    const c = withoutCurveDirectories({ ...curve('c1'), path: 'C:\\Users\\someone\\data\\curves\\c1.json' })
    const r = withoutRunDirectories({ ...run('x'), path: 'C:\\Users\\someone\\data\\runs\\x.json' })
    expect(c.path).toBe('c1.json')
    expect(r.path).toBe('x.json')
  })

  it('falls back to <id>.json for a path that ends in a separator, never keeping the directory', () => {
    expect(withoutCurveDirectories({ ...curve('c1'), path: '/home/someone/curves/' }).path).toBe('c1.json')
    expect(withoutRunDirectories({ ...run('x'), path: 'C:\\Users\\someone\\' }).path).toBe('x.json')
    expect(withoutRunDirectories({ ...run('x'), path: '' }).path).toBe('x.json')
  })

  it('keeps an empty or null curve_ref empty or null, and drops the directory of a trailing-slash one', () => {
    expect(withoutRunDirectories({ ...run('x'), curve_ref: null }).curve_ref).toBeNull()
    expect(withoutRunDirectories({ ...run('x'), curve_ref: '' }).curve_ref).toBe('')
    expect(withoutRunDirectories({ ...run('x'), curve_ref: '/home/someone/runs/' }).curve_ref).toBe('')
    expect(withoutRunDirectories({ ...run('x'), curve_ref: 'C:\\Users\\someone\\' }).curve_ref).toBe('')
    expect(withoutRunDirectories({ ...run('x'), curve_ref: 'C:\\Users\\someone\\c1.json' }).curve_ref).toBe(
      'c1.json',
    )
  })

  it('resolves an empty curve_ref to no reference curve without matching anything', () => {
    const cleaned = withoutRunDirectories({ ...run('x'), curve_ref: '/home/someone/runs/' })
    expect(findCurveForRun([curve('c1')], cleaned.curve_ref)).toBeNull()
    expect(referenceCurveMessage(cleaned.curve_ref, null)).toBe(
      'Reference curve "" was not found - it may have been deleted.',
    )
  })

  it('keeps only the last segment of any absolute path in a run note', () => {
    const scrub = (notes: string) => withoutRunDirectories({ ...run('x'), notes }).notes
    expect(scrub('/dev/x/y')).toBe('y')
    expect(scrub("error: [Errno 2] No such file or directory: '/dev/spidev0.0'")).toBe(
      "error: [Errno 2] No such file or directory: 'spidev0.0'",
    )
    expect(scrub('error: /home/someone/project/data/runs/x.json failed')).toBe('error: x.json failed')
    expect(scrub('open(/var/lib/mpp/x.json) failed')).toBe('open(x.json) failed')
  })

  it('leaves note text that only contains slashes unchanged', () => {
    const scrub = (notes: string) => withoutRunDirectories({ ...run('x'), notes }).notes
    for (const text of [
      'V/I',
      'dv/dt',
      '50/60 Hz',
      'a/b',
      '0.5/0.6',
      'https://example.org/a/b',
      '2026/09/21',
      'overvoltage',
      '',
    ]) {
      expect(scrub(text)).toBe(text)
    }
  })

  it('leaves a bare curve id and plain abort reasons alone', () => {
    const plain = { ...run('r1'), curve_ref: 'c1', notes: 'overvoltage' }
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [plain] })
    expect(built.runs[0].record.curve_ref).toBe('c1')
    expect(built.runs[0].record.notes).toBe('overvoltage')
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

  it('rejects a present duration_s that is not a number', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1')] })
    const broken = JSON.parse(JSON.stringify(built))
    broken.runs[0].record.duration_s = '1'
    const file = toFile(JSON.stringify(broken))
    await expect(readSessionFile(file)).rejects.toThrow('duration_s must be a number')
  })

  it('rejects a null duration_s instead of treating it as absent', async () => {
    const built = buildSessionFile({ title: 't', setup: 'single', curves: [], runs: [run('r1')] })
    const broken = JSON.parse(JSON.stringify(built))
    broken.runs[0].record.duration_s = null
    const file = toFile(JSON.stringify(broken))
    await expect(readSessionFile(file)).rejects.toThrow('duration_s must be a number')
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
