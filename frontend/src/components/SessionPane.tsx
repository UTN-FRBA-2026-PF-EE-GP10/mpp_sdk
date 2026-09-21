import { useEffect, useMemo, useRef, useState } from 'react'
import { SessionView } from '@/components/SessionView'
import { useActiveSession } from '@/lib/activeSession'
import { useRunDetails } from '@/hooks/useRunDetails'
import { deleteSession, fetchRunConfig, fetchSession, patchSession } from '@/lib/api'
import { DEMO_RUN_DETAILS, DEMO_SESSION } from '@/lib/demoFixtures'
import { captureIntoStep, SessionGoneError } from '@/lib/sessionCapture'
import type { SessionPatch, SessionRecord, SessionStep } from '@/lib/sessions'
import type { RunSummary } from '@/lib/runs'
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
  // The newest record the server has sent back, kept in a ref as well as in
  // state: an async capture reads it when it links, minutes after the click,
  // and a value closed over at click time would be that old. A link the
  // operator made from the picker in between must be in what gets patched.
  const latestSession = useRef<SessionRecord | null>(null)
  const [runConfig, setRunConfig] = useState<{ algorithms: string[]; durationS: number } | null>(
    null,
  )
  const { active: activeSession, setActive: setActiveSession, clear: clearActiveSession } =
    useActiveSession()
  // Sandbox mode never fetches - the one bundled fixture is derived
  // straight from props/constants, not synced into state via an effect
  // (a render-time value here is simpler than a setState-on-mount effect,
  // and the linter agrees - see react(set-state-in-effect)).
  const session = sandbox ? DEMO_SESSION : fetchedSession

  // No manual "reset to loading" here: the caller mounts one SessionPane
  // per session id (App.tsx's `key={selection.id}`), so a different id is
  // already a fresh mount with fresh initial state - this effect only
  // ever needs to kick off the fetch itself.
  useEffect(() => {
    if (sandbox) return
    fetchSession(id)
      .then((record) => {
        latestSession.current = record
        setFetchedSession(record)
      })
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

  // The run steps' algorithm picker, and the duration a run will last (for
  // the confirmation). A failed fetch only leaves the picker empty - a
  // capture then takes the server's own first algorithm.
  const hasRunStep = session?.steps.some((s) => s.kind === 'run') ?? false
  useEffect(() => {
    if (sandbox || !hasRunStep) return
    let cancelled = false
    async function load() {
      try {
        const config = await fetchRunConfig()
        if (!cancelled) {
          setRunConfig({ algorithms: config.algorithms, durationS: config.defaultDurationS })
        }
      } catch {
        // See above.
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [sandbox, hasRunStep])

  // Full detail (with samples) for every run a step links, and every run
  // filed into this session (an export includes both): SessionView needs the
  // samples for held power / P-over-MPP_th / time-to-converge, but the
  // session and the sidebar's run list only ever carry summaries. Loaded a
  // few at a time, once per id - see useRunDetails.
  const wantedRunIds = useMemo(() => {
    const ids = new Set<string>()
    if (session) {
      for (const step of session.steps) for (const runId of step.run_ids) ids.add(runId)
      for (const r of runs) if (r.session_id === session.id) ids.add(r.id)
    }
    return [...ids]
  }, [session, runs])
  const loaded = useRunDetails(wantedRunIds, !sandbox && session !== null)
  const runDetails = sandbox ? DEMO_RUN_DETAILS : loaded.details
  // True while a wanted run's detail is still being fetched. SessionView
  // disables "Export session file" on it, so a click mid-fetch can never
  // write a live run into the file's `missing` list or understate its
  // statistics. Always false in sandbox mode - DEMO_RUN_DETAILS is a fixed
  // fixture, never fetched.
  const runDetailsPending = loaded.pending
  const failedRunIds = useMemo(
    () => wantedRunIds.filter((runId) => loaded.failed.has(runId)),
    [wantedRunIds, loaded.failed],
  )

  async function handlePatch(patch: SessionPatch): Promise<SessionRecord> {
    const updated = await patchSession(id, patch)
    latestSession.current = updated
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
  // nothing half-linked on failure. The link reads the step from the newest
  // record at the moment it links, not at the click: a PATCH replaces the
  // step's whole list, so a stale read would unlink whatever was linked
  // while the capture ran.
  async function handleCaptureIntoStep(step: SessionStep, algorithm?: string): Promise<void> {
    if (sandbox || !session) return // defense in depth - the button is not offered either
    try {
      await captureIntoStep({
        sessionId: session.id,
        step,
        algorithm,
        link: async (kind, itemId) => {
          const current =
            (latestSession.current ?? session).steps.find((s) => s.id === step.id) ?? step
          await handlePatch({
            steps: [
              kind === 'curve'
                ? { id: step.id, curve_ids: [...current.curve_ids, itemId] }
                : { id: step.id, run_ids: [...current.run_ids, itemId] },
            ],
          })
        },
      })
    } catch (e) {
      // Deleted elsewhere: filing into it would fail every later save too.
      if (e instanceof SessionGoneError && activeSession?.id === session.id) clearActiveSession()
      throw e
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
      runAlgorithms={runConfig?.algorithms}
      runDurationS={runConfig?.durationS}
      failedRunIds={failedRunIds}
      onRetryRunDetails={loaded.retry}
    />
  )
}
