// A session file bundles a session record (mpp_sdk.sessions.record.SessionRecord
// - see lib/sessions.ts) and every curve and run linked to it - or a set of
// curves/runs chosen by hand in select mode - into one JSON file, so someone
// else can open the workbench with no board and no saved library and still
// see the whole picture. Import replaces the data source the same way demo
// (sandbox) mode does (see lib/sandbox.ts): everything read-only, nothing
// fetched from or written to a server. See CurveCategoryPane.tsx/
// RunDatePane.tsx/sessionExport.ts for where a file is built, and
// ImportedSessionProvider.tsx for where an imported one is held.
//
// "Session" now names two different things in this codebase, so they are
// kept apart by name: a *session* (lib/sessions.ts's SessionRecord) is the
// bench-session record itself; a *session file* (this module) is the
// exported bundle - and the state that holds one open for read-only viewing
// is the *imported session* (ImportedSessionProvider/useImportedSession
// below), never plain "session".

import { createContext, useContext } from 'react'
import { useSandbox } from '@/lib/sandbox'
import type { OpenQuestion, SessionRecord, SessionStep } from '@/lib/sessions'
import type { RunDetail, RunSample } from '@/lib/runs'
import type { CurvePoint, CurveRecord, PanelSetup } from '@/types'

export const SESSION_FORMAT = 'mpp-sdk-session'
export const SESSION_SCHEMA = 1

/** Matches the Addendum's 50 MB limit - checked against `File.size` before
 * the file is even read, so an oversize drop fails fast instead of
 * stringifying tens of megabytes into memory first. */
export const MAX_SESSION_BYTES = 50 * 1024 * 1024

export interface SessionCurveEntry {
  id: string
  record: CurveRecord
}

export interface SessionRunEntry {
  id: string
  record: RunDetail
}

export interface SessionMissing {
  curve_ids: string[]
  run_ids: string[]
}

/** The `mpp-sdk-session` file format, schema 1. `session` is `null` for a
 * file built from a hand-picked set of curves/runs (select mode), rather
 * than exported from a bench session. */
export interface SessionFile {
  format: typeof SESSION_FORMAT
  schema: number
  exported_at: string
  title: string
  setup: string
  session: SessionRecord | null
  curves: SessionCurveEntry[]
  runs: SessionRunEntry[]
  missing: SessionMissing
}

/** Thrown by every parse/read function below, with a message meant to be
 * shown to the operator as-is - "a bad file gives a clear message". */
export class SessionParseError extends Error {}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new SessionParseError(`${field} must be a string`)
  }
  return value
}

function requireNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new SessionParseError(`${field} must be a number`)
  }
  return value
}

function requireBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') {
    throw new SessionParseError(`${field} must be a boolean`)
  }
  return value
}

function requireArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new SessionParseError(`${field} must be an array`)
  }
  return value
}

function requireStringRecord(value: unknown, field: string): Record<string, string> {
  if (!isPlainObject(value)) {
    throw new SessionParseError(`${field} must be an object`)
  }
  const result: Record<string, string> = {}
  for (const [key, v] of Object.entries(value)) result[key] = requireString(v, `${field}.${key}`)
  return result
}

function parsePanels(value: unknown, field: string): PanelSetup[] {
  return requireArray(value, field).map((p, i) => {
    if (!isPlainObject(p)) throw new SessionParseError(`${field}[${i}] must be an object`)
    return {
      id: requireString(p.id, `${field}[${i}].id`),
      tilt_deg: requireNumber(p.tilt_deg, `${field}[${i}].tilt_deg`),
    }
  })
}

function parseCurvePoints(value: unknown, field: string): CurvePoint[] {
  return requireArray(value, field).map((p, i) => {
    if (!isPlainObject(p)) throw new SessionParseError(`${field}[${i}] must be an object`)
    return {
      v: requireNumber(p.v, `${field}[${i}].v`),
      i: requireNumber(p.i, `${field}[${i}].i`),
    }
  })
}

