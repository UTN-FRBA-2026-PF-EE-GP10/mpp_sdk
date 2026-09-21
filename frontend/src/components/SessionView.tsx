import { ChevronDown, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CurveChart } from '@/components/CurveChart'
import { CurveDetailDialog } from '@/components/CurveDetailDialog'
import { RunChart } from '@/components/RunChart'
import { RunPlayerDialog } from '@/components/RunPlayerDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDebouncedPatch } from '@/hooks/useDebouncedPatch'
import { formatCapturedAt } from '@/lib/format'
import { isPanelModelSnapshotField } from '@/lib/panels'
import {
  downloadSessionExportFile,
  downloadSessionJson,
  downloadSessionMarkdown,
} from '@/lib/sessionExport'
import {
  curveMetrics,
  curveStepStats,
  runMetrics,
  runStepStats,
  type Stats,
} from '@/lib/sessionStats'
import {
  groupStepsBySection,
  humanizeKey,
  progressLabel,
  STEP_STATUSES,
  type SessionPatch,
  type SessionRecord,
  type SessionStep,
  type SessionStepPatch,
  type StepStatus,
} from '@/lib/sessions'
import { findCurveForRun, referenceCurveMessage } from '@/lib/runPlayback'
import { useUnits } from '@/lib/units'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/** A click on "Expand all"/"Collapse all" in the session header - each
 * linked-item row is its own local expand/collapse state (per the design:
 * not persisted, not a store), but bumping `token` here is how one click
 * reaches every row at once. `token` changing is the signal; `expanded`
 * is the value rows should adopt. A row's own later clicks take over
 * again until the next bump. */
interface ExpandAllSignal {
  expanded: boolean
  token: number
}

const INITIAL_EXPAND_SIGNAL: ExpandAllSignal = { expanded: false, token: 0 }

/** Adopts `signal`'s value whenever it changes (token 0 means "no click
 * yet" - rows stay collapsed by default), while still letting the row's
 * own chevron toggle it in between signals. Adjusts state during render
 * (the React-documented way to sync state to a changed prop) rather than
 * an effect, so a fresh Expand all/Collapse all click takes effect in the
 * same render instead of a following one. */
function useRowExpansion(signal: ExpandAllSignal): [boolean, () => void] {
  const [expanded, setExpanded] = useState(false)
  // Starts at the initial token, never at the current one: a row that
  // mounts after an Expand all (a curve linked just now) must adopt that
  // state too, instead of sitting collapsed among expanded rows.
  const [seenToken, setSeenToken] = useState(INITIAL_EXPAND_SIGNAL.token)
  if (signal.token !== seenToken) {
    setSeenToken(signal.token)
    setExpanded(signal.expanded)
  }
  return [expanded, () => setExpanded((v) => !v)]
}

/**
 * The main pane for one bench session - a readable document from header to
 * open questions. Takes the session plus every curve/run it might need to
 * render already loaded, and makes no fetch of its own (not even for the
 * template - see `humanizeKey`'s use as a field-label fallback): an
 * imported session file's view mode can render this straight from the
 * file, with no server at all, by supplying the same props from the
 * file's own bundled records instead of a live fetch.
 *
 * Mutations go out through `onPatch` (debounced here - see
 * hooks/useDebouncedPatch.ts) and `onDeleteSession`, never called directly
 * against the API: the container (SessionPane) owns the network, this
 * component owns the document.
 */
