import { describe, expect, it } from 'vitest'
import type { CurveRecord } from '@/types'
import { curveFilenameBase, curveToCsv, curveToJson, sanitizeFilenamePart } from './curveExport'

describe('sanitizeFilenamePart', () => {
  it('lowercases and hyphenates punctuation and spaces', () => {
    expect(sanitizeFilenamePart('Both flat, midday sun!')).toBe('both-flat-midday-sun')
  })

  it('trims leading and trailing hyphens', () => {
    expect(sanitizeFilenamePart('  --weird--  ')).toBe('weird')
  })

  it('falls back to "curve" for an empty or all-punctuation label', () => {
    expect(sanitizeFilenamePart('')).toBe('curve')
    expect(sanitizeFilenamePart('!!!')).toBe('curve')
  })
})

describe('curveFilenameBase', () => {
  it('combines the sanitized label with a filesystem-safe timestamp', () => {
    expect(
      curveFilenameBase({ label: 'Both Flat', captured_at: '2026-09-13T08:30:00.000Z' }),
    ).toBe('both-flat_2026-09-13T08-30-00-000Z')
  })
})

describe('curveToCsv', () => {
  it('writes a unit-labelled header and one row per point', () => {
    const csv = curveToCsv({ points: [{ v: 21.3, i: 0.006 }, { v: 18.0, i: 0.195 }] })
    expect(csv).toBe('voltage (V),current (A)\n21.3,0.006\n18,0.195')
  })

  it('produces just the header for an empty sweep', () => {
    expect(curveToCsv({ points: [] })).toBe('voltage (V),current (A)')
  })
})

describe('curveToJson', () => {
  const record: CurveRecord = {
    id: 'c1',
    path: '/home/someone/project/data/curves/c1.json',
    captured_at: '2026-09-19T16:00:00Z',
    label: 'Curve c1',
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 1,
    source: 'hardware',
    voc: 20,
    isc: 0.5,
    p_mpp: 7,
    points: [{ v: 0, i: 0.5 }],
  }

  it('keeps only the file name in path, so the download has no server directory', () => {
    const text = curveToJson(record)
    expect(text).not.toContain('/home/')
    expect(JSON.parse(text)).toEqual({ ...record, path: 'c1.json' })
  })

  it('cuts a Windows-style path down to the file name too', () => {
    const text = curveToJson({ ...record, path: 'C:\\Users\\someone\\data\\c1.json' })
    expect(JSON.parse(text).path).toBe('c1.json')
  })
})
