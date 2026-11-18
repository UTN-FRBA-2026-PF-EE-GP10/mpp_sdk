import { describe, expect, it } from 'vitest'
import {
  alphaDegForPower,
  clampWarmupS,
  clampWindowS,
  lampPhaseText,
  parseLampPhase,
  parseWarmupLeft,
  powerForAlpha,
} from './lamp'

describe('lamp measurement helpers', () => {
  it('clamps the warm-up to 0..30 and falls back to 3', () => {
    expect(clampWarmupS(-5)).toBe(0)
    expect(clampWarmupS(99)).toBe(30)
    expect(clampWarmupS(NaN)).toBe(3)
  })

  it('reads an unknown phase as none', () => {
    expect(parseLampPhase('warming')).toBe('warming')
    expect(parseLampPhase('weird')).toBeNull()
    expect(parseLampPhase(undefined)).toBeNull()
    expect(parseWarmupLeft('x')).toBeNull()
  })

  it('words the phases', () => {
    expect(lampPhaseText('warming', 1.2)).toBe('Warming up the lamp, 2 s')
    expect(lampPhaseText('measuring', null)).toBe('Lamp on for the measurement')
    expect(lampPhaseText('off', null, false)).toBeNull()
    expect(lampPhaseText('off', null, true)).toBe(
      'The lamp is off, this measurement is running without light',
    )
  })
})

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
