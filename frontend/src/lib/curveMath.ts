import type { CurvePoint } from '@/types'

/** The point of maximum power in a sweep - the largest v*i product among
 * the measured points, mirroring `CurveRecord.mpp()` in
 * mpp_sdk/curves/record.py (a measured extreme, not a fitted one). `null`
 * for an empty sweep, which a malformed or in-progress record can be. */
export function mppPoint(points: CurvePoint[]): CurvePoint | null {
  if (points.length === 0) return null
  return points.reduce((best, p) => (p.v * p.i > best.v * best.i ? p : best))
}
