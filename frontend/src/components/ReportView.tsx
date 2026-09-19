import { useMemo, useState } from 'react'
import { CurveChart } from '@/components/CurveChart'
import { CurveDetailDialog } from '@/components/CurveDetailDialog'
import { RunPlayerDialog } from '@/components/RunPlayerDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDebouncedPatch } from '@/hooks/useDebouncedPatch'
import { formatCapturedAt } from '@/lib/format'
import { downloadReportJson, downloadReportMarkdown } from '@/lib/reportExport'
import {
  curveMetrics,
  curveStepStats,
  runMetrics,
  runStepStats,
  type Stats,
} from '@/lib/reportStats'
import {
  groupStepsBySection,
  humanizeKey,
  progressLabel,
  STEP_STATUSES,
  type ReportPatch,
  type ReportRecord,
  type ReportStep,
  type ReportStepPatch,
  type StepStatus,
} from '@/lib/reports'
import { findCurveForRun } from '@/lib/runPlayback'
import { useUnits } from '@/lib/units'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/**
 * The main pane for one measurement report - a readable document from
 * header to open questions. Takes the report plus every curve/run it might
 * need to render already loaded, and makes no fetch of its own (not even
 * for the template - see `humanizeKey`'s use as a field-label fallback):
 * a future session-file view mode (plan 042 Part D) renders this straight
 * from an imported file, with no server at all, by supplying the same
 * props from the file's own bundled records instead of a live fetch.
 *
 * Mutations go out through `onPatch` (debounced here - see
 * hooks/useDebouncedPatch.ts) and `onDeleteReport`, never called directly
 * against the API: the container (ReportPane) owns the network, this
 * component owns the document.
 */
export interface ReportViewProps {
  report: ReportRecord
  curves: CurveRecord[]
  runs: RunSummary[]
  /** Full run detail (with samples), keyed by run id - needed to compute
   * a run step's held power / P-over-MPP_th / time-to-converge. An id
   * with no entry here renders its per-run numbers as "-" rather than
   * blocking the rest of the step; the container fills this in
   * progressively (see ReportPane) or, for an imported session file,
   * supplies it all up front with no fetch at all. */
  runDetails?: Record<string, RunDetail>
  readOnly: boolean
  onPatch?: (patch: ReportPatch) => Promise<ReportRecord>
  onDeleteReport?: () => Promise<void>
  /** Fires after a run is deleted from the embedded run player - lets the
   * container refresh its own curve/run lists. Never fires in read-only
   * mode (RunPlayerDialog's own delete button is disabled there). */
  onLibraryChanged?: () => void
}

function SaveIndicator({ state, error }: { state: string; error: string | null }) {
  if (state === 'idle') return null
  if (state === 'saving') return <span className="text-xs text-muted-foreground">Saving...</span>
  if (state === 'error') {
    return <span className="text-xs text-destructive">Failed to save{error ? `: ${error}` : ''}</span>
  }
  return <span className="text-xs text-muted-foreground">Saved</span>
}

