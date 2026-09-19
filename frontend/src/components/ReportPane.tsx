import { useEffect, useState } from 'react'
import { ReportView } from '@/components/ReportView'
import { deleteReport, fetchReport, fetchRun, patchReport } from '@/lib/api'
import { DEMO_REPORT, DEMO_RUN_DETAILS } from '@/lib/demoFixtures'
import type { ReportPatch, ReportRecord } from '@/lib/reports'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/**
 * Owns the network side of one report: fetches the full record (GET
 * /api/reports/{id}), lazily fetches full detail (with samples) for any
 * linked run a step's statistics need, and turns edits from ReportView
 * back into PATCH requests. ReportView itself never talks to the API -
 * see its own doc comment on why - so this split is what keeps it
 * reusable for the session-file view mode plan 042 Part D adds later.
 */
export function ReportPane({
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
  /** The report itself was deleted - the caller should navigate away. */
  onDeleted: () => void
}) {
  const [fetchedReport, setFetchedReport] = useState<ReportRecord | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [fetchedRunDetails, setFetchedRunDetails] = useState<Record<string, RunDetail>>({})
  const [missingRunIds, setMissingRunIds] = useState<Set<string>>(new Set())
  // Sandbox mode never fetches - the one bundled fixture is derived
  // straight from props/constants, not synced into state via an effect
  // (a render-time value here is simpler than a setState-on-mount effect,
  // and the linter agrees - see react(set-state-in-effect)).
  const report = sandbox ? DEMO_REPORT : fetchedReport
  const runDetails = sandbox ? DEMO_RUN_DETAILS : fetchedRunDetails

  // No manual "reset to loading" here: the caller mounts one ReportPane
  // per report id (App.tsx's `key={selection.id}`), so a different id is
  // already a fresh mount with fresh initial state - this effect only
  // ever needs to kick off the fetch itself.
  useEffect(() => {
    if (sandbox) return
    fetchReport(id)
      .then(setFetchedReport)
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [id, sandbox])

  // Fetches full detail (with samples) for every run a curve/run step
  // links, once per id - ReportView needs the samples to compute held
  // power / P-over-MPP_th / time-to-converge, but the report and the
  // sidebar's run list only ever carry summaries. A 404 (deleted since
  // the report linked it) is remembered rather than retried on every
  // render.
  useEffect(() => {
    if (sandbox || !report) return
    const needed = new Set<string>()
    for (const step of report.steps) for (const runId of step.run_ids) needed.add(runId)
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
  }, [report, sandbox, runDetails, missingRunIds])

  async function handlePatch(patch: ReportPatch): Promise<ReportRecord> {
    const updated = await patchReport(id, patch)
    setFetchedReport(updated)
    onChanged()
    return updated
  }

  async function handleDeleteReport(): Promise<void> {
    await deleteReport(id)
    onDeleted()
  }

  if (loadError) {
    return (
      <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        Failed to load report: {loadError}
      </p>
    )
  }

  if (!report) {
    return <p className="text-sm text-muted-foreground">Loading report...</p>
  }

  return (
    <ReportView
      key={report.id}
      report={report}
      curves={curves}
      runs={runs}
      runDetails={runDetails}
      readOnly={sandbox}
      onPatch={sandbox ? undefined : handlePatch}
      onDeleteReport={sandbox ? undefined : handleDeleteReport}
      onLibraryChanged={sandbox ? undefined : onChanged}
    />
  )
}
