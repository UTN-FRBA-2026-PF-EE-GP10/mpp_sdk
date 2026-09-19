import { describe, expect, it } from 'vitest'
import {
  computeStats,
  curveMetrics,
  curveStepStats,
  runMetrics,
  runStepStats,
} from '@/lib/reportStats'
import type { RunSample } from '@/lib/runs'
import type { CurveRecord } from '@/types'

function curve(overrides: Partial<CurveRecord> = {}): CurveRecord {
  return {
    id: 'c1',
    path: '/data/curves/c1.json',
    captured_at: '2026-01-01T00:00:00Z',
    label: 'curve',
    measurement: 'baseline',
    panels: [],
    notes: '',
    n_points: 2,
    source: 'hardware',
    voc: 20,
    isc: 0.6,
    p_mpp: 7,
    points: [
      { v: 0, i: 0.6 },
      { v: 14, i: 0.5 }, // P = 7, the max
      { v: 20, i: 0 },
    ],
    ...overrides,
  }
}

describe('computeStats', () => {
  it('is null for an empty sample', () => {
    expect(computeStats([])).toBeNull()
  })

  it('shows the value alone with no deviation at n = 1', () => {
    const stats = computeStats([5])
    expect(stats).toEqual({ n: 1, median: 5, mean: 5, std: null, min: 5, max: 5 })
  })

  it('computes median/mean/sample std (n - 1) over an odd-sized sample', () => {
    const stats = computeStats([1, 2, 3])!
    expect(stats.n).toBe(3)
    expect(stats.median).toBe(2)
    expect(stats.mean).toBeCloseTo(2)
    expect(stats.std).toBeCloseTo(1) // sqrt(((1)^2+(0)^2+(1)^2)/2) = 1
    expect(stats.min).toBe(1)
    expect(stats.max).toBe(3)
  })

  it('averages the two middle values for an even-sized sample', () => {
    const stats = computeStats([1, 2, 3, 4])!
    expect(stats.median).toBe(2.5)
  })

  it('does not require the input sorted', () => {
    const stats = computeStats([3, 1, 2])!
    expect(stats.median).toBe(2)
    expect(stats.min).toBe(1)
    expect(stats.max).toBe(3)
  })
})

describe('curveMetrics', () => {
  it('reads Voc/Isc off the record and Vmp/Imp/P_mpp off the measured MPP', () => {
    const m = curveMetrics(curve())!
    expect(m.voc).toBe(20)
    expect(m.isc).toBe(0.6)
    expect(m.vmp).toBe(14)
    expect(m.imp).toBe(0.5)
    expect(m.pMpp).toBe(7)
  })

  it('is null for a curve with no points', () => {
    expect(curveMetrics(curve({ points: [] }))).toBeNull()
  })
})

describe('curveStepStats', () => {
  it('summarizes each metric across several linked curves', () => {
    const stats = curveStepStats([
      curve({ id: 'c1', voc: 20, points: [{ v: 14, i: 0.5 }] }),
      curve({ id: 'c2', voc: 22, points: [{ v: 15, i: 0.5 }] }),
    ])
    expect(stats.voc?.n).toBe(2)
    expect(stats.voc?.mean).toBe(21)
    expect(stats.vmp?.mean).toBe(14.5)
  })

  it('drops curves with no points instead of failing the whole step', () => {
    const stats = curveStepStats([curve({ points: [] }), curve({ voc: 20, points: [{ v: 14, i: 0.5 }] })])
    expect(stats.voc?.n).toBe(1)
  })

  it('is all-null with no curves at all', () => {
    const stats = curveStepStats([])
    expect(stats.voc).toBeNull()
    expect(stats.pMpp).toBeNull()
  })
})

function samples(pairs: [number, number, number][]): RunSample[] {
  return pairs.map(([t, v, i]) => ({ t, v, i, d: 0.5 }))
}

describe('runMetrics', () => {
  it('is null for an empty run', () => {
    expect(runMetrics([], null)).toBeNull()
  })

  it('reports held power alone with no reference curve', () => {
    const m = runMetrics(samples([[0, 10, 0.5]]), null)!
    expect(m.heldPower).toBeCloseTo(5)
    expect(m.pOverMppTh).toBeNull()
    expect(m.timeToConvergeS).toBeNull()
  })

  it('computes P / MPP_th off the last sample', () => {
    const mppTh = { v: 14, i: 0.5 } // P_th = 7
    const m = runMetrics(samples([[0, 14, 0.5]]), mppTh)!
    expect(m.heldPower).toBeCloseTo(7)
    expect(m.pOverMppTh).toBeCloseTo(1)
  })

  it('finds the time to converge as the first sample after which power stays in band', () => {
    const mppTh = { v: 14, i: 1 } // P_th = 14, band = 0.95*14 = 13.3
    const trace = samples([
      [0, 5, 1], // P=5, outside
      [1, 10, 1], // P=10, outside
      [2, 14, 1], // P=14, inside - converged here
      [3, 14, 1], // stays inside
    ])
    const m = runMetrics(trace, mppTh)!
    expect(m.timeToConvergeS).toBe(2) // t=2 minus t0=0
  })

  it('is null when the run dips back out of band right before the end', () => {
    const mppTh = { v: 14, i: 1 }
    const trace = samples([
      [0, 14, 1],
      [1, 14, 1],
      [2, 5, 1], // drops out of band on the very last sample
    ])
    const m = runMetrics(trace, mppTh)!
    expect(m.timeToConvergeS).toBeNull()
  })

  it('is zero when the run starts inside the band', () => {
    const mppTh = { v: 14, i: 1 }
    const trace = samples([
      [5, 14, 1],
      [6, 14, 1],
    ])
    const m = runMetrics(trace, mppTh)!
    expect(m.timeToConvergeS).toBe(0)
  })
})

describe('runStepStats', () => {
  it('summarizes held power and P/MPP_th, and drops non-converged runs from time-to-converge', () => {
    const mppTh = { v: 14, i: 1 }
    const m1 = runMetrics(samples([[0, 14, 1]]), mppTh)!
    const m2 = runMetrics(samples([[0, 5, 1]]), null)! // no reference - pOverMppTh null
    const stats = runStepStats([m1, m2])
    expect(stats.heldPower?.n).toBe(2)
    expect(stats.pOverMppTh?.n).toBe(1) // only m1 has a ratio
    expect(stats.timeToConvergeS?.n).toBe(1)
  })

  it('is all-null with no runs at all', () => {
    const stats = runStepStats([])
    expect(stats.heldPower).toBeNull()
    expect(stats.pOverMppTh).toBeNull()
    expect(stats.timeToConvergeS).toBeNull()
  })
})
