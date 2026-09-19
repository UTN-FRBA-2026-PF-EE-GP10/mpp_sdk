// Statistics over a report step's repeats - Addendum (2026-09-19) of plan
// 042: "the report view computes the statistics in the browser, over the
// linked items of one step". Pure functions, no fetching - callers hand in
// curves/run samples already in hand, the same "already-loaded" contract
// ReportView itself follows.

import { mppPoint } from '@/lib/curveMath'
import type { RunSample } from '@/lib/runs'
import type { CurvePoint, CurveRecord } from '@/types'

export interface Stats {
  n: number
  median: number
  mean: number
  /** Sample standard deviation (n - 1 divisor). `null` at n = 1 - "show
   * the value alone, with no deviation" (Addendum). */
  std: number | null
  min: number
  max: number
}

/** `null` for an empty sample - a step with no found links has nothing to
 * summarize. */
export function computeStats(values: number[]): Stats | null {
  if (values.length === 0) return null
  const n = values.length
  const sorted = [...values].sort((a, b) => a - b)
  const mean = values.reduce((a, b) => a + b, 0) / n
  const mid = Math.floor(n / 2)
  const median = n % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
  let std: number | null = null
  if (n > 1) {
    const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / (n - 1)
    std = Math.sqrt(variance)
  }
  return { n, median, mean, std, min: sorted[0], max: sorted[n - 1] }
}

export interface CurveMetrics {
  voc: number
  isc: number
  vmp: number
  imp: number
  pMpp: number
}

/** Voc/Isc are the curve's own recorded extremes (see CurveRecord.voc/isc
 * - mirrors mpp_sdk/curves/record.py's open_circuit_voltage/
 * short_circuit_current, the measured extremes, not extrapolated ones).
 * Vmp/Imp/P_mpp come from the curve's own maximum-power point
 * (curveMath.mppPoint), recomputed from `points` rather than trusting
 * `record.p_mpp` alone, so a step statistic and a chart's MPP marker can
 * never disagree. `null` for a curve with no points. */
export function curveMetrics(record: Pick<CurveRecord, 'voc' | 'isc' | 'points'>): CurveMetrics | null {
  const mpp = mppPoint(record.points)
  if (mpp === null) return null
  return { voc: record.voc, isc: record.isc, vmp: mpp.v, imp: mpp.i, pMpp: mpp.v * mpp.i }
}

/** One metric's stats over every found curve linked to a step. `null`
 * entries (curves with no points) are dropped rather than propagated. */
export interface CurveStepStats {
  voc: Stats | null
  isc: Stats | null
  vmp: Stats | null
  imp: Stats | null
  pMpp: Stats | null
}

export function curveStepStats(records: CurveRecord[]): CurveStepStats {
  const metrics = records.map(curveMetrics).filter((m): m is CurveMetrics => m !== null)
  return {
    voc: computeStats(metrics.map((m) => m.voc)),
    isc: computeStats(metrics.map((m) => m.isc)),
    vmp: computeStats(metrics.map((m) => m.vmp)),
    imp: computeStats(metrics.map((m) => m.imp)),
    pMpp: computeStats(metrics.map((m) => m.pMpp)),
  }
}

export interface RunMetrics {
  /** Power at the end of the run (last sample's V*I) - what the
   * controller was actually holding when it stopped. */
  heldPower: number
  /** heldPower / P(MPP_th) - `null` with no reference curve to grade
   * against (mirrors RunReadouts's own ratio, at the run's last sample
   * instead of the playback cursor). */
  pOverMppTh: number | null
  /** Seconds (run-relative, like runPlayback.ts's runDuration) from the
   * start until power enters - and stays within - 5% of MPP_th, mirroring
   * mpp_sdk.metrics.settling_time's band. `null` with no reference, or if
   * the run never settles inside the band. */
  timeToConvergeS: number | null
}

const SETTLING_BAND = 0.05

/** `null` for an empty sample series. `mppTh` is the reference curve's
 * maximum-power point (curveMath.mppPoint over its points) - pass `null`
 * when the run has no reference curve (see runPlayback.findCurveForRun). */
export function runMetrics(samples: RunSample[], mppTh: CurvePoint | null): RunMetrics | null {
  if (samples.length === 0) return null
  const last = samples[samples.length - 1]
  const heldPower = last.v * last.i
  const pTh = mppTh ? mppTh.v * mppTh.i : 0
  if (!mppTh || pTh <= 0) {
    return { heldPower, pOverMppTh: null, timeToConvergeS: null }
  }
  const pOverMppTh = heldPower / pTh
  const t0 = samples[0].t
  const threshold = (1 - SETTLING_BAND) * pTh
  let lastOutsideIndex = -1
  for (let k = 0; k < samples.length; k++) {
    if (samples[k].v * samples[k].i < threshold) lastOutsideIndex = k
  }
  let timeToConvergeS: number | null
  if (lastOutsideIndex === -1) {
    timeToConvergeS = 0 // inside the band from the first sample
  } else if (lastOutsideIndex === samples.length - 1) {
    timeToConvergeS = null // still outside at the end - never settled
  } else {
    timeToConvergeS = samples[lastOutsideIndex + 1].t - t0
  }
  return { heldPower, pOverMppTh, timeToConvergeS }
}

export interface RunStepStats {
  heldPower: Stats | null
  pOverMppTh: Stats | null
  /** Only over runs that actually converged (a `null` per-run value is
   * dropped, same as a missing/unavailable run) - a mix of "converged in
   * 2s" and "never converged" has no sensible mean. */
  timeToConvergeS: Stats | null
}

export function runStepStats(metrics: RunMetrics[]): RunStepStats {
  return {
    heldPower: computeStats(metrics.map((m) => m.heldPower)),
    pOverMppTh: computeStats(
      metrics.map((m) => m.pOverMppTh).filter((v): v is number => v !== null),
    ),
    timeToConvergeS: computeStats(
      metrics.map((m) => m.timeToConvergeS).filter((v): v is number => v !== null),
    ),
  }
}
