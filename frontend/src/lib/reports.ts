// Shapes for measurement reports, mirroring mpp_sdk/reports/record.py and
// mpp_sdk/reports/templates.py, and the GET/POST/PATCH /api/report* routes
// in scripts/curve_tracer_server.py. Same split as lib/runs.ts: wire types
// and pure helpers live here, api.ts is the one place that crosses the wire.

export const STEP_KINDS = ['check', 'number', 'text', 'curve', 'run'] as const
export type StepKind = (typeof STEP_KINDS)[number]

export const STEP_STATUSES = ['todo', 'done', 'failed', 'skipped'] as const
export type StepStatus = (typeof STEP_STATUSES)[number]

export interface ReportStep {
  id: string
  section: string
  title: string
  instructions: string
  kind: StepKind | (string & {})
  status: StepStatus | (string & {})
  value: number | string | null
  unit: string | null
  notes: string
  curve_ids: string[]
  run_ids: string[]
  /** How many curves/runs this step asks for - only curve/run steps may
   * be above 1. Set by the template; PATCH cannot change it (see
   * mpp_sdk/reports/record.py's ReportStep docstring). */
  repeats: number
}

export interface OpenQuestion {
  id: string
  text: string
  answer: string
}

export interface ReportRecord {
  id: string
  title: string
  template_id: string
  template_version: number
  setup: string
  created_at: string
  updated_at: string
  fields: Record<string, string>
  steps: ReportStep[]
  open_questions: OpenQuestion[]
}

/** GET /api/reports's entry shape - summary only, no steps. */
export interface ReportSummary {
  id: string
  title: string
  template_id: string
  setup: string
  created_at: string
  updated_at: string
  n_steps: number
  n_done: number
  n_failed: number
}

/** GET /api/report-templates's entry shape. */
export interface ReportTemplateSummary {
  template_id: string
  version: number
  title: string
  setup: string
  n_steps: number
}

export interface TemplateFieldDef {
  key: string
  label: string
  hint: string
  default: string
}

export interface TemplateStep {
  id: string
  section: string
  title: string
  instructions: string
  kind: StepKind | (string & {})
  unit: string | null
  repeats: number
}

export interface TemplateQuestion {
  id: string
  text: string
}

/** GET /api/report-templates/{id}'s shape - a report without values. */
export interface ReportTemplate {
  template_id: string
  version: number
  title: string
  setup: string
  field_defs: TemplateFieldDef[]
  steps: TemplateStep[]
  open_questions: TemplateQuestion[]
}

// --- PATCH payload shapes - exactly PATCH /api/reports/{id}'s body -------

export interface ReportStepPatch {
  id: string
  status?: string
  value?: number | string
  notes?: string
  curve_ids?: string[]
  run_ids?: string[]
}

export interface OpenQuestionPatch {
  id: string
  answer: string
}

export interface ReportPatch {
  title?: string
  fields?: Record<string, string>
  steps?: ReportStepPatch[]
  open_questions?: OpenQuestionPatch[]
}

/** Combines two patches into one, later fields winning - used to batch
 * edits that land inside the same debounce window (see
 * hooks/useDebouncedPatch.ts) into a single PATCH request instead of
 * racing several. `fields` merges key by key; `steps`/`open_questions`
 * merge by `id`, so an edit to one step's notes and another step's status
 * in the same window both survive in the combined request. */
export function mergeReportPatch(a: ReportPatch, b: ReportPatch): ReportPatch {
  const merged: ReportPatch = { ...a }
  if (b.title !== undefined) merged.title = b.title
  if (b.fields) merged.fields = { ...(a.fields ?? {}), ...b.fields }
  if (b.steps) {
    const byId = new Map((a.steps ?? []).map((s) => [s.id, s]))
    for (const s of b.steps) {
      const existing = byId.get(s.id) ?? { id: s.id }
      byId.set(s.id, { ...existing, ...s })
    }
    merged.steps = Array.from(byId.values())
  }
  if (b.open_questions) {
    const byId = new Map((a.open_questions ?? []).map((q) => [q.id, q]))
    for (const q of b.open_questions) byId.set(q.id, q)
    merged.open_questions = Array.from(byId.values())
  }
  return merged
}

export function isEmptyPatch(patch: ReportPatch): boolean {
  return (
    patch.title === undefined &&
    !patch.fields &&
    !patch.steps &&
    !patch.open_questions
  )
}

export interface ReportSection {
  section: string
  steps: ReportStep[]
}

/**
 * Groups steps by their `section`, preserving each section's and each
 * step's first-seen order - the order `mpp_sdk.reports.library.create`
 * wrote them in (template order), not alphabetical. A PATCH never
 * reorders or adds/removes steps, so this is safe to recompute on every
 * render rather than cached.
 */
export function groupStepsBySection(steps: ReportStep[]): ReportSection[] {
  const order: string[] = []
  const bySection = new Map<string, ReportStep[]>()
  for (const step of steps) {
    if (!bySection.has(step.section)) {
      bySection.set(step.section, [])
      order.push(step.section)
    }
    bySection.get(step.section)?.push(step)
  }
  return order.map((section) => ({ section, steps: bySection.get(section) ?? [] }))
}

/** "12 / 20" - the progress count shown in the sidebar and the report
 * header. Shared so the two never disagree on what counts as "done". */
export function progressLabel(report: Pick<ReportSummary, 'n_done' | 'n_steps'>): string {
  return `${report.n_done} / ${report.n_steps}`
}

/** A template/field key like "light_source" read as "Light source" - used
 * as a fallback label for the setup-fields table, which otherwise has no
 * access to the template's own field labels (see ReportView's doc comment
 * on why it never fetches the template). */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}
