import { Menu } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ConnectionIndicator } from '@/components/ConnectionIndicator'
import { CurveCategoryPane } from '@/components/CurveCategoryPane'
import { MeasurePane } from '@/components/MeasurePane'
import { RunDatePane } from '@/components/RunDatePane'
import { Sidebar, type Selection } from '@/components/Sidebar'
import { ThemeToggle } from '@/components/ThemeToggle'
import { UnitToggle } from '@/components/UnitToggle'
import { useConnectionStatus } from '@/hooks/useConnectionStatus'
import { deleteCurve, fetchCurves, fetchMeasurementKinds, fetchRuns } from '@/lib/api'
import { useCaptureMode } from '@/lib/captureMode'
import { DEMO_CURVES, DEMO_RUNS } from '@/lib/demoFixtures'
import { groupRunsByDate, type RunSummary } from '@/lib/runs'
import {
  isLiveConnection,
  MEASUREMENT_KINDS,
  type CurveRecord,
  type MeasurePrefill,
} from '@/types'

/** A remeasure that has been confirmed and navigated to Measure, but
 * whose old curve is not deleted yet - only `curveId` is strictly needed
 * to fire the delete; `label` is kept alongside for the banner. See
 * `startRemeasure`/`handleCurveSaved`/`cancelRemeasure` below, and
 * CurveDashboardPane's `onRemeasure` doc comment for the ordering this
 * implements. */
interface PendingRemeasure {
  curveId: string
  label: string
  /** The measurement kind being replaced - a save under any other kind
   * must not consume this remeasure or delete the old curve. */
  kind: string
}