function parseRunSamples(value: unknown, field: string): RunSample[] {
  return requireArray(value, field).map((s, i) => {
    if (!isPlainObject(s)) throw new SessionParseError(`${field}[${i}] must be an object`)
    return {
      t: requireNumber(s.t, `${field}[${i}].t`),
      v: requireNumber(s.v, `${field}[${i}].v`),
      i: requireNumber(s.i, `${field}[${i}].i`),
      d: requireNumber(s.d, `${field}[${i}].d`),
    }
  })
}

/** The file name without its directory. A record's `path` is the server's
 * absolute path, which would put a home directory and user name into a file
 * meant to be shared. Nothing reads the directory part (findCurveForRun
 * matches the base name only), so it is dropped when a file is built and
 * again when an older file that still has it is read. `fallback` stands in
 * when nothing follows the last separator, so the directory never survives. */
export function bareFileName(path: string, fallback: string): string {
  const name = path.split(/[\\/]/).pop() ?? ''
  return name === '' ? fallback : name
}

/** A run's notes hold its abort reason, and an `error: ...` reason is raw
 * exception text that can name a device node or a file under a home
 * directory. Only the last segment of each absolute path is kept. */
function scrubAbsolutePaths(text: string): string {
  return text.replace(/(?<![\w.:/-])\/(?:[^\s/'"()]+\/)+([^\s/'"()]*)/g, '$1')
}

export function withoutCurveDirectories(record: CurveRecord): CurveRecord {
  return { ...record, path: bareFileName(record.path, `${record.id}.json`) }
}

export function withoutRunDirectories(record: RunDetail): RunDetail {
  return {
    ...record,
    path: bareFileName(record.path, `${record.id}.json`),
    curve_ref: record.curve_ref === null ? null : bareFileName(record.curve_ref, ''),
    notes: scrubAbsolutePaths(record.notes),
  }
}

/** Validates a curve record the same shape GET /api/curves serves, so a
 * hand-edited or corrupted session file fails clearly instead of crashing
 * a chart or a metadata table deep in the app later. The live API path
 * (lib/api.ts) trusts the server's own JSON outright - this extra check
 * only exists here because a session file is not the server's own JSON,
 * it is whatever the operator was handed. */
export function parseSessionCurveRecord(raw: unknown, context: string): CurveRecord {
  if (!isPlainObject(raw)) {
    throw new SessionParseError(`${context}: curve record must be an object`)
  }
  return withoutCurveDirectories({
    id: requireString(raw.id, `${context}.id`),
    path: requireString(raw.path, `${context}.path`),
    captured_at: requireString(raw.captured_at, `${context}.captured_at`),
    label: requireString(raw.label, `${context}.label`),
    measurement: requireString(raw.measurement, `${context}.measurement`),
    panels: parsePanels(raw.panels, `${context}.panels`),
    notes: requireString(raw.notes, `${context}.notes`),
    n_points: requireNumber(raw.n_points, `${context}.n_points`),
    source: requireString(raw.source, `${context}.source`),
    voc: requireNumber(raw.voc, `${context}.voc`),
    isc: requireNumber(raw.isc, `${context}.isc`),
    p_mpp: requireNumber(raw.p_mpp, `${context}.p_mpp`),
    points: parseCurvePoints(raw.points, `${context}.points`),
  })
}

/** Same reasoning as parseSessionCurveRecord above, for GET /api/runs/{id}'s
 * shape - a session run always carries its full samples (the export side
 * always fetches with max_samples=0), so `downsampled` is expected false,
 * but a stray true is accepted rather than rejected: it says something
 * about how the file was produced, not something that makes it unusable. */
export function parseSessionRunDetail(raw: unknown, context: string): RunDetail {
  if (!isPlainObject(raw)) {
    throw new SessionParseError(`${context}: run record must be an object`)
  }
  const samples = parseRunSamples(raw.samples, `${context}.samples`)
  // Files exported before the run detail carried `duration_s` lack it, so
  // an absent value is derived from the samples, while a present one must
  // still be a number.
  const duration_s =
    raw.duration_s === undefined
      ? samples.length >= 2
        ? samples[samples.length - 1].t - samples[0].t
        : 0
      : requireNumber(raw.duration_s, `${context}.duration_s`)
  return withoutRunDirectories({
    id: requireString(raw.id, `${context}.id`),
    path: requireString(raw.path, `${context}.path`),
    captured_at: requireString(raw.captured_at, `${context}.captured_at`),
    label: requireString(raw.label, `${context}.label`),
    algorithm: requireString(raw.algorithm, `${context}.algorithm`),
    n_samples: requireNumber(raw.n_samples, `${context}.n_samples`),
    duration_s,
    aborted: requireBoolean(raw.aborted, `${context}.aborted`),
    curve_ref: raw.curve_ref === null ? null : requireString(raw.curve_ref, `${context}.curve_ref`),
    notes: requireString(raw.notes, `${context}.notes`),
    source: requireString(raw.source, `${context}.source`),
    downsampled: requireBoolean(raw.downsampled, `${context}.downsampled`),
    samples,
  })
}

function parseOpenQuestion(raw: unknown, context: string): OpenQuestion {
  if (!isPlainObject(raw)) throw new SessionParseError(`${context} must be an object`)
  return {
    id: requireString(raw.id, `${context}.id`),
    text: requireString(raw.text, `${context}.text`),
    answer: requireString(raw.answer, `${context}.answer`),
  }
}

function parseSessionStep(raw: unknown, context: string): SessionStep {
  if (!isPlainObject(raw)) throw new SessionParseError(`${context} must be an object`)
  const value = raw.value
  if (value !== null && typeof value !== 'number' && typeof value !== 'string') {
    throw new SessionParseError(`${context}.value must be a number, a string, or null`)
  }
  const unit = raw.unit
  if (unit !== null && typeof unit !== 'string') {
    throw new SessionParseError(`${context}.unit must be a string or null`)
  }
  return {
    id: requireString(raw.id, `${context}.id`),
    section: requireString(raw.section, `${context}.section`),
    title: requireString(raw.title, `${context}.title`),
    instructions: requireString(raw.instructions, `${context}.instructions`),
    kind: requireString(raw.kind, `${context}.kind`),
    status: requireString(raw.status, `${context}.status`),
    value,
    unit,
    notes: requireString(raw.notes, `${context}.notes`),
    curve_ids: requireArray(raw.curve_ids, `${context}.curve_ids`).map((v, i) =>
      requireString(v, `${context}.curve_ids[${i}]`),
    ),
    run_ids: requireArray(raw.run_ids, `${context}.run_ids`).map((v, i) =>
      requireString(v, `${context}.run_ids[${i}]`),
    ),
    repeats: requireNumber(raw.repeats, `${context}.repeats`),
  }
}

/** Validates a session record the same shape GET /api/sessions/{id} serves -
 * same reasoning as parseSessionCurveRecord/parseSessionRunDetail above: a
 * session file is whatever the operator was handed, not the server's own
 * trusted JSON. */
export function parseSessionRecord(raw: unknown, context = 'session'): SessionRecord {
  if (!isPlainObject(raw)) {
    throw new SessionParseError(`${context} must be an object`)
  }
  return {
    id: requireString(raw.id, `${context}.id`),
    title: requireString(raw.title, `${context}.title`),
    template_id: requireString(raw.template_id, `${context}.template_id`),
    template_version: requireNumber(raw.template_version, `${context}.template_version`),
    setup: requireString(raw.setup, `${context}.setup`),
    created_at: requireString(raw.created_at, `${context}.created_at`),
    updated_at: requireString(raw.updated_at, `${context}.updated_at`),
    fields: requireStringRecord(raw.fields, `${context}.fields`),
    steps: requireArray(raw.steps, `${context}.steps`).map((s, i) =>
      parseSessionStep(s, `${context}.steps[${i}]`),
    ),
    open_questions: requireArray(raw.open_questions, `${context}.open_questions`).map((q, i) =>
      parseOpenQuestion(q, `${context}.open_questions[${i}]`),
    ),
  }
}

function parseMissing(value: unknown): SessionMissing {
  if (value === undefined) return { curve_ids: [], run_ids: [] }
  if (!isPlainObject(value)) throw new SessionParseError('missing must be an object')
  const curveIds = value.curve_ids === undefined ? [] : requireArray(value.curve_ids, 'missing.curve_ids')
  const runIds = value.run_ids === undefined ? [] : requireArray(value.run_ids, 'missing.run_ids')
  return {
    curve_ids: curveIds.map((v, i) => requireString(v, `missing.curve_ids[${i}]`)),
    run_ids: runIds.map((v, i) => requireString(v, `missing.run_ids[${i}]`)),
  }
}

/** Checks `format`/`schema` first, before parsing a single record - a file
 * that is simply not a session file (the wrong format, or a schema this
 * workbench doesn't know) should say so plainly, not fail on whatever
 * record happens to be first. */
export function parseSessionFile(raw: unknown): SessionFile {
  if (!isPlainObject(raw)) {
    throw new SessionParseError('Not a session file - expected a JSON object')
  }
  if (raw.format !== SESSION_FORMAT) {
    throw new SessionParseError(
      `Not a session file - expected "format": "${SESSION_FORMAT}", got ${JSON.stringify(raw.format)}`,
    )
  }
  if (raw.schema !== SESSION_SCHEMA) {
    throw new SessionParseError(
      `Unsupported session schema ${JSON.stringify(raw.schema)} - this workbench reads schema ${SESSION_SCHEMA}`,
    )
  }

  const title = requireString(raw.title, 'title')
  const setup = requireString(raw.setup, 'setup')
  const exportedAt = requireString(raw.exported_at, 'exported_at')

  const curveEntries = requireArray(raw.curves, 'curves').map((entry, i) => {
    if (!isPlainObject(entry)) throw new SessionParseError(`curves[${i}] must be an object`)
    const id = requireString(entry.id, `curves[${i}].id`)
    return { id, record: parseSessionCurveRecord(entry.record, `curves[${i}] ("${id}")`) }
  })

  const runEntries = requireArray(raw.runs, 'runs').map((entry, i) => {
    if (!isPlainObject(entry)) throw new SessionParseError(`runs[${i}] must be an object`)
    const id = requireString(entry.id, `runs[${i}].id`)
    return { id, record: parseSessionRunDetail(entry.record, `runs[${i}] ("${id}")`) }
  })

  const session =
    raw.session === undefined || raw.session === null ? null : parseSessionRecord(raw.session, 'session')

  return {
    format: SESSION_FORMAT,
    schema: SESSION_SCHEMA,
    exported_at: exportedAt,
    title,
    setup,
    session,
    curves: curveEntries,
    runs: runEntries,
    missing: parseMissing(raw.missing),
  }
}

/** Reads and validates a dropped/opened file, in that order: size first (no
 * point reading 200 MB just to reject it), then JSON syntax, then the
 * format/schema/record checks above. */
export async function readSessionFile(file: File): Promise<SessionFile> {
  if (file.size > MAX_SESSION_BYTES) {
    const mb = (file.size / (1024 * 1024)).toFixed(1)
    throw new SessionParseError(`Session file is too large (${mb} MB) - the limit is 50 MB`)
  }
  const text = await file.text()
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new SessionParseError('Not a valid JSON file')
  }
  return parseSessionFile(parsed)
}

/** Builds a session file from records already in hand - curves are always
 * full records by the time they reach this app (GET /api/curves serves
 * points inline), and runs are expected to already carry every sample
 * (max_samples=0), so nothing here re-fetches or truncates anything.
 * `missing` names curve/run ids a session's steps linked that could not be
 * found (see sessionExport.ts's sessionExportFile, which fills it in);
 * select mode's loose export (CurveCategoryPane/RunDatePane) never has
 * missing ids of its own, so it is left at its default, empty value. */
export function buildSessionFile(options: {
  title: string
  setup: string
  curves: CurveRecord[]
  runs: RunDetail[]
  session?: SessionRecord | null
  missing?: SessionMissing
}): SessionFile {
  return {
    format: SESSION_FORMAT,
    schema: SESSION_SCHEMA,
    exported_at: new Date().toISOString(),
    title: options.title,
    setup: options.setup,
    session: options.session ?? null,
    curves: options.curves.map((record) => ({ id: record.id, record: withoutCurveDirectories(record) })),
    runs: options.runs.map((record) => ({ id: record.id, record: withoutRunDirectories(record) })),
    missing: options.missing ?? { curve_ids: [], run_ids: [] },
  }
}

/** `<title>.mppsession.json`, with filesystem-illegal characters swapped
 * for a hyphen - unlike curveExport.ts's sanitizeFilenamePart, the title's
 * spacing and casing are kept, since it is meant to be read back by a
 * person, not matched against anything. */
export function sessionFileName(title: string): string {
  const cleaned = title.trim().replace(/[/\\?%*:|"<>]/g, '-')
  return `${cleaned || 'session'}.mppsession.json`
}

/** Same Blob-object-URL download as curveExport.ts's downloadCurve - no
 * server involvement, so no download endpoint to add. */
export function downloadSessionFile(file: SessionFile): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = sessionFileName(file.title)
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** The state of the session file currently open for read-only viewing, if
 * any - kept apart from `SessionRecord`/`SessionFile` above by name
 * ("imported session") since all three now share the word "session". */
export interface ImportedSessionValue {
  /** True once a session file has been imported - view mode. */
  active: boolean
  title: string | null
  setup: string | null
  session: SessionRecord | null
  curves: CurveRecord[]
  runs: RunDetail[]
  missing: SessionMissing
  enter: (file: SessionFile) => void
  close: () => void
}

// Fails safe the same way CaptureModeContext does (lib/captureMode.ts): a
// component rendered without ImportedSessionProvider (most tests) gets "no
// imported session active" rather than a throw.
const DEFAULT_IMPORTED_SESSION_VALUE: ImportedSessionValue = {
  active: false,
  title: null,
  setup: null,
  session: null,
  curves: [],
  runs: [],
  missing: { curve_ids: [], run_ids: [] },
  enter: () => {},
  close: () => {},
}

export const ImportedSessionContext = createContext<ImportedSessionValue>(
  DEFAULT_IMPORTED_SESSION_VALUE,
)

export function useImportedSession(): ImportedSessionValue {
  return useContext(ImportedSessionContext)
}

export type ReadOnlyReason = 'demo' | 'view'

export interface ReadOnlyValue {
  enabled: boolean
  reason: ReadOnlyReason | null
}

/** The one place "is this control allowed to write" is decided, folding
 * together demo (sandbox) mode and an imported session's view mode - both
 * mean the same thing to a delete/remeasure/batch-delete button, and the
 * Addendum asks view mode to work "the same way demo (sandbox) mode does".
 * `reason` is kept apart from `enabled` only so a tooltip can say which of
 * the two is actually active, rather than always blaming demo mode. */
export function useReadOnly(): ReadOnlyValue {
  const sandbox = useSandbox()
  const importedSession = useImportedSession()
  if (importedSession.active) return { enabled: true, reason: 'view' }
  if (sandbox.enabled) return { enabled: true, reason: 'demo' }
  return { enabled: false, reason: null }
}

/** Picks the tooltip/explanation text for a control useReadOnly disabled -
 * one place so "unavailable while viewing an imported session" and
 * "unavailable in demo mode" can't drift apart between components. */
export function readOnlyReasonText(reason: ReadOnlyReason, action: string): string {
  return reason === 'view'
    ? `${action} is unavailable while viewing an imported session`
    : `${action} is unavailable in demo mode`
}
