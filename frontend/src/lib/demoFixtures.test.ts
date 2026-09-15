import { describe, expect, it } from 'vitest'
import {
  DEMO_CURVE_BRIGHT,
  DEMO_CURVE_DIM,
  DEMO_RUN,
  generateDemoRunSamples,
  PHASE1_SAMPLES,
  PHASE2_SAMPLES,
} from './demoFixtures'

describe('DEMO_CURVE_BRIGHT / DEMO_CURVE_DIM', () => {
  it('are flagged as replayed, never as a live measurement', () => {
    expect(DEMO_CURVE_BRIGHT.source).toBe('firmware-replay')
    expect(DEMO_CURVE_DIM.source).toBe('firmware-replay')
  })

  it('are labeled as bundled demo fixtures, not confusable with the real library', () => {
    expect(DEMO_CURVE_BRIGHT.label.toLowerCase()).toContain('demo')
    expect(DEMO_CURVE_DIM.label.toLowerCase()).toContain('demo')
  })

  it('carry the real bench headline numbers for the bright sweep', () => {
    expect(DEMO_CURVE_BRIGHT.voc).toBeCloseTo(19.337)
    expect(DEMO_CURVE_BRIGHT.isc).toBeCloseTo(0.607)
    expect(DEMO_CURVE_BRIGHT.p_mpp).toBeCloseTo(7.707)
    expect(DEMO_CURVE_BRIGHT.points).toHaveLength(20)
  })

  it('carry the real bench headline numbers for the dim sweep', () => {
    expect(DEMO_CURVE_DIM.voc).toBeCloseTo(18.62)
    expect(DEMO_CURVE_DIM.isc).toBeCloseTo(0.229)
    expect(DEMO_CURVE_DIM.p_mpp).toBeCloseTo(3.072)
    expect(DEMO_CURVE_DIM.points).toHaveLength(20)
  })

  it('have distinct paths, so a run can reference one unambiguously', () => {
    expect(DEMO_CURVE_BRIGHT.path).not.toBe(DEMO_CURVE_DIM.path)
  })
})

describe('generateDemoRunSamples', () => {
  const samples = generateDemoRunSamples(DEMO_CURVE_BRIGHT.points)
  const totalSamples = PHASE1_SAMPLES + PHASE2_SAMPLES

  it('produces a few hundred samples', () => {
    expect(samples).toHaveLength(totalSamples)
    expect(samples.length).toBeGreaterThanOrEqual(200)
    expect(samples.length).toBeLessThanOrEqual(400)
  })

  it('has strictly increasing, honestly paced timestamps', () => {
    for (let k = 1; k < samples.length; k++) {
      expect(samples[k].t).toBeGreaterThan(samples[k - 1].t)
    }
  })

  it('starts near Voc and hill-climbs down toward the MPP voltage', () => {
    expect(samples[0].v).toBeGreaterThan(18)
    const endOfHillClimb = samples[PHASE1_SAMPLES - 1].v
    expect(endOfHillClimb).toBeLessThan(samples[0].v)
    expect(endOfHillClimb).toBeCloseTo(13.9, 0)
  })

  it('is monotonically non-increasing in voltage during the hill-climb', () => {
    for (let k = 1; k < PHASE1_SAMPLES; k++) {
      expect(samples[k].v).toBeLessThanOrEqual(samples[k - 1].v)
    }
  })

  it('oscillates in a small cycle around the MPP once it gets there, not sitting flat', () => {
    const tail = samples.slice(-PHASE2_SAMPLES).map((s) => s.v)
    for (const v of tail) {
      expect(v).toBeGreaterThanOrEqual(13.6)
      expect(v).toBeLessThanOrEqual(14.2)
    }
    expect(new Set(tail.map((v) => v.toFixed(1))).size).toBeGreaterThan(1)
  })

  it('raises duty as voltage falls, matching the SEPIC sign convention', () => {
    for (let k = 1; k < PHASE1_SAMPLES; k++) {
      expect(samples[k].d).toBeGreaterThanOrEqual(samples[k - 1].d)
    }
  })

  it('reads current off the golden curve rather than inventing one', () => {
    for (const s of samples) {
      expect(s.i).toBeGreaterThanOrEqual(0)
      expect(s.i).toBeLessThanOrEqual(DEMO_CURVE_BRIGHT.isc + 0.01)
    }
  })

  it('is a pure function of the points it is given', () => {
    const again = generateDemoRunSamples(DEMO_CURVE_BRIGHT.points)
    expect(again).toEqual(samples)
  })
})

describe('DEMO_RUN', () => {
  it('resolves to the bright demo curve by filename, the same way a real run does', () => {
    expect(DEMO_RUN.curve_ref).toBe(DEMO_CURVE_BRIGHT.path.split('/').pop())
  })

  it('is labeled, annotated, and flagged as simulated - not a captured run', () => {
    expect(DEMO_RUN.label.toLowerCase()).toContain('demo')
    expect(DEMO_RUN.notes.toLowerCase()).toContain('synthetic')
    expect(DEMO_RUN.source).toBe('simulated')
  })

  it('is not marked aborted', () => {
    expect(DEMO_RUN.aborted).toBe(false)
  })
})
