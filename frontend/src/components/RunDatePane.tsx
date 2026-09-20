import { Download, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { RunPlayerDialog } from '@/components/RunPlayerDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { deleteRunsBatch, fetchRun } from '@/lib/api'
import { formatCapturedAt, formatSeconds } from '@/lib/format'
import type { RunDetail, RunSummary } from '@/lib/runs'
import {
  buildSessionFile,
  downloadSessionFile,
  readOnlyReasonText,
  useImportedSession,
  useReadOnly,
} from '@/lib/sessionFile'
import { useSetupMode } from '@/lib/setupMode'
import type { CurveRecord } from '@/types'

/**
 * One date's closed-loop runs, as a table - same click-a-row-to-open
 * pattern as CurveWorkbench's saved-curves table. Opening a row hands off
 * to RunPlayerDialog, the one place a run is played back (App.tsx is the
 * only other thing that could reach it, and doesn't need to - a run only
 * ever surfaces grouped under its date).
 *
 * Also owns this date's select mode - same "Select" / "Select all" /
 * "Export N selected" / "Delete N selected" shape as CurveCategoryPane's,
 * one POST /api/runs/delete-batch request instead of N separate DELETE
 * calls.
 */
export function RunDatePane({
  date,
  runs,
  curves,
  onRunsChanged,
}: {
  date: string
  runs: RunSummary[]
  curves: CurveRecord[]
  onRunsChanged: () => void
}) {
  const [selected, setSelected] = useState<RunSummary | null>(null)
  const readOnly = useReadOnly()
  const importedSession = useImportedSession()
  const { mode: setupMode } = useSetupMode()

  const [selectMode, setSelectMode] = useState(false)
  const [rawSelectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchFailed, setBatchFailed] = useState<{ id: string; error: string }[] | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  // Derived, not stored: a reload can drop runs this pane had selected
  // (deleted elsewhere, or already removed by an earlier batch here), and
  // filtering here rather than syncing state in an effect means "Delete N
  // selected" can never count an id that no longer exists, with no extra
  // render pass.
  const selectedIds = useMemo(() => {
    const known = new Set(runs.map((r) => r.id))
    return new Set([...rawSelectedIds].filter((id) => known.has(id)))
  }, [rawSelectedIds, runs])

  function exitSelectMode() {
    setSelectMode(false)
    setSelectedIds(new Set())
    setBatchFailed(null)
  }

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    setSelectedIds((prev) => (prev.size === runs.length ? new Set() : new Set(runs.map((r) => r.id))))
  }

  /** Downloads the selected runs as a session file - see lib/sessionFile.ts.
   * A run's full samples are needed (max_samples=0), not just the summary
   * already in `runs`: in view mode those samples are already in hand
   * (importedSession.runs carries full RunDetail), everywhere else they're
   * fetched one GET /api/runs/{id} at a time. */
  async function handleExport() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0 || exporting) return
    const defaultTitle = `Runs from ${date}`
    const title = window.prompt('Session title', defaultTitle)
    if (title === null) return // cancelled
    setExporting(true)
    setExportError(null)
    try {
      const details: RunDetail[] = []
      for (const id of ids) {
        const fromImported = importedSession.active
          ? importedSession.runs.find((r) => r.id === id)
          : undefined
        details.push(fromImported ?? (await fetchRun(id, 0)))
      }
      downloadSessionFile(
        buildSessionFile({ title: title.trim() || defaultTitle, setup: setupMode, curves: [], runs: details }),
      )
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e))
    } finally {
      setExporting(false)
    }
  }

  async function handleBatchDelete() {
    if (readOnly.enabled || selectedIds.size === 0 || batchDeleting) return // defense in depth
    const ids = Array.from(selectedIds)
    if (
      !window.confirm(
        `Delete ${ids.length} selected run${ids.length === 1 ? '' : 's'} from ${date}? This cannot be undone.`,
      )
    ) {
      return
    }
    setBatchDeleting(true)
    setBatchFailed(null)
    try {
      const result = await deleteRunsBatch(ids)
      // Only the ones that failed stay selected - a retry then only
      // targets what's actually still there.
      setSelectedIds(new Set(result.failed.map((f) => f.id)))
      if (result.failed.length > 0) {
        setBatchFailed(result.failed)
      } else {
        exitSelectMode()
      }
      onRunsChanged()
    } catch (e) {
      // The request itself failed (network/server error), so nothing is
      // known to have been deleted - every id stays selected rather than
      // guessing which ones might have gone through.
      setBatchFailed(ids.map((id) => ({ id, error: e instanceof Error ? e.message : String(e) })))
    } finally {
      setBatchDeleting(false)
    }
  }

  const allSelected = runs.length > 0 && selectedIds.size === runs.length

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>{date}</CardTitle>
            <CardDescription>Closed-loop MPPT runs captured this day.</CardDescription>
          </div>

          {runs.length > 0 &&
            (selectMode ? (
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    aria-label="Select all"
                    className="size-4 accent-primary"
                  />
                  Select all
                </label>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleExport}
                  disabled={selectedIds.size === 0 || exporting}
                  focusableWhenDisabled
                  title={selectedIds.size === 0 ? 'Select at least one run first' : undefined}
                >
                  <Download />
                  {exporting ? 'Exporting...' : `Export ${selectedIds.size} selected`}
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleBatchDelete}
                  disabled={readOnly.enabled || selectedIds.size === 0 || batchDeleting}
                  focusableWhenDisabled
                  title={
                    readOnly.enabled
                      ? readOnlyReasonText(readOnly.reason ?? 'demo', 'Deleting')
                      : selectedIds.size === 0
                        ? 'Select at least one run first'
                        : undefined
                  }
                >
                  <Trash2 />
                  {batchDeleting ? 'Deleting...' : `Delete ${selectedIds.size} selected`}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exitSelectMode}
                  disabled={batchDeleting}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
                Select
              </Button>
            ))}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {exportError && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            Export failed: {exportError}
          </p>
        )}

        {batchFailed && batchFailed.length > 0 && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            Failed to delete {batchFailed.length} {batchFailed.length === 1 ? 'run' : 'runs'}:{' '}
            {batchFailed
              .map((f) => `"${runs.find((r) => r.id === f.id)?.label || f.id}" (${f.error})`)
              .join(', ')}
            . Still selected - try again, or Cancel to give up.
          </p>
        )}

        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs recorded for this date yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {selectMode && <TableHead className="w-8" />}
                  <TableHead>Label</TableHead>
                  <TableHead>Algorithm</TableHead>
                  <TableHead>Captured</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead className="text-right">Samples</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow
                    key={r.id}
                    onClick={() => setSelected(r)}
                    tabIndex={0}
                    role="button"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(r)
                      }
                    }}
                    className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    {selectMode && (
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(r.id)}
                          onChange={() => toggleSelected(r.id)}
                          aria-label={`Select "${r.label || 'Untitled run'}" for batch delete`}
                          className="size-4 accent-primary"
                        />
                      </TableCell>
                    )}
                    <TableCell className="font-medium">{r.label || 'Untitled run'}</TableCell>
                    <TableCell>{r.algorithm}</TableCell>
                    <TableCell>{formatCapturedAt(r.captured_at)}</TableCell>
                    <TableCell className="text-right">{formatSeconds(r.duration_s)}</TableCell>
                    <TableCell className="text-right">{r.n_samples}</TableCell>
                    <TableCell>
                      {r.curve_ref ? (
                        <span className="text-xs text-muted-foreground">curve saved</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">none</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <ProvenanceBadge source={r.source} />
                    </TableCell>
                    <TableCell>{r.aborted && <Badge variant="destructive">Aborted</Badge>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <RunPlayerDialog
        run={selected}
        curves={curves}
        onClose={() => setSelected(null)}
        onDeleted={onRunsChanged}
      />
    </Card>
  )
}