export function ReportView({
  report,
  curves,
  runs,
  runDetails = {},
  readOnly,
  onPatch,
  onDeleteReport,
  onLibraryChanged,
}: ReportViewProps) {
  const { schedule, sendNow, state, error } = useDebouncedPatch(readOnly ? undefined : onPatch)
  const [openCurve, setOpenCurve] = useState<CurveRecord | null>(null)
  const [openRun, setOpenRun] = useState<RunSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const sections = useMemo(() => groupStepsBySection(report.steps), [report.steps])
  const mostRecentCurve = useMemo(
    () =>
      curves.length === 0
        ? null
        : [...curves].sort((a, b) => b.captured_at.localeCompare(a.captured_at))[0],
    [curves],
  )
  const mostRecentRun = useMemo(
    () =>
      runs.length === 0 ? null : [...runs].sort((a, b) => b.captured_at.localeCompare(a.captured_at))[0],
    [runs],
  )

  function patchStep(id: string, changes: Omit<ReportStepPatch, 'id'>) {
    sendNow({ steps: [{ id, ...changes }] })
  }

  async function handleDelete() {
    if (!onDeleteReport) return
    if (!window.confirm(`Delete report "${report.title}"? This cannot be undone.`)) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDeleteReport()
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 print:gap-3">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle className="text-xl">{report.title}</CardTitle>
              <p className="text-sm text-muted-foreground">
                {report.template_id} - setup: {report.setup}
              </p>
            </div>
            <div className="flex items-center gap-2 print:hidden">
              {readOnly && <Badge variant="secondary">Read-only</Badge>}
              {!readOnly && <SaveIndicator state={state} error={error} />}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Created {formatCapturedAt(report.created_at)} - updated{' '}
            {formatCapturedAt(report.updated_at)}
          </p>
          <ProgressBar report={report} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FieldsTable
            key={report.id}
            fields={report.fields}
            readOnly={readOnly}
            onChange={(key, value) => schedule({ fields: { [key]: value } })}
          />
          <div className="flex flex-wrap gap-2 print:hidden">
            <Button variant="outline" size="sm" onClick={() => downloadReportJson(report)}>
              Download JSON
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadReportMarkdown(report, curves, runs, runDetails)}
            >
              Download Markdown
            </Button>
            {onDeleteReport && (
              <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting...' : 'Delete report'}
              </Button>
            )}
          </div>
          {deleteError && <p className="text-sm text-destructive">Failed to delete: {deleteError}</p>}
        </CardContent>
      </Card>

      {sections.map((group) => (
        <Card key={group.section}>
          <CardHeader>
            <CardTitle>{group.section}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {group.steps.map((step) => (
              <StepCard
                key={step.id}
                step={step}
                curves={curves}
                runs={runs}
                runDetails={runDetails}
                readOnly={readOnly}
                mostRecentCurve={mostRecentCurve}
                mostRecentRun={mostRecentRun}
                onStatusChange={(status) => patchStep(step.id, { status })}
                onValueChange={(value) => schedule({ steps: [{ id: step.id, value }] })}
                onNotesChange={(notes) => schedule({ steps: [{ id: step.id, notes }] })}
                onLinkCurve={(id) =>
                  patchStep(step.id, { curve_ids: [...step.curve_ids, id] })
                }
                onUnlinkCurve={(id) =>
                  patchStep(step.id, { curve_ids: step.curve_ids.filter((c) => c !== id) })
                }
                onLinkRun={(id) => patchStep(step.id, { run_ids: [...step.run_ids, id] })}
                onUnlinkRun={(id) =>
                  patchStep(step.id, { run_ids: step.run_ids.filter((r) => r !== id) })
                }
                onOpenCurve={setOpenCurve}
                onOpenRun={setOpenRun}
              />
            ))}
          </CardContent>
        </Card>
      ))}

      {report.open_questions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Open questions</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {report.open_questions.map((q) => (
              <OpenQuestionRow
                key={q.id}
                id={q.id}
                text={q.text}
                initialAnswer={q.answer}
                readOnly={readOnly}
                onChange={(answer) => schedule({ open_questions: [{ id: q.id, answer }] })}
              />
            ))}
          </CardContent>
        </Card>
      )}

      <CurveDetailDialog record={openCurve} onClose={() => setOpenCurve(null)} />
      <RunPlayerDialog
        run={openRun}
        curves={curves}
        onClose={() => setOpenRun(null)}
        onDeleted={() => onLibraryChanged?.()}
      />
    </div>
  )
}

function ProgressBar({ report }: { report: ReportRecord }) {
  const total = report.steps.length
  const done = report.steps.filter((s) => s.status === 'done').length
  const failed = report.steps.filter((s) => s.status === 'failed').length
  const pct = total === 0 ? 0 : (done / total) * 100
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
        {progressLabel({ n_done: done, n_steps: total })}
        {failed > 0 ? ` (${failed} failed)` : ''}
      </span>
    </div>
  )
}

function FieldsTable({
  fields,
  readOnly,
  onChange,
}: {
  fields: Record<string, string>
  readOnly: boolean
  onChange: (key: string, value: string) => void
}) {
  const keys = Object.keys(fields)
  if (keys.length === 0) return null
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
      {keys.map((key) => (
        <FieldRow
          key={key}
          fieldKey={key}
          initialValue={fields[key]}
          readOnly={readOnly}
          onChange={(v) => onChange(key, v)}
        />
      ))}
    </dl>
  )
}

