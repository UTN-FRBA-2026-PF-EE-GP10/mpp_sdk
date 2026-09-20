import { useEffect, useMemo, useState } from 'react'
import { SessionView } from '@/components/SessionView'
import { useActiveSession } from '@/lib/activeSession'
import { deleteSession, fetchRun, fetchRunConfig, fetchSession, patchSession } from '@/lib/api'
import { DEMO_RUN_DETAILS, DEMO_SESSION } from '@/lib/demoFixtures'
import { captureIntoStep } from '@/lib/sessionCapture'
import type { SessionPatch, SessionRecord, SessionStep } from '@/lib/sessions'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/**
 * Owns the network side of one session: fetches the full record (GET
 * /api/sessions/{id}), lazily fetches full detail (with samples) for any
 * linked run a step's statistics need, and turns edits from SessionView
 * back into PATCH requests. SessionView itself never talks to the API -
 * see its own doc comment on why - so this split is what keeps it
 * reusable for an imported session file's view mode, which renders a
 * session with no server at all.
 */
export function SessionPane({
  id,
  curves,
  runs,
  sandbox,
  captureUnavailable,
  onChanged,
  onDeleted,
}: {
  id: string
  curves: CurveRecord[]
  runs: RunSummary[]
  sandbox: boolean
  /** Why "Capture into this step" is off right now, per kind (no live link
   * to the board), or null when it can run. Omitted means always available.
   * Ignored in sandbox mode, where the action is not offered at all. */
  captureUnavailable?: { curve: string | null; run: string | null }
  /** A field, step, or open-question edit was saved - refresh the
   * sidebar's progress counts. */
  onChanged: () => void
  /** The session itself was deleted - the caller should navigate away. */
  onDeleted: () => void
}) {
  const [fetchedSession, setFetchedSession] = useState<SessionRecord | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [fetchedRunDetails, setFetchedRunDetails] = useState<Record<string, RunDetail>>({})
  const [missingRunIds, setMissingRunIds] = useState<Set<string>>(new Set())
  const [runAlgorithms, setRunAlgorithms] = useState<string[]>([])
  const { active: activeSession, setActive: setActiveSession, clear: clearActiveSession } =
    useActiveSession()
  // Sandbox mode never fetches - the one bundled fixture is derived
  // straight from props/constants, not synced into state via an effect
  // (a render-time value here is simpler than a setState-on-mount effect,
  // and the linter agrees - see react(set-state-in-effect)).
  const session = sandbox ? DEMO_SESSION : fetchedSession
  const runDetails = sandbox ? DEMO_RUN_DETAILS : fetchedRunDetails

  // No manual "reset to loading" here: the caller mounts one SessionPane
  // per session id (App.tsx's `key={selection.id}`), so a different id is
  // already a fresh mount with fresh initial state - this effect only
  // ever needs to kick off the fetch itself.
  useEffect(() => {
    if (sandbox) return
    fetchSession(id)
      .then(setFetchedSession)
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [id, sandbox])

  // Opening a session makes it the one new captures are filed into (see
  // lib/activeSession.ts). Keyed on the id and title, not the record, so a
  // later step edit does not re-activate a session the operator has just
  // dismissed with "Stop filing". Never in demo mode: nothing is written.
  const sessionId = session?.id ?? null
  const sessionTitle = session?.title ?? ''
  useEffect(() => {
    if (sandbox || sessionId === null) return
    setActiveSession(sessionId, sessionTitle)
  }, [sandbox, sessionId, sessionTitle, setActiveSession])

  // The run steps' algorithm picker. A failed fetch only leaves the picker
  // empty - a capture then takes the server's own first algorithm.
  const hasRunStep = session?.steps.some((s) => s.kind === 'run') ?? false
  useEffect(() => {
    if (sandbox || !hasRunStep) return
    let cancelled = false
    async function load() {
      try {
        const config = await fetchRunConfig()
        if (!cancelled) setRunAlgorithms(config.algorithms)
      } catch {
        // See above.
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [sandbox, hasRunStep])

  // Fetches full detail (with samples) for every run a curve/run step
  // links, once per id - SessionView needs the samples to compute held
  // power / P-over-MPP_th / time-to-converge, but the session and the
  // sidebar's run list only ever carry summaries. A 404 (deleted since
  // the session linked it) is remembered rather than retried on every
  // render.
  useEffect(() => {
    if (sandbox || !session) return
    const needed = new Set<string>()
    for (const step of session.steps) for (const runId of step.run_ids) needed.add(runId)
    // Runs filed into this session but linked to no step are exported too
    // (see lib/sessionExport.ts), so their samples are needed as well.
    for (const r of runs) if (r.session_id === session.id) needed.add(r.id)
    const toFetch = [...needed].filter((rid) => !(rid in runDetails) && !missingRunIds.has(rid))
    if (toFetch.length === 0) return
    let cancelled = false
    for (const runId of toFetch) {
      fetchRun(runId)
        .then((detail) => {
          if (cancelled) return
          setFetchedRunDetails((prev) => ({ ...prev, [runId]: detail }))
        })
        .catch(() => {
          if (cancelled) return
          setMissingRunIds((prev) => new Set(prev).add(runId))
        })
    }
    return () => {
      cancelled = true
    }
  }, [session, sandbox, runs, runDetails, missingRunIds])

  // True while some run a step links is neither resolved nor confirmed
  // missing yet - i.e. its GET /api/runs/{id} is still in flight. Exported
  // to SessionView so "Export session file" can refuse to run while this
  // is true: sessionExportFile treats an id absent from runDetails as
  // deleted (see its own doc comment), so exporting mid-fetch would write
  // a live, in-flight run into the file's `missing` list and understate
  // its statistics. Always false in sandbox mode - DEMO_RUN_DETAILS is a
  // fixed fixture, never fetched, so nothing there is ever "in flight".
  const runDetailsPending = useMemo(() => {
    if (sandbox || !session) return false
    const linkedRunIds = new Set<string>()
    for (const step of session.steps) for (const runId of step.run_ids) linkedRunIds.add(runId)
    for (const r of runs) if (r.session_id === session.id) linkedRunIds.add(r.id)
    for (const runId of linkedRunIds) {
      if (!(runId in runDetails) && !missingRunIds.has(runId)) return true
    }
    return false
  }, [sandbox, session, runs, runDetails, missingRunIds])

  async function handlePatch(patch: SessionPatch): Promise<SessionRecord> {
    const updated = await patchSession(id, patch)
    setFetchedSession(updated)
    onChanged()
    return updated
  }

  async function handleDeleteSession(): Promise<void> {
    await deleteSession(id)
    // Curves and runs stamped with it are left alone (a stamp is not
    // ownership) - only the "file new captures here" choice must go, or the
    // next save would be rejected for naming a session that is gone.
    if (activeSession?.id === id) clearActiveSession()
    onDeleted()
  }

  // Sweeps or runs, saves the result stamped with this session, then links
  // it to the step - see lib/sessionCapture.ts for why that order leaves
  // nothing half-linked on failure. The link reads the step from the latest
  // fetched record so an earlier link on the same step is not overwritten.
  async function handleCaptureIntoStep(step: SessionStep, algorithm?: string): Promise<void> {
    if (sandbox || !session) return // defense in depth - the button is not offered either
    try {
      await captureIntoStep({
        sessionId: session.id,
        step,
        algorithm,
        link: async (kind, itemId) => {
          const current = (fetchedSession ?? session).steps.find((s) => s.id === step.id) ?? step
          await handlePatch({
            steps: [
              kind === 'curve'
                ? { id: step.id, curve_ids: [...current.curve_ids, itemId] }
                : { id: step.id, run_ids: [...current.run_ids, itemId] },
            ],
          })
        },
      })
    } finally {
      // Saved or not, the library may have changed (a curve saved but not
      // linked is still new), so the lists reload either way.
      onChanged()
    }
  }

  if (loadError) {
    return (
      <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        Failed to load session: {loadError}
      </p>
    )
  }

  if (!session) {
    return <p className="text-sm text-muted-foreground">Loading session...</p>
  }

  return (
    <SessionView
      key={session.id}
      session={session}
      curves={curves}
      runs={runs}
      runDetails={runDetails}
      runDetailsPending={runDetailsPending}
      readOnly={sandbox}
      onPatch={sandbox ? undefined : handlePatch}
      onDeleteSession={sandbox ? undefined : handleDeleteSession}
      onLibraryChanged={sandbox ? undefined : onChanged}
      onCaptureIntoStep={sandbox ? undefined : handleCaptureIntoStep}
      captureUnavailable={captureUnavailable}
      runAlgorithms={runAlgorithms}
    />
  )
}