export interface SessionViewProps {
  session: SessionRecord
  curves: CurveRecord[]
  runs: RunSummary[]
  /** Full run detail (with samples), keyed by run id - needed to compute
   * a run step's held power / P-over-MPP_th / time-to-converge. An id
   * with no entry here renders its per-run numbers as "-" rather than
   * blocking the rest of the step; the container fills this in
   * progressively (see SessionPane) or, for an imported session file,
   * supplies it all up front with no fetch at all. */
  runDetails?: Record<string, RunDetail>
  /** True while some linked run's detail fetch is still in flight (see
   * SessionPane's own doc comment on why) - disables "Export session
   * file" so a click mid-fetch can never write a live run into the
   * file's `missing` list. Always false for an already-complete,
   * no-fetch-at-all source (sandbox mode, an imported session file). */
  runDetailsPending?: boolean
  readOnly: boolean
  onPatch?: (patch: SessionPatch) => Promise<SessionRecord>
  onDeleteSession?: () => Promise<void>
  /** Fires after a run is deleted from the embedded run player - lets the
   * container refresh its own curve/run lists. Never fires in read-only
   * mode (RunPlayerDialog's own delete button is disabled there). */
  onLibraryChanged?: () => void
  /** Runs one "Capture into this step": sweep or run, save stamped with
   * this session, link to the step (see lib/sessionCapture.ts). Rejects
   * with a message to show as-is. Absent - and so the button - in read-only
   * mode and whenever the container cannot capture. */
  onCaptureIntoStep?: (step: SessionStep, algorithm?: string) => Promise<void>
  /** Why capturing is off right now, per kind (no live link), or null. */
  captureUnavailable?: { curve: string | null; run: string | null }
  /** Algorithms a run step can pick from; empty leaves the server's first. */
  runAlgorithms?: string[]
  /** Seconds a captured run lasts, for the confirmation; unknown until the
   * server's run config has loaded. */
  runDurationS?: number
  /** Run ids whose full detail could not be loaded (not a 404): they will
   * be named as missing in an exported file. */
  failedRunIds?: string[]
  /** Asks for the failed run details again. */
  onRetryRunDetails?: () => void
}

/** What one step's body needs to offer "Capture into this step". */
interface StepCapture {
  /** Some step is capturing - only one sweep or run can be in flight. */
  busy: boolean
  capturingThis: boolean
  error: string | null
  unavailableReason: string | null
  algorithms: string[]
  onCapture: (algorithm?: string) => void
}

function SaveIndicator({ state, error }: { state: string; error: string | null }) {
  if (state === 'idle') return null
  if (state === 'saving') return <span className="text-xs text-muted-foreground">Saving...</span>
  if (state === 'error') {
    return <span className="text-xs text-destructive">Failed to save{error ? `: ${error}` : ''}</span>
  }
  return <span className="text-xs text-muted-foreground">Saved</span>
}