// Local state seeded once at mount, not resynced from the `fields` prop on
// every render - see ReportView's own doc comment on why typed inputs work
// this way (the same "prefill read once at mount" pattern MeasurePane
// already uses). ReportView is remounted (key={report.id}) whenever a
// different report is opened, which is the only time this should reset.
function FieldRow({
  fieldKey,
  initialValue,
  readOnly,
  onChange,
}: {
  fieldKey: string
  initialValue: string
  readOnly: boolean
  onChange: (value: string) => void
}) {
  const [value, setValue] = useState(initialValue)
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs text-muted-foreground">{humanizeKey(fieldKey)}</dt>
      <dd>
        <input
          type="text"
          value={value}
          readOnly={readOnly}
          onChange={(e) => {
            setValue(e.target.value)
            onChange(e.target.value)
          }}
          className="w-full rounded-md border bg-transparent px-2 py-1 text-sm text-foreground read-only:cursor-default read-only:opacity-70"
        />
      </dd>
    </div>
  )
}

function StatusControl({
  status,
  readOnly,
  onChange,
}: {
  status: string
  readOnly: boolean
  onChange: (status: StepStatus) => void
}) {
  return (
    <select
      value={STEP_STATUSES.includes(status as StepStatus) ? status : 'todo'}
      disabled={readOnly}
      onChange={(e) => onChange(e.target.value as StepStatus)}
      aria-label="Step status"
      className="rounded-md border bg-transparent px-2 py-1 text-xs capitalize text-foreground print:hidden"
    >
      {STEP_STATUSES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  )
}

function statusVariant(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
  if (status === 'done') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'skipped') return 'secondary'
  return 'outline'
}

