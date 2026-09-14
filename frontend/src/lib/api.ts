// Typed client for scripts/curve_tracer_server.py's FastAPI routes. This
// is the one place the mA/A boundary is crossed: GET /api/data's points
// are milliamps (the UI's unit). Everything else (the curve library,
// /api/curves, and the run library, /api/runs) stores volts and amps -
// see CurvePoint's convention in types.ts and RunSample's in runs.ts.

import type { RunDetail, RunSummary } from '@/lib/runs'
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
  command_error: string | null
  demo_source: boolean
}

export interface LiveSweepState {
  points: CurvePoint[]
  partial: CurvePoint[]
  active: boolean
  link: string
  seq: number
  // Set when the last Start Measurement/Release Relay click failed -
  // null otherwise.
  commandError: string | null
  // True when the curve on screen was replayed from the firmware's
  // stored curves rather than measured off a panel.
  demoSource: boolean
}

function fromWirePoints(points: WireDataPoint[] | undefined): CurvePoint[] {
  return (points ?? []).map((p) => ({ v: p.x, i: p.y / 1000 }))
}

// FastAPI's own validation errors (a bad body on POST /api/save-curve,
// e.g. a panel missing "tilt_deg") send `detail` as a list of
// {loc, msg, type} objects, not a string. `HTTPException(detail=...)`
// elsewhere in the app still sends a plain string. Handle both, so
// `String()` doesn't flatten the array case into "[object Object]".
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
    commandError: payload.command_error ?? null,
    demoSource: Boolean(payload.demo_source),
  }
}

export async function fetchCurves(): Promise<CurveRecord[]> {
  const r = await fetch('/api/curves')
  const payload = (await parseJsonOrThrow(r, 'GET /api/curves')) as (
    | CurveRecord
    | { id: string; path: string; error: string }
  )[]
  // A malformed on-disk file reports {id, path, error} instead of a full
  // record (see curve_tracer_server.py's get_curves) - not renderable as
  // a curve, so it's dropped here rather than pushed further into the UI.
  return payload.filter((entry): entry is CurveRecord => !('error' in entry))
}

export async function deleteCurve(id: string): Promise<void> {
  const r = await fetch(`/api/curves/${encodeURIComponent(id)}`, { method: 'DELETE' })
  await parseJsonOrThrow(r, 'DELETE /api/curves/{id}')
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

export async function startDemoSweep(bright: boolean): Promise<void> {
  const r = await fetch(`/api/start-demo-sweep?bright=${bright}`, { method: 'POST' })
  await parseJsonOrThrow(r, 'POST /api/start-demo-sweep')
}

export async function releaseRelay(): Promise<void> {
  const r = await fetch('/api/release-relay', { method: 'POST' })
  await parseJsonOrThrow(r, 'POST /api/release-relay')
}

export async function fetchRuns(): Promise<RunSummary[]> {
  const r = await fetch('/api/runs')
  const payload = (await parseJsonOrThrow(r, 'GET /api/runs')) as (
    | RunSummary
    | { id: string; path: string; error: string }
  )[]
  // A malformed on-disk file reports {id, path, error} instead of a full
  // summary (see curve_tracer_server.py's get_runs - same pattern as
  // fetchCurves above), so it's dropped here rather than pushed further
  // into the UI.
  return payload.filter((entry): entry is RunSummary => !('error' in entry))
}

// `maxSamples` caps how many samples come back - omit it to take the
// server's default (a player-sized cap), pass 0 for the full series
// (export/analysis). Either way the samples themselves are volts and
// amps, matching the run library's on-disk convention and CurveRecord's
// - GET /api/data's milliamps convention is that route's own and does not
// apply here.
export async function fetchRun(id: string, maxSamples?: number): Promise<RunDetail> {
  const query = maxSamples === undefined ? '' : `?max_samples=${maxSamples}`
  const r = await fetch(`/api/runs/${encodeURIComponent(id)}${query}`)
  return (await parseJsonOrThrow(r, 'GET /api/runs/{id}')) as RunDetail
}

export async function deleteRun(id: string): Promise<void> {
  const r = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })
  await parseJsonOrThrow(r, 'DELETE /api/runs/{id}')
}
