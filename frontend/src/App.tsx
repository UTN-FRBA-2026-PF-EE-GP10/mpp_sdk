import { Menu } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ConnectionIndicator } from '@/components/ConnectionIndicator'
import { CurveCategoryPane } from '@/components/CurveCategoryPane'
import { ImportedSessionBar } from '@/components/ImportedSessionBar'
import { MeasurePane } from '@/components/MeasurePane'
import { NewSessionPane } from '@/components/NewSessionPane'
import { OpenSessionButton } from '@/components/OpenSessionButton'
import { RunDatePane } from '@/components/RunDatePane'
import { SessionPane } from '@/components/SessionPane'
import { SetupModeToggle } from '@/components/SetupModeToggle'
import { Sidebar, type Selection } from '@/components/Sidebar'
import { ThemeToggle } from '@/components/ThemeToggle'
import { UnitToggle } from '@/components/UnitToggle'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useConnectionStatus } from '@/hooks/useConnectionStatus'
import { useSessionFileImport } from '@/hooks/useSessionFileImport'
import { deleteCurve, fetchCurves, fetchMeasurementKinds, fetchRuns, fetchSessions } from '@/lib/api'
import { useCaptureMode } from '@/lib/captureMode'
import { DEMO_CURVES, DEMO_RUNS, DEMO_SESSIONS } from '@/lib/demoFixtures'
import { groupRunsByDate, type RunSummary } from '@/lib/runs'
import { useImportedSession } from '@/lib/sessionFile'
import type { SessionSummary } from '@/lib/sessions'
import { useSetupMode } from '@/lib/setupMode'
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
  const importedSession = useImportedSession()
  const [selection, setSelection] = useState<Selection>({ root: 'measure' })
  // Jumps to the imported session's own content once it lands - Measure
  // (capture, run start) isn't a view-mode destination (see the
  // placeholder below), so landing there right after an import would show
  // nothing useful. Only ever fires from the import event itself, never
  // fights a later pick of Measure once the operator is looking at it.
  const sessionImport = useSessionFileImport((parsed) => {
    // A remeasure can only be finished by capturing, which view mode turns
    // off - leaving its banner up would be a pending state with no way to
    // resolve it. The old curve is untouched either way.
    setPendingRemeasure(null)
    if (parsed.curves.length > 0) {
      setSelection({ root: 'curves', kind: parsed.curves[0].record.measurement })
    } else if (parsed.runs.length > 0) {
      setSelection({ root: 'runs', date: parsed.runs[0].record.captured_at.slice(0, 10) })
    }
  })
  const { mode: setupMode } = useSetupMode()
  const [showFullReminder, setShowFullReminder] = useState(false)
  // Fires only on the actual single -> full transition, not on mount (Full
  // is the default, and nagging every fresh load would make the reminder
  // background noise). Two panels reach ~34-44 V, well past what the Low
  // ADC range reads cleanly, so it's worth a nudge every time someone
  // flips into that setup, not just the first time ever.
  const prevSetupModeRef = useRef(setupMode)
  useEffect(() => {
    if (prevSetupModeRef.current === 'single' && setupMode === 'full') {
      setShowFullReminder(true)
    }
    prevSetupModeRef.current = setupMode
  }, [setupMode])
  // The link poll has nothing to do while fully offline - see
  // useConnectionStatus's docstring and ConnectionIndicator's one-shot
  // check, which takes over answering "is a link available" in that mode.
  // An imported session (view mode) is offline the same way - see
  // lib/sessionFile.ts.
  const { status: connectionStatus, link: connectionLink } = useConnectionStatus(
    !sandboxEnabled && !importedSession.active,
  )
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
  const [fetchedSessions, setFetchedSessions] = useState<SessionSummary[]>([])
  const [reloadToken, setReloadToken] = useState(0)
  // An imported session takes priority over demo fixtures - both are
  // offline data sources, but an imported session is something the
  // operator chose to look at, not a fallback default. See
  // lib/sessionFile.ts.
  const records = importedSession.active ? importedSession.curves : sandboxEnabled ? DEMO_CURVES : fetchedRecords
  const runs = importedSession.active ? importedSession.runs : sandboxEnabled ? DEMO_RUNS : fetchedRuns
  // Sessions are never written in demo mode (see NewSessionPane/
  // SessionPane's sandbox gating) - the sidebar shows only the one bundled
  // read-only fixture there, the same "swap the whole list" pattern as
  // records/runs above, not a filtered view of whatever a real backend
  // happens to have.
  const sessions = importedSession.active ? [] : sandboxEnabled ? DEMO_SESSIONS : fetchedSessions

  // Neither of these is persisted (no localStorage/sessionStorage) on
  // purpose: a reload must drop a pending remeasure and leave the old
  // curve untouched (see CurveDashboardPane's onRemeasure doc comment),
  // and plain in-memory state does exactly that for free.
  const [pendingRemeasure, setPendingRemeasure] = useState<PendingRemeasure | null>(null)
  const [measurePrefill, setMeasurePrefill] = useState<MeasurePrefill | null>(null)
  const [remeasureError, setRemeasureError] = useState<string | null>(null)
  // A failed initial load used to only reach the console - the operator
  // saw an empty sidebar with no way to tell "nothing saved yet" from
  // "the request failed", and no way to retry short of reloading the page.
  const [curvesError, setCurvesError] = useState<string | null>(null)
  const [runsError, setRunsError] = useState<string | null>(null)

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
    // An imported session (view mode) is offline the same way.
    if (sandboxEnabled || importedSession.active) return
    fetchMeasurementKinds()
      .then((fetched) => setSeedKinds((prev) => Array.from(new Set([...prev, ...fetched]))))
      .catch((e) => console.error('fetching measurement kinds failed', e))
  }, [sandboxEnabled, importedSession.active])

  useEffect(() => {
    if (sandboxEnabled || importedSession.active) return
    // A retry or reload can start while an older request is still out.
    // Only the newest one may set the list or the error, or a slow stale
    // answer would overwrite the current state.
    let current = true
    fetchCurves()
      .then((data) => {
        if (!current) return
        setFetchedRecords(data)
        setCurvesError(null)
      })
      .catch((e) => {
        console.error('fetching curves failed', e)
        if (current) setCurvesError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      current = false
    }
  }, [reloadToken, sandboxEnabled, importedSession.active])

  useEffect(() => {
    if (sandboxEnabled || importedSession.active) return
    let current = true
    fetchRuns()
      .then((data) => {
        if (!current) return
        setFetchedRuns(data)
        setRunsError(null)
      })
      .catch((e) => {
        console.error('fetching runs failed', e)
        if (current) setRunsError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      current = false
    }
  }, [reloadToken, sandboxEnabled, importedSession.active])

  useEffect(() => {
    if (sandboxEnabled || importedSession.active) return
    fetchSessions()
      .then(setFetchedSessions)
      .catch((e) => console.error('fetching sessions failed', e))
  }, [reloadToken, sandboxEnabled, importedSession.active])

  // 'firmware-replay' ("Replay on the board") needs a real board on the
  // other end of a real link - ConnectionIndicator already refuses to let
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
  if (selection.root === 'measure' && importedSession.active) {
    content = (
      <Card>
        <CardHeader>
          <CardTitle>Measure is unavailable</CardTitle>
          <CardDescription>
            Capture and run start need a real board and a saved library - both are off while
            viewing an imported session. Close the session (top of the page) to measure.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  } else if (
    (selection.root === 'new-session' || selection.root === 'session') &&
    importedSession.active
  ) {
    // Guards against two write paths: the sidebar already hides "New
    // session" while an imported session is active (canCreateSession
    // below), but a session file with no curves/runs never redirects the
    // selection away from an already-open 'session' (see
    // useSessionFileImport's onImported above) - so without this branch,
    // SessionPane/NewSessionPane would stay mounted, live, and writable
    // right under the read-only "Viewing" banner.
    content = (
      <Card>
        <CardHeader>
          <CardTitle>Sessions are unavailable</CardTitle>
          <CardDescription>
            Creating or editing a session needs a saved library - that's off while viewing an
            imported session. Close the session (top of the page) first.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  } else if (selection.root === 'measure') {
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
  } else if (selection.root === 'runs') {
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
  } else if (selection.root === 'new-session') {
    content = (
      <NewSessionPane
        setupMode={setupMode}
        onCreated={(session) => {
          setReloadToken((t) => t + 1)
          setSelection({ root: 'session', id: session.id })
        }}
      />
    )
  } else {
    content = (
      <SessionPane
        key={selection.id}
        id={selection.id}
        curves={records}
        runs={runs}
        sandbox={sandboxEnabled}
        onChanged={() => setReloadToken((t) => t + 1)}
        onDeleted={() => {
          setReloadToken((t) => t + 1)
          setSelection({ root: 'measure' })
        }}
      />
    )
  }

  return (
    <div
      className="flex min-h-svh flex-col"
      // Page-wide, not just a drop zone rendered somewhere in the layout -
      // an operator dragging a session file in shouldn't need to hit a
      // specific target for it to land. See useSessionFileImport.
      onDragOver={sessionImport.handleDragOver}
      onDrop={sessionImport.handleDrop}
    >
      <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-4 print:hidden">
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
            the connection pill's label runs as long as "Replay on the
            board" - wrapping beats clipping the one control here that
            also doubles as the capture-mode trigger. */}
        <div className="flex flex-wrap items-center gap-2">
          <OpenSessionButton onFile={sessionImport.importFile} />
          <SetupModeToggle />
          <UnitToggle />
          <ThemeToggle />
          {/* Connection health is a link problem, not a per-pane one - it
              stays visible regardless of which sidebar item is selected.
              Also the capture-mode menu - see lib/captureMode.ts. */}
          <ConnectionIndicator status={connectionStatus} link={connectionLink} />
        </div>
      </header>

      <ImportedSessionBar />

      {sessionImport.error && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-destructive/40 bg-destructive/10 px-4 py-1.5 text-xs font-medium text-destructive">
          <span>Couldn&apos;t open that session file: {sessionImport.error}</span>
          <button
            type="button"
            onClick={sessionImport.dismissError}
            className="shrink-0 rounded-md border border-destructive/40 px-2 py-0.5 hover:bg-destructive/20"
          >
            Dismiss
          </button>
        </div>
      )}

      {sandboxEnabled && (
        <div className="border-b border-violet-500/30 bg-violet-500/10 px-4 py-1.5 text-center text-xs font-medium text-violet-700 dark:text-violet-300">
          Demo: showing bundled sample data, not your library. No live board, no writes.
        </div>
      )}

      {/* Outside demo mode only - sandbox mode never fetches, so any
          error here is left over from before it was entered and would be
          stale (see the fetch effects above, which skip the request but
          not the previous error state). A failed load must not read as
          "nothing saved yet" - that empty state means something different
          to an operator deciding whether to trust the library. */}
      {!sandboxEnabled && (curvesError || runsError) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-destructive/40 bg-destructive/10 px-4 py-1.5 text-xs font-medium text-destructive">
          <span>
            {curvesError && `Couldn't load your saved curves: ${curvesError}. `}
            {runsError && `Couldn't load your saved runs: ${runsError}. `}
            Check the connection to the Pi and try again.
          </span>
          <button
            type="button"
            onClick={() => setReloadToken((t) => t + 1)}
            className="shrink-0 rounded-md border border-destructive/40 px-2 py-0.5 hover:bg-destructive/20"
          >
            Retry
          </button>
        </div>
      )}

      {showFullReminder && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-xs font-medium text-amber-800 dark:text-amber-300">
          <span>
            Full setup: two panels reach ~34-44 V. Move the ADC jumpers to Mid and reflash the
            firmware, then check it against a meter (docs/hardware_v1/calibration.md).
          </span>
          <button
            type="button"
            onClick={() => setShowFullReminder(false)}
            className="shrink-0 rounded-md border border-amber-500/40 px-2 py-0.5 hover:bg-amber-500/20"
          >
            Dismiss
          </button>
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
          sessions={sessions}
          canCreateSession={!sandboxEnabled && !importedSession.active}
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