export default function App() {
  const { mode: captureMode, setMode: setCaptureMode } = useCaptureMode()
  const sandboxEnabled = captureMode === 'simulated'
  // The link poll has nothing to do while fully offline - see
  // useConnectionStatus's docstring and ConnectionIndicator's one-shot
  // check, which takes over answering "is a link available" in that mode.
  const { status: connectionStatus } = useConnectionStatus(!sandboxEnabled)
  const [selection, setSelection] = useState<Selection>({ root: 'measure' })
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  // Seeded with the known vocabulary so the sidebar renders before the
  // first fetch lands. GET /api/measurement-kinds and any kind already in
  // the library (an operator can save under a kind this list never
  // anticipated - see mpp_sdk/curves/record.py) fold in on top.
  const [seedKinds, setSeedKinds] = useState<string[]>([...MEASUREMENT_KINDS])
  // Holds only what was actually fetched from the server - demo mode never
  // writes into this, it's swapped out for the bundled fixtures below
  // instead. That keeps a stray real fetch response that lands late (a
  // toggle right after mount, say) from ever being able to clobber the
  // fixtures on screen.
  const [fetchedRecords, setFetchedRecords] = useState<CurveRecord[]>([])
  const [fetchedRuns, setFetchedRuns] = useState<RunSummary[]>([])
  const [reloadToken, setReloadToken] = useState(0)
  const records = sandboxEnabled ? DEMO_CURVES : fetchedRecords
  const runs = sandboxEnabled ? DEMO_RUNS : fetchedRuns

  // Neither of these is persisted (no localStorage/sessionStorage) on
  // purpose: a reload must drop a pending remeasure and leave the old
  // curve untouched (see CurveDashboardPane's onRemeasure doc comment),
  // and plain in-memory state does exactly that for free.
  const [pendingRemeasure, setPendingRemeasure] = useState<PendingRemeasure | null>(null)
  const [measurePrefill, setMeasurePrefill] = useState<MeasurePrefill | null>(null)
  const [remeasureError, setRemeasureError] = useState<string | null>(null)

  /** Step 1-2 of the remeasure workflow (confirming already happened in
   * CurveDashboardPane): mark the deletion pending and send the operator
   * to Measure, prefilled from the curve being replaced. Nothing is
   * deleted here - see handleCurveSaved for step 4. */
  function startRemeasure(record: CurveRecord) {
    setRemeasureError(null)
    setPendingRemeasure({
      curveId: record.id,
      label: record.label || 'Untitled curve',
      kind: record.measurement,
    })
    setMeasurePrefill({
      kind: record.measurement,
      label: record.label,
      notes: record.notes,
      panels: record.panels,
    })
    setSelection({ root: 'measure' })
  }

  function cancelRemeasure() {
    setPendingRemeasure(null)
  }

  /** Fires on every successful Measure save. When a remeasure is pending
   * AND the save just made was under the same kind as the curve being
   * replaced, this is step 4: the replacement just landed, so now - and
   * only now - the old curve is removed. An unrelated save (a different
   * kind, e.g. while a baseline remeasure is still pending) must leave
   * the pending remeasure and the old curve untouched. A failure here
   * leaves the old curve in place (nothing destroyed, matching step 5)
   * and surfaces the error rather than pretending the cleanup happened. */
  async function handleCurveSaved(savedKind: string) {
    setReloadToken((t) => t + 1)
    const toFinish = pendingRemeasure
    if (!toFinish || toFinish.kind !== savedKind) return
    setPendingRemeasure(null)
    try {
      await deleteCurve(toFinish.curveId)
      setReloadToken((t) => t + 1)
    } catch (e) {
      setRemeasureError(
        `Captured the replacement, but couldn't remove the old "${toFinish.label}": ` +
          (e instanceof Error ? e.message : String(e)),
      )
    }
  }

  useEffect(() => {
    // The demo fixtures' kinds ('baseline', 'dimmed') are already in the
    // seeded vocabulary - no server round trip needed, and none should
    // happen while showing someone the workbench with no backend at all.
    if (sandboxEnabled) return
    fetchMeasurementKinds()
      .then((fetched) => setSeedKinds((prev) => Array.from(new Set([...prev, ...fetched]))))
      .catch((e) => console.error('fetching measurement kinds failed', e))
  }, [sandboxEnabled])

  useEffect(() => {
    if (sandboxEnabled) return
    fetchCurves()
      .then(setFetchedRecords)
      .catch((e) => console.error('fetching curves failed', e))
  }, [reloadToken, sandboxEnabled])

  useEffect(() => {
    if (sandboxEnabled) return
    fetchRuns()
      .then(setFetchedRuns)
      .catch((e) => console.error('fetching runs failed', e))
  }, [reloadToken, sandboxEnabled])

  // 'firmware-replay' ("Demo with PICO") needs a real board on the other
  // end of a real link - ConnectionIndicator already refuses to let
  // someone select it without one, but the link can also drop out from
  // under an already-selected mode. This is the other half of that rule:
  // fall back the moment it's no longer true, rather than leaving the
  // indicator showing a mode that cannot work.
  useEffect(() => {
    if (captureMode === 'firmware-replay' && connectionStatus !== 'connected') {
      setCaptureMode('hardware')
    }
  }, [captureMode, connectionStatus, setCaptureMode])

  const byKind = useMemo(() => {
    const groups = new Map<string, CurveRecord[]>()
    for (const kind of seedKinds) groups.set(kind, [])
    for (const record of records) {
      if (!groups.has(record.measurement)) groups.set(record.measurement, [])
      groups.get(record.measurement)?.push(record)
    }
    // Newest first: GET /api/curves returns records in on-disk filename
    // order, oldest first. The sidebar's curve counts don't care, but the
    // workbench's saved-curves table assumes records[0] is newest.
    for (const bucket of groups.values()) {
      bucket.sort((a, b) => b.captured_at.localeCompare(a.captured_at))
    }
    return groups
  }, [seedKinds, records])

  const kinds = useMemo(() => Array.from(byKind.keys()), [byKind])

  const countsByKind = useMemo(() => {
    const counts = new Map<string, number>()
    for (const [kind, list] of byKind) counts.set(kind, list.length)
    return counts
  }, [byKind])

  const runGroups = useMemo(() => groupRunsByDate(runs), [runs])

  let content
  if (selection.root === 'measure') {
    content = (
      <MeasurePane
        kinds={kinds}
        byKind={byKind}
        curves={records}
        connected={isLiveConnection(connectionStatus)}
        connectionStatus={connectionStatus}
        onSaved={handleCurveSaved}
        onRunSaved={() => setReloadToken((t) => t + 1)}
        prefill={measurePrefill}
        onPrefillApplied={() => setMeasurePrefill(null)}
      />
    )
  } else if (selection.root === 'curves') {
    content = (
      <CurveCategoryPane
        // A fresh pane per kind, so select mode never carries over.
        key={selection.kind}
        kind={selection.kind}
        records={byKind.get(selection.kind) ?? []}
        onDeleted={() => setReloadToken((t) => t + 1)}
        onRemeasure={startRemeasure}
        remeasurePendingId={pendingRemeasure?.curveId ?? null}
      />
    )
  } else {
    const group = runGroups.find((g) => g.date === selection.date)
    content = (
      <RunDatePane
        key={selection.date}
        date={selection.date}
        runs={group?.runs ?? []}
        curves={records}
        onRunsChanged={() => setReloadToken((t) => t + 1)}
      />
    )
  }

  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
            className="rounded-md p-1.5 hover:bg-muted md:hidden"
          >
            <Menu className="size-5" />
          </button>
          <h1 className="text-lg font-semibold tracking-tight">mpp-sdk Workbench</h1>
        </div>
        {/* flex-wrap here and on the header itself: none of these three
            controls can shrink (buttonVariants is whitespace-nowrap), and
            the connection pill's label runs as long as "Demo mode -
            simulated" - wrapping beats clipping the one control here that
            also doubles as the capture-mode trigger. */}
        <div className="flex flex-wrap items-center gap-2">
          <UnitToggle />
          <ThemeToggle />
          {/* Connection health is a link problem, not a per-pane one - it
              stays visible regardless of which sidebar item is selected.
              Also the capture-mode menu - see lib/captureMode.ts. */}
          <ConnectionIndicator status={connectionStatus} />
        </div>
      </header>

      {sandboxEnabled && (
        <div className="border-b border-violet-500/30 bg-violet-500/10 px-4 py-1.5 text-center text-xs font-medium text-violet-700 dark:text-violet-300">
          Demo mode - showing bundled sample data, not your library. No live board, no writes.
        </div>
      )}

      {/* Visible for as long as the remeasure is pending, from any
          section - it must never be a mode the operator is stuck in with
          no way out or no visible sign it's active. Cancelling here only
          drops the pending delete; the old curve was never touched. */}
      {pendingRemeasure && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-xs font-medium text-amber-800 dark:text-amber-300">
          <span>
            Remeasure pending - replacing &ldquo;{pendingRemeasure.label}&rdquo;. Capture and save
            a replacement to remove the old curve; the old curve is untouched until then.
          </span>
          <button
            type="button"
            onClick={cancelRemeasure}
            className="shrink-0 rounded-md border border-amber-500/40 px-2 py-0.5 hover:bg-amber-500/20"
          >
            Cancel remeasure
          </button>
        </div>
      )}

      {remeasureError && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-destructive/40 bg-destructive/10 px-4 py-1.5 text-xs font-medium text-destructive">
          <span>{remeasureError}</span>
          <button
            type="button"
            onClick={() => setRemeasureError(null)}
            className="shrink-0 rounded-md border border-destructive/40 px-2 py-0.5 hover:bg-destructive/20"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="relative flex flex-1">
        <Sidebar
          selection={selection}
          onSelect={setSelection}
          kinds={kinds}
          countsByKind={countsByKind}
          runGroups={runGroups}
          mobileOpen={mobileNavOpen}
          onCloseMobile={() => setMobileNavOpen(false)}
        />
        <main className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto flex max-w-4xl flex-col gap-4">{content}</div>
        </main>
      </div>
    </div>
  )
}