function StepCard({
  step,
  curves,
  runs,
  runDetails,
  readOnly,
  mostRecentCurve,
  mostRecentRun,
  onStatusChange,
  onValueChange,
  onNotesChange,
  onLinkCurve,
  onUnlinkCurve,
  onLinkRun,
  onUnlinkRun,
  onOpenCurve,
  onOpenRun,
}: {
  step: ReportStep
  curves: CurveRecord[]
  runs: RunSummary[]
  runDetails: Record<string, RunDetail>
  readOnly: boolean
  mostRecentCurve: CurveRecord | null
  mostRecentRun: RunSummary | null
  onStatusChange: (status: StepStatus) => void
  onValueChange: (value: number | string) => void
  onNotesChange: (notes: string) => void
  onLinkCurve: (id: string) => void
  onUnlinkCurve: (id: string) => void
  onLinkRun: (id: string) => void
  onUnlinkRun: (id: string) => void
  onOpenCurve: (record: CurveRecord) => void
  onOpenRun: (run: RunSummary) => void
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-step-id={step.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">{step.title}</p>
          {step.instructions && (
            <p className="text-xs text-muted-foreground">{step.instructions}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={statusVariant(step.status)} className="print:hidden">
            {step.status}
          </Badge>
          <StatusControl status={step.status} readOnly={readOnly} onChange={onStatusChange} />
        </div>
      </div>

      {(step.kind === 'number' || step.kind === 'text') && (
        <StepValueInput step={step} readOnly={readOnly} onChange={onValueChange} />
      )}

      {step.kind === 'curve' && (
        <CurveStepBody
          step={step}
          curves={curves}
          readOnly={readOnly}
          mostRecentCurve={mostRecentCurve}
          onLink={onLinkCurve}
          onUnlink={onUnlinkCurve}
          onOpen={onOpenCurve}
        />
      )}

      {step.kind === 'run' && (
        <RunStepBody
          step={step}
          curves={curves}
          runs={runs}
          runDetails={runDetails}
          readOnly={readOnly}
          mostRecentRun={mostRecentRun}
          onLink={onLinkRun}
          onUnlink={onUnlinkRun}
          onOpen={onOpenRun}
        />
      )}

      <NotesField initialNotes={step.notes} readOnly={readOnly} onChange={onNotesChange} />
    </div>
  )
}

function StepValueInput({
  step,
  readOnly,
  onChange,
}: {
  step: ReportStep
  readOnly: boolean
  onChange: (value: number | string) => void
}) {
  const [text, setText] = useState(step.value === null ? '' : String(step.value))
  const isNumber = step.kind === 'number'

  function commit(raw: string) {
    setText(raw)
    if (!isNumber) {
      onChange(raw)
      return
    }
    const n = Number(raw)
    if (raw.trim() !== '' && Number.isFinite(n)) onChange(n)
  }

  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      Value{step.unit ? ` (${step.unit})` : ''}
      {isNumber ? (
        <input
          type="number"
          value={text}
          readOnly={readOnly}
          onChange={(e) => commit(e.target.value)}
          className="w-40 rounded-md border bg-transparent px-2 py-1 text-sm text-foreground read-only:cursor-default read-only:opacity-70"
        />
      ) : (
        <textarea
          value={text}
          readOnly={readOnly}
          onChange={(e) => commit(e.target.value)}
          rows={2}
          className="w-full rounded-md border bg-transparent px-2 py-1 text-sm text-foreground read-only:cursor-default read-only:opacity-70"
        />
      )}
    </label>
  )
}

function NotesField({
  initialNotes,
  readOnly,
  onChange,
}: {
  initialNotes: string
  readOnly: boolean
  onChange: (notes: string) => void
}) {
  const [notes, setNotes] = useState(initialNotes)
  if (readOnly && notes.trim() === '') return null
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      Notes
      <textarea
        value={notes}
        readOnly={readOnly}
        onChange={(e) => {
          setNotes(e.target.value)
          onChange(e.target.value)
        }}
        rows={2}
        placeholder={readOnly ? undefined : 'Notes...'}
        className="w-full rounded-md border bg-transparent px-2 py-1 text-sm text-foreground read-only:cursor-default read-only:opacity-70"
      />
    </label>
  )
}

function OpenQuestionRow({
  id,
  text,
  initialAnswer,
  readOnly,
  onChange,
}: {
  id: string
  text: string
  initialAnswer: string
  readOnly: boolean
  onChange: (answer: string) => void
}) {
  const [answer, setAnswer] = useState(initialAnswer)
  return (
    <div className="flex flex-col gap-1" data-question-id={id}>
      <p className="text-sm text-foreground">{text}</p>
      <textarea
        value={answer}
        readOnly={readOnly}
        onChange={(e) => {
          setAnswer(e.target.value)
          onChange(e.target.value)
        }}
        rows={2}
        placeholder={readOnly ? undefined : 'Answer...'}
        aria-label={`Answer: ${text}`}
        className="w-full rounded-md border bg-transparent px-2 py-1 text-sm text-foreground read-only:cursor-default read-only:opacity-70"
      />
    </div>
  )
}

function repeatsLabel(linked: number, repeats: number): string {
  return `${linked} / ${repeats} repeat${repeats === 1 ? '' : 's'}`
}

function StatRow({ label, unit, stats }: { label: string; unit: string; stats: Stats | null }) {
  if (stats === null) return null
  if (stats.n === 1) {
    return (
      <p>
        {label}: {stats.median.toFixed(3)} {unit}
      </p>
    )
  }
  return (
    <p>
      {label}: median {stats.median.toFixed(3)} {unit}, mean {stats.mean.toFixed(3)} {unit}, std{' '}
      {stats.std !== null ? stats.std.toFixed(3) : '-'} {unit}, min {stats.min.toFixed(3)} {unit},
      max {stats.max.toFixed(3)} {unit} (n = {stats.n})
    </p>
  )
}

function CurveStepBody({
  step,
  curves,
  readOnly,
  mostRecentCurve,
  onLink,
  onUnlink,
  onOpen,
}: {
  step: ReportStep
  curves: CurveRecord[]
  readOnly: boolean
  mostRecentCurve: CurveRecord | null
  onLink: (id: string) => void
  onUnlink: (id: string) => void
  onOpen: (record: CurveRecord) => void
}) {
  const { formatCurrent, formatPower } = useUnits()
  const [pick, setPick] = useState('')
  const linkedRecords = step.curve_ids
    .map((id) => curves.find((c) => c.id === id))
    .filter((c): c is CurveRecord => !!c)
  const unlinkedCurves = curves.filter((c) => !step.curve_ids.includes(c.id))
  const stats = useMemo(() => curveStepStats(linkedRecords), [linkedRecords])
  const canLinkMostRecent =
    !readOnly && mostRecentCurve !== null && !step.curve_ids.includes(mostRecentCurve.id)

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        {repeatsLabel(step.curve_ids.length, step.repeats)}
      </p>

      {step.curve_ids.length === 0 && (
        <p className="text-xs text-muted-foreground">No curves linked yet.</p>
      )}

      {step.curve_ids.map((id) => {
        const record = curves.find((c) => c.id === id)
        if (!record) {
          return (
            <p key={id} className="text-xs text-destructive">
              Curve &ldquo;{id}&rdquo; - missing (may have been deleted).{' '}
              {!readOnly && (
                <button type="button" className="underline" onClick={() => onUnlink(id)}>
                  Remove link
                </button>
              )}
            </p>
          )
        }
        const metrics = curveMetrics(record)
        return (
          <div key={id} className="flex flex-col gap-1 rounded-md border p-2 sm:flex-row sm:items-center sm:gap-3">
            <div className="w-full sm:w-48">
              <CurveChart points={record.points} heightClassName="h-24" />
            </div>
            <div className="flex-1 text-xs text-muted-foreground">
              <button
                type="button"
                className="text-left font-medium text-foreground underline-offset-2 hover:underline"
                onClick={() => onOpen(record)}
              >
                {record.label || id}
              </button>
              {metrics && (
                <p>
                  Voc {metrics.voc.toFixed(2)} V - Isc {formatCurrent(metrics.isc)} - Vmp{' '}
                  {metrics.vmp.toFixed(2)} V - Imp {formatCurrent(metrics.imp)} - P_mpp{' '}
                  {formatPower(metrics.pMpp)}
                </p>
              )}
            </div>
            {!readOnly && (
              <button
                type="button"
                className="shrink-0 self-start text-xs text-muted-foreground underline print:hidden"
                onClick={() => onUnlink(id)}
              >
                Unlink
              </button>
            )}
          </div>
        )
      })}

      {(stats.voc || stats.isc || stats.vmp || stats.imp || stats.pMpp) && (
        <div className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
          <StatRow label="Voc" unit="V" stats={stats.voc} />
          <StatRow label="Isc" unit="A" stats={stats.isc} />
          <StatRow label="Vmp" unit="V" stats={stats.vmp} />
          <StatRow label="Imp" unit="A" stats={stats.imp} />
          <StatRow label="P_mpp" unit="W" stats={stats.pMpp} />
        </div>
      )}

      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          <select
            value={pick}
            onChange={(e) => setPick(e.target.value)}
            aria-label="Pick a curve to link"
            className="rounded-md border bg-transparent px-2 py-1 text-xs text-foreground"
          >
            <option value="">Pick a curve...</option>
            {unlinkedCurves.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label || c.id} ({formatCapturedAt(c.captured_at)})
              </option>
            ))}
          </select>
          <Button
            size="xs"
            variant="outline"
            disabled={pick === ''}
            onClick={() => {
              onLink(pick)
              setPick('')
            }}
          >
            Link
          </Button>
          <Button
            size="xs"
            variant="outline"
            disabled={!canLinkMostRecent}
            onClick={() => mostRecentCurve && onLink(mostRecentCurve.id)}
          >
            Link most recent curve
          </Button>
        </div>
      )}
    </div>
  )
}

