// Typed client for scripts/curve_tracer_server.py's FastAPI routes. This
// is the one place the mA/A boundary is crossed: GET /api/data's points
// are milliamps (the UI's unit), while everything else (the curve
// library, /api/curves) stores amps - see CurvePoint's volts/amps
// convention in types.ts.

import type { CurvePoint, CurveRecord, PanelSetup } from '@/types'

interface WireDataPoint {
  x: number // volts
  y: number // milliamps
}

interface DataResponse {
  points: WireDataPoint[]
  partial: WireDataPoint[]
  active: boolean
  link: string
  seq: number
}

export interface LiveSweepState {
  points: CurvePoint[]
  partial: CurvePoint[]
  active: boolean
  link: string
  seq: number
}

function fromWirePoints(points: WireDataPoint[] | undefined): CurvePoint[] {
  return (points ?? []).map((p) => ({ v: p.x, i: p.y / 1000 }))
}

// FastAPI's own validation errors (a bad body on POST /api/save-curve, e.g.
// a panel missing "tilt_deg") send `detail` as a list of {loc, msg, type}
// objects, not a string - `HTTPException(detail=...)` elsewhere in the app
// still sends a plain string. Handle both rather than letting `String()`
// flatten the array case into "[object Object]".
function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join('; ')
  }
  return JSON.stringify(detail)
}

async function parseJsonOrThrow(r: Response, what: string): Promise<unknown> {
  const payload = await r.json().catch(() => null)
  if (!r.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? formatDetail((payload as { detail: unknown }).detail)
        : `HTTP ${r.status}`
    throw new Error(`${what}: ${detail}`)
  }
  return payload
}

export async function fetchLiveSweep(): Promise<LiveSweepState> {
  const r = await fetch('/api/data', { cache: 'no-store' })
  const payload = (await parseJsonOrThrow(r, 'GET /api/data')) as DataResponse
  return {
    points: fromWirePoints(payload.points),
    partial: fromWirePoints(payload.partial),
    active: Boolean(payload.active),
    link: payload.link ?? '--',
    seq: Number.isFinite(payload.seq) ? payload.seq : 0,
  }
}

export async function fetchCurves(): Promise<CurveRecord[]> {
  const r = await fetch('/api/curves')
  const payload = (await parseJsonOrThrow(r, 'GET /api/curves')) as (
    | CurveRecord
    | { path: string; error: string }
  )[]
  // A malformed on-disk file reports {path, error} instead of a full
  // record (see curve_tracer_server.py's get_curves) - not renderable as
  // a curve, so it's dropped here rather than pushed further into the UI.
  return payload.filter((entry): entry is CurveRecord => !('error' in entry))
}

export async function fetchMeasurementKinds(): Promise<string[]> {
  const r = await fetch('/api/measurement-kinds')
  return (await parseJsonOrThrow(r, 'GET /api/measurement-kinds')) as string[]
}

export interface SaveCurveInput {
  label: string
  measurement: string
  panels: PanelSetup[]
  notes: string
}

export async function saveCurve(input: SaveCurveInput): Promise<{ path: string }> {
  const r = await fetch('/api/save-curve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return (await parseJsonOrThrow(r, 'POST /api/save-curve')) as { path: string }
}

export async function startSweep(): Promise<void> {
  const r = await fetch('/api/start-sweep', { method: 'POST' })
  await parseJsonOrThrow(r, 'POST /api/start-sweep')
}

export async function releaseRelay(): Promise<void> {
  const r = await fetch('/api/release-relay', { method: 'POST' })
  await parseJsonOrThrow(r, 'POST /api/release-relay')
}
