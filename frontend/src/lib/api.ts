// Typed client for scripts/curve_tracer_server.py's FastAPI routes. This
// is the one place the mA/A boundary is crossed: GET /api/data's points
// are milliamps (the UI's unit). Everything else (the curve library,
// /api/curves, and the run library, /api/runs) stores volts and amps -
// see CurvePoint's convention in types.ts and RunSample's in runs.ts.

import type { LiveRunState, RunDetail, RunSummary } from '@/lib/runs'
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

// The registered algorithm labels POST /api/runs/start accepts - see
// curve_tracer_server.py's get_algorithms for why this route exists
// (drawn from harness.common.algorithm_specs(), not a hardcoded list that
// could drift from it).
export interface RunConfig {
  algorithms: string[]
  /** Seconds. A run with no duration, or a longer one, is clamped to this. */
  maxDurationS: number
  /** Seconds. What a run lasts unless the operator changes it. */
  defaultDurationS: number
  /** The duty the algorithm is seeded with. Decides which maximum a local
   * tracker hill-climbs to, so it is offered rather than fixed. */
  defaultInitialDuty: number
  /** Volts and amps. The bounds a run is held to unless narrowed. */
  defaultVMax: number
  defaultIMax: number
}

/** The algorithm roster and the bounds the server enforces. Served rather
 * than hardcoded because these are the numbers a run is actually held to -
 * a page showing different ones would be worse than showing none. */
export async function fetchRunConfig(): Promise<RunConfig> {
  const r = await fetch('/api/run-config')
  const payload = (await parseJsonOrThrow(r, 'GET /api/run-config')) as {
    algorithms: string[]
    max_duration_s: number
    default_duration_s: number
    default_initial_duty: number
    default_v_max: number
    default_i_max: number
  }
  return {
    algorithms: payload.algorithms ?? [],
    maxDurationS: payload.max_duration_s,
    defaultDurationS: payload.default_duration_s,
    defaultInitialDuty: payload.default_initial_duty,
    defaultVMax: payload.default_v_max,
    defaultIMax: payload.default_i_max,
  }
}

// Volts and amps, like GET/POST .../runs above - unlike GET /api/data's
// milliamps (see this file's header note).
export interface StartRunInput {
  algorithm: string
  /** Omitted (or over the server's backstop) is clamped there, not
   * rejected - see curve_tracer_server.py's _MAX_RUN_DURATION_S. */
  duration_s?: number
  /** Seeds the algorithm. Rejected outside (0, 1) rather than clamped,
   * because moving it silently would change which maximum a local
   * tracker converges on. */
  initial_duty?: number
  v_max?: number
  i_max?: number
  curve_ref?: string | null
  label?: string
  /** Drive a SimulatedSource instead of the real board - see
   * curve_tracer_server.py's post_start_run. Omitted (or false) keeps the
   * existing hardware behavior; RunPane sets this rather than leaving it
   * to the caller, so a forgotten flag can never silently drive the
   * converter when a simulated run was intended, or vice versa. */
  simulated?: boolean
}

export interface StartRunResult {
  status: string
  algorithm: string
  label: string
  /** The duration the server actually committed to, after clamping -
   * always the number to show once a run is live, not whatever the
   * operator typed. */
  duration_s: number
}

export async function startRun(input: StartRunInput): Promise<StartRunResult> {
  const r = await fetch('/api/runs/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return (await parseJsonOrThrow(r, 'POST /api/runs/start')) as StartRunResult
}

export async function stopRun(): Promise<void> {
  const r = await fetch('/api/runs/stop', { method: 'POST' })
  await parseJsonOrThrow(r, 'POST /api/runs/stop')
}

// `maxSamples` caps the live window the same way fetchRun's does - see
// its own doc comment. Uncached like fetchLiveSweep: this is polled for a
// run's whole duration and must never serve a stale operating point.
export async function fetchLiveRun(maxSamples?: number): Promise<LiveRunState> {
  const query = maxSamples === undefined ? '' : `?max_samples=${maxSamples}`
  const r = await fetch(`/api/runs/live${query}`, { cache: 'no-store' })
  return (await parseJsonOrThrow(r, 'GET /api/runs/live')) as LiveRunState
}