function RunStepBody({
  step,
  curves,
  runs,
  runDetails,
  readOnly,
  mostRecentRun,
  onLink,
  onUnlink,
  onOpen,
}: {
  step: ReportStep
  curves: CurveRecord[]
  runs: RunSummary[]
  runDetails: Record<string, RunDetail>
  readOnly: boolean
  mostRecentRun: RunSummary | null
  onLink: (id: string) => void
  onUnlink: (id: string) => void
  onOpen: (run: RunSummary) => void
}) {
  const { formatPower } = useUnits()
  const [pick, setPick] = useState('')
  const unlinkedRuns = runs.filter((r) => !step.run_ids.includes(r.id))
  const canLinkMostRecent = !readOnly && mostRecentRun !== null && !step.run_ids.includes(mostRecentRun.id)

  const metrics = useMemo(
    () =>
      step.run_ids
        .map((id) => {
          const detail = runDetails[id]
          if (!detail) return null
          const reference = findCurveForRun(curves, detail.curve_ref)
          const mppTh = reference ? curveMetrics(reference) : null
          return runMetrics(detail.samples, mppTh ? { v: mppTh.vmp, i: mppTh.imp } : null)
        })
        .filter((m): m is NonNullable<typeof m> => m !== null),
    [step.run_ids, runDetails, curves],
  )
  const stats = useMemo(() => runStepStats(metrics), [metrics])

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        {repeatsLabel(step.run_ids.length, step.repeats)}
      </p>

      {step.run_ids.length === 0 && (
        <p className="text-xs text-muted-foreground">No runs linked yet.</p>
      )}

      {step.run_ids.map((id) => {
        const summary = runs.find((r) => r.id === id)
        if (!summary) {
          return (
            <p key={id} className="text-xs text-destructive">
              Run &ldquo;{id}&rdquo; - missing (may have been deleted).{' '}
              {!readOnly && (
                <button type="button" className="underline" onClick={() => onUnlink(id)}>
                  Remove link
                </button>
              )}
            </p>
          )
        }
        const detail = runDetails[id]
        const reference = detail ? findCurveForRun(curves, detail.curve_ref) : null
        const mppTh = reference ? curveMetrics(reference) : null
        const m = detail ? runMetrics(detail.samples, mppTh ? { v: mppTh.vmp, i: mppTh.imp } : null) : null
        return (
          <div key={id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2 text-xs">
            <div>
              <button
                type="button"
                className="text-left font-medium text-foreground underline-offset-2 hover:underline"
                onClick={() => onOpen(summary)}
              >
                {summary.label || id}
              </button>
              <p className="text-muted-foreground">
                {summary.algorithm} - {summary.duration_s.toFixed(1)} s
                {summary.aborted ? ' - aborted' : ''}
              </p>
              {m ? (
                <p className="text-muted-foreground">
                  Held {formatPower(m.heldPower)}
                  {m.pOverMppTh !== null && ` - P/MPP_th ${(m.pOverMppTh * 100).toFixed(1)} %`}
                  {m.timeToConvergeS !== null
                    ? ` - converged in ${m.timeToConvergeS.toFixed(2)} s`
                    : ''}
                </p>
              ) : (
                <p className="text-muted-foreground">Loading statistics...</p>
              )}
            </div>
            {!readOnly && (
              <button
                type="button"
                className="text-xs text-muted-foreground underline print:hidden"
                onClick={() => onUnlink(id)}
              >
                Unlink
              </button>
            )}
          </div>
        )
      })}

      {(stats.heldPower || stats.pOverMppTh || stats.timeToConvergeS) && (
        <div className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
          <StatRow label="Held power" unit="W" stats={stats.heldPower} />
          {stats.pOverMppTh && <StatRow label="P / MPP_th" unit="" stats={stats.pOverMppTh} />}
          {stats.timeToConvergeS && (
            <StatRow label="Time to converge" unit="s" stats={stats.timeToConvergeS} />
          )}
        </div>
      )}

      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          <select
            value={pick}
            onChange={(e) => setPick(e.target.value)}
            aria-label="Pick a run to link"
            className="rounded-md border bg-transparent px-2 py-1 text-xs text-foreground"
          >
            <option value="">Pick a run...</option>
            {unlinkedRuns.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label || r.id} ({formatCapturedAt(r.captured_at)})
              </option>
            ))}
          </select>
          <Button
            size="xs"
            variant="outline"
            disabled={pick === ''}
            onClick={() => {
              onLink(pick)
              setPick('')
            }}
          >
            Link
          </Button>
          <Button
            size="xs"
            variant="outline"
            disabled={!canLinkMostRecent}
            onClick={() => mostRecentRun && onLink(mostRecentRun.id)}
          >
            Link most recent run
          </Button>
        </div>
      )}
    </div>
  )
}
