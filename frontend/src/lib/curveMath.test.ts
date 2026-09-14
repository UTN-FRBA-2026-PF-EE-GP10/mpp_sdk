import { describe, expect, it } from 'vitest'
import { mppPoint } from './curveMath'

describe('mppPoint', () => {
  it('returns null for an empty sweep', () => {
    expect(mppPoint([])).toBeNull()
  })

  it('returns the point with the largest v*i product', () => {
    const points = [
      { v: 21.3, i: 0.006 }, // ~0.128 W
      { v: 18.0, i: 0.195 }, // 3.51 W
      { v: 8.0, i: 0.215 }, // 1.72 W
    ]
    expect(mppPoint(points)).toEqual({ v: 18.0, i: 0.195 })
  })
})
