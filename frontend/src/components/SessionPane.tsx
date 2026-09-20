import { useEffect, useState } from 'react'
import { SessionView } from '@/components/SessionView'
import { deleteSession, fetchRun, fetchSession, patchSession } from '@/lib/api'
import { DEMO_RUN_DETAILS, DEMO_SESSION } from '@/lib/demoFixtures'
import type { SessionPatch, SessionRecord } from '@/lib/sessions'
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
  onChanged,
  onDeleted,
}: {
  id: string
  curves: CurveRecord[]
  runs: RunSummary[]
  sandbox: boolean
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
  }, [session, sandbox, runDetails, missingRunIds])

  async function handlePatch(patch: SessionPatch): Promise<SessionRecord> {
    const updated = await patchSession(id, patch)
    setFetchedSession(updated)
    onChanged()
    return updated
  }

  async function handleDeleteSession(): Promise<void> {
    await deleteSession(id)
    onDeleted()
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
      readOnly={sandbox}
      onPatch={sandbox ? undefined : handlePatch}
      onDeleteSession={sandbox ? undefined : handleDeleteSession}
      onLibraryChanged={sandbox ? undefined : onChanged}
    />
  )
}
