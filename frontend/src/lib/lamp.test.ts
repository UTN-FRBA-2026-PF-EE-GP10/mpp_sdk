import { describe, expect, it } from 'vitest'
import { alphaDegForPower, clampWindowS, powerForAlpha } from './lamp'

describe('alphaDegForPower', () => {
  it('maps the ends', () => {
    expect(alphaDegForPower(0)).toBe(180)
    expect(alphaDegForPower(1)).toBe(0)
  })

  it('gives 90 degrees at half power', () => {
    expect(alphaDegForPower(0.5)).toBeCloseTo(90, 6)
  })

  it('inverts powerForAlpha and falls as power rises', () => {
    let last = 181
    for (const p of [0.05, 0.1, 0.3, 0.7, 0.95]) {
      const a = alphaDegForPower(p)
      expect(powerForAlpha((a * Math.PI) / 180)).toBeCloseTo(p, 9)
      expect(a).toBeLessThan(last)
      last = a
    }
  })

  it('clamps out of range input', () => {
    expect(alphaDegForPower(-1)).toBe(180)
    expect(alphaDegForPower(2)).toBe(0)
  })
})

describe('clampWindowS', () => {
  it('clamps to 1..120 and falls back on NaN', () => {
    expect(clampWindowS(0)).toBe(1)
    expect(clampWindowS(500)).toBe(120)
    expect(clampWindowS(45)).toBe(45)
    expect(clampWindowS(Number.NaN)).toBe(30)
  })
})
