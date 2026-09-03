import type { CurvePoint, CurveRecord, MeasurementKind } from '@/types'

/**
 * A plausible single-diode-shaped I-V sweep, not a real measurement.
 * Used only until this UI is wired to the real Pi endpoints.
 */
export function generateMockPoints(
  voc: number,
  isc: number,
  points = 20,
  noise = 0.004,
): CurvePoint[] {
  const knee = 0.82 // fraction of Voc where the knee sits
  const out: CurvePoint[] = []
  for (let idx = 0; idx < points; idx++) {
    const v = voc * (1 - idx / Math.max(points - 1, 1))
    const shape = 1 / (1 + Math.exp((v / voc - knee) * 18))
    const jitter = (Math.random() - 0.5) * noise * isc
    const i = Math.max(0, isc * shape + jitter)
    out.push({ v: Number(v.toFixed(4)), i: Number(i.toFixed(5)) })
  }
  return out
}

function mpp(points: CurvePoint[]): number {
  return Math.max(...points.map((p) => p.v * p.i))
}

function record(
  path: string,
  label: string,
  measurement: MeasurementKind,
  panels: CurveRecord['panels'],
  voc: number,
  isc: number,
  hoursAgo: number,
  notes = '',
): CurveRecord {
  const points = generateMockPoints(voc, isc)
  const capturedAt = new Date(Date.now() - hoursAgo * 3_600_000).toISOString()
  return {
    path,
    captured_at: capturedAt,
    label,
    measurement,
    panels,
    notes,
    points,
    voc: Math.max(...points.map((p) => p.v)),
    isc: Math.max(...points.map((p) => p.i)),
    p_mpp: mpp(points),
  }
}

/** Stand-in for `GET /curves` until the frontend talks to a real backend. */
export const MOCK_LIBRARY: CurveRecord[] = [
  record(
    'mock/baseline-1.json',
    'both panels flat, midday sun',
    'baseline',
    [
      { id: 'A', tilt_deg: 0 },
      { id: 'B', tilt_deg: 0 },
    ],
    21.4,
    0.21,
    2,
  ),
  record(
    'mock/baseline-2.json',
    'both panels flat, lamp at 30cm',
    'baseline',
    [
      { id: 'A', tilt_deg: 0 },
      { id: 'B', tilt_deg: 0 },
    ],
    21.1,
    0.198,
    26,
  ),
  record(
    'mock/partial-shade-1.json',
    'panel B tilted 45deg',
    'partial-shade',
    [
      { id: 'A', tilt_deg: 0 },
      { id: 'B', tilt_deg: 45 },
    ],
    20.6,
    0.14,
    5,
    'B partially self-shaded by mount bracket at this angle',
  ),
  record(
    'mock/tilt-sweep-1.json',
    'panel B at 15deg',
    'tilt-sweep',
    [
      { id: 'A', tilt_deg: 0 },
      { id: 'B', tilt_deg: 15 },
    ],
    21.2,
    0.19,
    8,
  ),
  record(
    'mock/tilt-sweep-2.json',
    'panel B at 30deg',
    'tilt-sweep',
    [
      { id: 'A', tilt_deg: 0 },
      { id: 'B', tilt_deg: 30 },
    ],
    20.9,
    0.165,
    7.5,
  ),
]
