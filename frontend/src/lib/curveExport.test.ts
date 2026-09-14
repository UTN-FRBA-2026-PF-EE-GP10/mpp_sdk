import { describe, expect, it } from 'vitest'
import { curveFilenameBase, curveToCsv, sanitizeFilenamePart } from './curveExport'

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
