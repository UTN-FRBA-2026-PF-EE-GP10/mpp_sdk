import { describe, expect, it } from 'vitest'
import {
  findCurveForRun,
  referenceCurveMessage,
  runDuration,
  sampleIndexAtTime,
  trailUpTo,
} from './runPlayback'
import type { RunSample } from '@/lib/runs'
import type { CurveRecord } from '@/types'

function sample(t: number, v = 10, i = 0.1, d = 0.5): RunSample {
  return { t, v, i, d }
}

describe('runDuration', () => {
  it('is zero for an empty run', () => {
    expect(runDuration([])).toBe(0)
  })

  it('is zero for a single-sample run', () => {
    expect(runDuration([sample(5)])).toBe(0)
  })

  it('is the span between the first and last sample, not the raw timestamps', () => {
    // Samples carry whatever wall-clock offset the control loop's clock
    // happened to start at - only the span between them is playback time.
    expect(runDuration([sample(100), sample(101.5), sample(103)])).toBeCloseTo(3)
  })
})

describe('sampleIndexAtTime', () => {
  it('is -1 for an empty run', () => {
    expect(sampleIndexAtTime([], 1)).toBe(-1)
  })

  it('clamps to the first sample before playback starts', () => {
    const samples = [sample(10), sample(11), sample(12)]
    expect(sampleIndexAtTime(samples, -5)).toBe(0)
    expect(sampleIndexAtTime(samples, 0)).toBe(0)
  })

  it('clamps to the last sample past the end of the run', () => {
    const samples = [sample(10), sample(11), sample(12)]
    expect(sampleIndexAtTime(samples, 999)).toBe(2)
  })

  it('picks the last sample whose relative time has not yet passed', () => {
    const samples = [sample(0), sample(1), sample(2), sample(3)]
    expect(sampleIndexAtTime(samples, 1.9)).toBe(1)
    expect(sampleIndexAtTime(samples, 2.0)).toBe(2)
    expect(sampleIndexAtTime(samples, 2.1)).toBe(2)
  })

  it('handles unevenly spaced samples correctly', () => {
    // Real SPI round-trip time varies (see RunSample's docstring) - the
    // mapping must not assume a fixed step.
    const samples = [sample(0), sample(0.1), sample(2.0), sample(2.05)]
    expect(sampleIndexAtTime(samples, 1.0)).toBe(1)
    expect(sampleIndexAtTime(samples, 2.02)).toBe(2)
  })

  it('uses the first sample as the time origin, not zero', () => {
    const samples = [sample(50), sample(51), sample(52)]
    expect(sampleIndexAtTime(samples, 0.5)).toBe(0)
    expect(sampleIndexAtTime(samples, 1.5)).toBe(1)
  })
})

describe('trailUpTo', () => {
  it('is empty for a negative index', () => {
    expect(trailUpTo([sample(0), sample(1)], -1)).toEqual([])
  })

  it('includes every sample up to and including the index', () => {
    const samples = [sample(0), sample(1), sample(2)]
    expect(trailUpTo(samples, 1)).toEqual([samples[0], samples[1]])
  })

  it('includes the whole run at the last index', () => {
    const samples = [sample(0), sample(1), sample(2)]
    expect(trailUpTo(samples, 2)).toEqual(samples)
  })
})

function curve(path: string): CurveRecord {
  // The server derives a curve's id from its filename stem - keep that
  // relationship here, since findCurveForRun matches against both.
  const id = path.split('/').pop()!.replace(/\.json$/, '')
  return {
    id,
    path,
    captured_at: '2026-09-13T08:00:00Z',
    label: 'ref',
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 21.3,
    isc: 0.215,
    p_mpp: 3.51,
    points: [
      { v: 0, i: 0.215 },
      { v: 21.3, i: 0 },
    ],
  }
}

describe('findCurveForRun', () => {
  it('is null when the run has no curve_ref', () => {
    expect(findCurveForRun([curve('/data/curves/a.json')], null)).toBeNull()
  })

  it('matches on the basename, since curve_ref is a filename and path is a full path', () => {
    const record = curve('/data/curves/20260908T120000Z-baseline.json')
    expect(findCurveForRun([record], '20260908T120000Z-baseline.json')).toBe(record)
  })

  it('matches on the bare id, the form a run started from the web UI stores', () => {
    const record = curve('/data/curves/20260908T120000Z-baseline.json')
    expect(findCurveForRun([record], '20260908T120000Z-baseline')).toBe(record)
  })

  it('is null when no fetched curve matches the ref', () => {
    expect(findCurveForRun([curve('/data/curves/other.json')], 'missing.json')).toBeNull()
  })
})

describe('referenceCurveMessage', () => {
  it('explains that this run never had a reference curve', () => {
    expect(referenceCurveMessage(null, null)).toBe('No reference curve was captured for this run.')
  })

  it('explains that the referenced curve is gone, distinctly from never having had one', () => {
    const message = referenceCurveMessage('missing.json', null)
    expect(message).toContain('missing.json')
    expect(message).not.toBe(referenceCurveMessage(null, null))
  })

  it('says a demo curve is only viewable in Demo mode, not that it was deleted', () => {
    const message = referenceCurveMessage('demo-fixture-psf10-bright', null)
    expect(message).toContain('Demo mode')
    expect(message).not.toContain('deleted')
  })

  it('is null once a reference curve is found', () => {
    expect(referenceCurveMessage('a.json', curve('/data/curves/a.json'))).toBeNull()
  })
})