export function SessionView({
  session,
  curves,
  runs,
  runDetails = {},
  runDetailsPending = false,
  readOnly,
  onPatch,
  onDeleteSession,
  onLibraryChanged,
  onCaptureIntoStep,
  captureUnavailable,
  runAlgorithms = [],
  runDurationS,
  failedRunIds = [],
  onRetryRunDetails,
}: SessionViewProps) {
  const { schedule, sendNow, state, error } = useDebouncedPatch(readOnly ? undefined : onPatch)
  const [openCurve, setOpenCurve] = useState<CurveRecord | null>(null)
  const [openRun, setOpenRun] = useState<RunSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [expandAllSignal, setExpandAllSignal] = useState<ExpandAllSignal>(INITIAL_EXPAND_SIGNAL)
  const [capturingStepId, setCapturingStepId] = useState<string | null>(null)
  // The guard against a second capture, in a ref because state is only
  // seen after the next render: two clicks in one tick would both pass a
  // state check. The state above is for what is drawn.
  const capturingRef = useRef<string | null>(null)
  const [captureErrors, setCaptureErrors] = useState<Record<string, string>>({})

  // A collapsed row has no chart in the DOM at all, so Ctrl+P would print
  // a session with no charts. Expanding on beforeprint keeps the printed
  // document complete without asking the operator to remember a button.
  useEffect(() => {
    const expandForPrint = () =>
      setExpandAllSignal((s) => ({ expanded: true, token: s.token + 1 }))
    const restore = () => setExpandAllSignal((s) => ({ expanded: false, token: s.token + 1 }))
    window.addEventListener('beforeprint', expandForPrint)
    window.addEventListener('afterprint', restore)
    return () => {
      window.removeEventListener('beforeprint', expandForPrint)
      window.removeEventListener('afterprint', restore)
    }
  }, [])

  const sections = useMemo(() => groupStepsBySection(session.steps), [session.steps])
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

  // Curves and runs filed into this session (stamped with its id) that no
  // step links - captured from Measure while it was active, or unlinked
  // since. Listed so they are never out of sight, and so they can be linked.
  const linkedCurveIds = useMemo(
    () => new Set(session.steps.flatMap((s) => s.curve_ids)),
    [session.steps],
  )
  const linkedRunIds = useMemo(
    () => new Set(session.steps.flatMap((s) => s.run_ids)),
    [session.steps],
  )
  const unlinkedCurves = useMemo(
    () => curves.filter((c) => c.session_id === session.id && !linkedCurveIds.has(c.id)),
    [curves, session.id, linkedCurveIds],
  )
  const unlinkedRuns = useMemo(
    () => runs.filter((r) => r.session_id === session.id && !linkedRunIds.has(r.id)),
    [runs, session.id, linkedRunIds],
  )

  function captureFor(step: SessionStep): StepCapture | null {
    if (readOnly || !onCaptureIntoStep) return null
    const kind = step.kind === 'run' ? 'run' : 'curve'
    return {
      busy: capturingStepId !== null,
      capturingThis: capturingStepId === step.id,
      error: captureErrors[step.id] ?? null,
      unavailableReason: captureUnavailable?.[kind] ?? null,
      algorithms: runAlgorithms,
      onCapture: (algorithm) => void handleCapture(step, algorithm),
    }
  }

  async function handleCapture(step: SessionStep, algorithm?: string) {
    if (readOnly || !onCaptureIntoStep || capturingRef.current !== null) return // defense in depth
    // A run drives the real converter - same bar as RunPane's Start run,
    // and it names what will run, as that one does.
    if (step.kind === 'run') {
      const chosen = algorithm ?? runAlgorithms[0]
      const what = chosen ? ` "${chosen}"` : ''
      const duration = runDurationS === undefined ? '' : ` (${runDurationS}s)`
      if (
        !window.confirm(
          `Start a live${what} run${duration} for "${step.title}"? This drives the real converter.`,
        )
      ) {
        return
      }
    }
    capturingRef.current = step.id
    setCapturingStepId(step.id)
    setCaptureErrors((prev) => {
      const next = { ...prev }
      delete next[step.id]
      return next
    })
    try {
      await onCaptureIntoStep(step, algorithm)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setCaptureErrors((prev) => ({ ...prev, [step.id]: message }))
    } finally {
      capturingRef.current = null
      setCapturingStepId(null)
    }
  }

  function patchStep(id: string, changes: Omit<SessionStepPatch, 'id'>) {
    sendNow({ steps: [{ id, ...changes }] })
  }

  async function handleDelete() {
    if (!onDeleteSession) return
    if (!window.confirm(`Delete session "${session.title}"? This cannot be undone.`)) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDeleteSession()
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
      setDeleting(false)
    }
  }

  function handleExportSessionFile() {
    if (runDetailsPending) return // defense in depth - the button is disabled anyway
    downloadSessionExportFile(session, curves, runDetails, runs)
  }

  return (
    <div className="flex flex-col gap-4 print:gap-3">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle className="text-xl">{session.title}</CardTitle>
              <p className="text-sm text-muted-foreground">
                {session.template_id} - setup: {session.setup}
              </p>
            </div>
            <div className="flex items-center gap-2 print:hidden">
              {readOnly && <Badge variant="secondary">Read-only</Badge>}
              {!readOnly && <SaveIndicator state={state} error={error} />}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Created {formatCapturedAt(session.created_at)} - updated{' '}
            {formatCapturedAt(session.updated_at)}
          </p>
          <ProgressBar session={session} />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FieldsTable
            key={session.id}
            fields={session.fields}
            readOnly={readOnly}
            onChange={(key, value) => schedule({ fields: { [key]: value } })}
          />
          <div className="flex flex-wrap gap-2 print:hidden">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setExpandAllSignal((s) => ({ expanded: true, token: s.token + 1 }))
              }
            >
              Expand all
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setExpandAllSignal((s) => ({ expanded: false, token: s.token + 1 }))
              }
            >
              Collapse all
            </Button>
            <Button variant="outline" size="sm" onClick={() => downloadSessionJson(session)}>
              Download JSON
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadSessionMarkdown(session, curves, runs, runDetails)}
            >
              Download Markdown
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportSessionFile}
              disabled={runDetailsPending}
              focusableWhenDisabled
              title={
                runDetailsPending
                  ? 'Waiting on linked run details to finish loading'
                  : undefined
              }
            >
              Export session file
            </Button>
            {onDeleteSession && (
              <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting...' : 'Delete session'}
              </Button>
            )}
          </div>
          {deleteError && <p className="text-sm text-destructive">Failed to delete: {deleteError}</p>}
          {failedRunIds.length > 0 && (
            <p className="flex flex-wrap items-center gap-2 text-sm text-destructive print:hidden">
              Could not load {failedRunIds.length} run{failedRunIds.length === 1 ? '' : 's'} for this
              session. An exported session file will name{' '}
              {failedRunIds.length === 1 ? 'it' : 'them'} as missing.
              {onRetryRunDetails && (
                <Button size="xs" variant="outline" onClick={onRetryRunDetails}>
                  Retry
                </Button>
              )}
            </p>
          )}
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
                expandAllSignal={expandAllSignal}
                capture={captureFor(step)}
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

      {(unlinkedCurves.length > 0 || unlinkedRuns.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>Captured in this session, not linked to a step</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {unlinkedCurves.map((c) => (
              <UnlinkedItemRow
                key={c.id}
                label={c.label || c.id}
                capturedAt={c.captured_at}
                what="curve"
                steps={session.steps.filter((s) => s.kind === 'curve')}
                readOnly={readOnly}
                onOpen={() => setOpenCurve(c)}
                onLink={(stepId) => {
                  const step = session.steps.find((s) => s.id === stepId)
                  if (step) patchStep(stepId, { curve_ids: [...step.curve_ids, c.id] })
                }}
              />
            ))}
            {unlinkedRuns.map((r) => (
              <UnlinkedItemRow
                key={r.id}
                label={r.label || r.id}
                capturedAt={r.captured_at}
                what="run"
                steps={session.steps.filter((s) => s.kind === 'run')}
                readOnly={readOnly}
                onOpen={() => setOpenRun(r)}
                onLink={(stepId) => {
                  const step = session.steps.find((s) => s.id === stepId)
                  if (step) patchStep(stepId, { run_ids: [...step.run_ids, r.id] })
                }}
              />
            ))}
          </CardContent>
        </Card>
      )}

      {session.open_questions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Open questions</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {session.open_questions.map((q) => (
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

function ProgressBar({ session }: { session: SessionRecord }) {
  const total = session.steps.length
  const done = session.steps.filter((s) => s.status === 'done').length
  const failed = session.steps.filter((s) => s.status === 'failed').length
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
// every render - see SessionView's own doc comment on why typed inputs work
// this way (the same "prefill read once at mount" pattern MeasurePane
// already uses). SessionView is remounted (key={session.id}) whenever a
// different session is opened, which is the only time this should reset.
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
  // A snapshotted panel-model number (e.g. "panel_model_voc") is
  // read-only regardless of the session's own edit/view mode - it was
  // copied from a panel model at creation, and hand-editing it here
  // would silently disagree with what that panel model says (see
  // lib/panels.ts's isPanelModelSnapshotField).
  const fieldReadOnly = readOnly || isPanelModelSnapshotField(fieldKey)
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs text-muted-foreground">{humanizeKey(fieldKey)}</dt>
      <dd>
        <input
          type="text"
          value={value}
          readOnly={fieldReadOnly}
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
  expandAllSignal,
  capture,
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
  step: SessionStep
  curves: CurveRecord[]
  runs: RunSummary[]
  runDetails: Record<string, RunDetail>
  readOnly: boolean
  mostRecentCurve: CurveRecord | null
  mostRecentRun: RunSummary | null
  expandAllSignal: ExpandAllSignal
  capture: StepCapture | null
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
          expandAllSignal={expandAllSignal}
          capture={capture}
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
          expandAllSignal={expandAllSignal}
          capture={capture}
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
  step: SessionStep
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

/**
 * "Capture into this step": one button that measures, saves the result
 * stamped with this session, and links it to the step. The existing picker
 * below it stays for linking something captured earlier.
 */
function CaptureControl({ capture, what }: { capture: StepCapture; what: 'curve' | 'run' }) {
  const [algorithm, setAlgorithm] = useState('')
  const disabled = capture.busy || capture.unavailableReason !== null
  return (
    <div className="flex flex-col gap-1 print:hidden">
      <div className="flex flex-wrap items-center gap-2">
        {what === 'run' && capture.algorithms.length > 0 && (
          <select
            value={algorithm}
            onChange={(e) => setAlgorithm(e.target.value)}
            aria-label="Algorithm to run"
            disabled={disabled}
            className="rounded-md border bg-transparent px-2 py-1 text-xs text-foreground"
          >
            <option value="">{`Default (${capture.algorithms[0]})`}</option>
            {capture.algorithms.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        )}
        <Button
          size="xs"
          onClick={() => capture.onCapture(algorithm || undefined)}
          disabled={disabled}
          focusableWhenDisabled
          title={capture.unavailableReason ?? undefined}
        >
          {capture.capturingThis
            ? what === 'run'
              ? 'Running...'
              : 'Sweeping...'
            : 'Capture into this step'}
        </Button>
        {capture.unavailableReason && (
          <span className="text-xs text-muted-foreground">{capture.unavailableReason}</span>
        )}
      </div>
      {capture.error && <p className="text-xs text-destructive">{capture.error}</p>}
    </div>
  )
}

/** One curve or run filed into this session but linked to no step, with a
 * picker to link it to one of the steps that take that kind. */
function UnlinkedItemRow({
  label,
  capturedAt,
  what,
  steps,
  readOnly,
  onOpen,
  onLink,
}: {
  label: string
  capturedAt: string
  what: 'curve' | 'run'
  steps: SessionStep[]
  readOnly: boolean
  onOpen: () => void
  onLink: (stepId: string) => void
}) {
  const [pick, setPick] = useState('')
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border px-2 py-2 text-xs">
      <span className="font-medium text-foreground">{label}</span>
      <span className="text-muted-foreground">
        {what} - {formatCapturedAt(capturedAt)}
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-2 print:hidden">
        <Button size="xs" variant="outline" onClick={onOpen}>
          Open
        </Button>
        {!readOnly && steps.length > 0 && (
          <>
            <select
              value={pick}
              onChange={(e) => setPick(e.target.value)}
              aria-label={`Step to link "${label}" to`}
              className="rounded-md border bg-transparent px-2 py-1 text-xs text-foreground"
            >
              <option value="">Link to step...</option>
              {steps.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.title}
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
          </>
        )}
      </div>
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

/**
 * One curve linked to a step, collapsed to a single row by default (the
 * chart used to render at ~190x96px inline, too small to read at the
 * bench - see the session header's Expand all for the printing angle on
 * why this stays a click instead of always-open). Expansion is local,
 * per-row state, except when overridden by `expandAllSignal`.
 */
function CurveLinkRow({
  record,
  readOnly,
  expandAllSignal,
  onUnlink,
  onOpen,
}: {
  record: CurveRecord
  readOnly: boolean
  expandAllSignal: ExpandAllSignal
  onUnlink: () => void
  onOpen: () => void
}) {
  const { formatCurrent, formatPower } = useUnits()
  const [expanded, toggle] = useRowExpansion(expandAllSignal)
  const metrics = curveMetrics(record)

  return (
    <div className="rounded-md border text-xs">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        className="flex w-full flex-wrap items-center gap-2 px-2 py-2 text-left hover:bg-muted/40"
      >
        {expanded ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="font-medium text-foreground">{record.label || record.id}</span>
        {metrics && (
          <span className="text-muted-foreground">
            Voc {metrics.voc.toFixed(2)} V - Isc {formatCurrent(metrics.isc)} - P_mpp{' '}
            {formatPower(metrics.pMpp)} - {formatCapturedAt(record.captured_at)}
          </span>
        )}
      </button>
      {expanded && (
        <div className="flex flex-col gap-2 border-t p-2">
          <CurveChart points={record.points} heightClassName="h-56" />
          {metrics && (
            <p className="text-muted-foreground">
              Vmp {metrics.vmp.toFixed(2)} V - Imp {formatCurrent(metrics.imp)}
            </p>
          )}
          <div className="flex items-center gap-2 print:hidden">
            <Button size="xs" variant="outline" onClick={onOpen}>
              Open
            </Button>
            {!readOnly && (
              <button type="button" className="text-xs text-muted-foreground underline" onClick={onUnlink}>
                Unlink
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function CurveStepBody({
  step,
  curves,
  readOnly,
  mostRecentCurve,
  expandAllSignal,
  capture,
  onLink,
  onUnlink,
  onOpen,
}: {
  step: SessionStep
  curves: CurveRecord[]
  readOnly: boolean
  mostRecentCurve: CurveRecord | null
  expandAllSignal: ExpandAllSignal
  capture: StepCapture | null
  onLink: (id: string) => void
  onUnlink: (id: string) => void
  onOpen: (record: CurveRecord) => void
}) {
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
        return (
          <CurveLinkRow
            key={id}
            record={record}
            readOnly={readOnly}
            expandAllSignal={expandAllSignal}
            onUnlink={() => onUnlink(id)}
            onOpen={() => onOpen(record)}
          />
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

      {!readOnly && capture && <CaptureControl capture={capture} what="curve" />}

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

/**
 * One run linked to a step, collapsed to a single row by default - same
 * treatment as CurveLinkRow. Expanded, it shows the run's full trace via
 * RunChart (a static playthrough: `trail` is every sample, `current` is
 * the last one - not the animated player, which lives in the dialog
 * behind Open) rather than just readouts, since `runDetails` already
 * carries everything RunChart needs (reference curve points, samples).
 */
function RunLinkRow({
  summary,
  detail,
  curves,
  readOnly,
  expandAllSignal,
  onUnlink,
  onOpen,
}: {
  summary: RunSummary
  detail: RunDetail | undefined
  curves: CurveRecord[]
  readOnly: boolean
  expandAllSignal: ExpandAllSignal
  onUnlink: () => void
  onOpen: () => void
}) {
  const { formatPower } = useUnits()
  const [expanded, toggle] = useRowExpansion(expandAllSignal)
  const reference = detail ? findCurveForRun(curves, detail.curve_ref) : null
  const mppTh = reference ? curveMetrics(reference) : null
  const m = detail ? runMetrics(detail.samples, mppTh ? { v: mppTh.vmp, i: mppTh.imp } : null) : null
  const refMessage = detail ? referenceCurveMessage(detail.curve_ref, reference) : null

  return (
    <div className="rounded-md border text-xs">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        className="flex w-full flex-wrap items-center gap-2 px-2 py-2 text-left hover:bg-muted/40"
      >
        {expanded ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="font-medium text-foreground">{summary.label || summary.id}</span>
        <span className="text-muted-foreground">
          {summary.algorithm} - {summary.duration_s.toFixed(1)} s
          {summary.aborted ? ' - aborted' : ''}
          {m ? (
            <>
              {' - Held '}
              {formatPower(m.heldPower)}
              {m.pOverMppTh !== null && ` - P/MPP_th ${(m.pOverMppTh * 100).toFixed(1)} %`}
            </>
          ) : (
            ' - loading statistics...'
          )}
        </span>
      </button>
      {expanded && (
        <div className="flex flex-col gap-2 border-t p-2">
          {detail ? (
            <>
              {refMessage && <p className="text-muted-foreground">{refMessage}</p>}
              <RunChart
                referencePoints={reference?.points ?? []}
                trail={detail.samples}
                current={detail.samples[detail.samples.length - 1] ?? null}
              />
              {m && (
                <p className="text-muted-foreground">
                  {m.timeToConvergeS === null
                    ? 'Did not settle within 5 % of MPP_th'
                    : `Converged in ${m.timeToConvergeS.toFixed(1)} s`}
                </p>
              )}
            </>
          ) : (
            <p className="text-muted-foreground">Loading run detail...</p>
          )}
          <div className="flex items-center gap-2 print:hidden">
            <Button size="xs" variant="outline" onClick={onOpen}>
              Open
            </Button>
            {!readOnly && (
              <button type="button" className="text-xs text-muted-foreground underline" onClick={onUnlink}>
                Unlink
              </button>
            )}
          </div>
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
  expandAllSignal,
  capture,
  onLink,
  onUnlink,
  onOpen,
}: {
  step: SessionStep
  curves: CurveRecord[]
  runs: RunSummary[]
  runDetails: Record<string, RunDetail>
  readOnly: boolean
  mostRecentRun: RunSummary | null
  expandAllSignal: ExpandAllSignal
  capture: StepCapture | null
  onLink: (id: string) => void
  onUnlink: (id: string) => void
  onOpen: (run: RunSummary) => void
}) {
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
        return (
          <RunLinkRow
            key={id}
            summary={summary}
            detail={runDetails[id]}
            curves={curves}
            readOnly={readOnly}
            expandAllSignal={expandAllSignal}
            onUnlink={() => onUnlink(id)}
            onOpen={() => onOpen(summary)}
          />
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

      {!readOnly && capture && <CaptureControl capture={capture} what="run" />}

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
