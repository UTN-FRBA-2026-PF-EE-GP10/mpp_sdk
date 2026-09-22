import { Download, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CurveDashboardPane } from '@/components/CurveDashboardPane'
import { CurveDetailDialog } from '@/components/CurveDetailDialog'
import { SessionScopeFilter } from '@/components/SessionScopeFilter'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { filterToSession, useCaptureSession, type SessionScope } from '@/lib/activeSession'
import { deleteCurvesBatch } from '@/lib/api'
import { buildSessionFile, downloadSessionFile, readOnlyReasonText, useReadOnly } from '@/lib/sessionFile'
import { useSetupMode } from '@/lib/setupMode'
import { getMeasurementKindInfo, type CurveRecord } from '@/types'

/**
 * One dashboard tile per curve saved under `kind`, newest first (App.tsx
 * sorts `records` before handing them here). Clicking a tile opens the
 * same expanded view (CurveDetailDialog) that a Saved-curves table row in
 * CurveWorkbench opens - one place to inspect a curve, reachable from
 * both.
 *
 * Also owns this kind's select mode: "Select" turns on a checkbox per
 * tile (CurveDashboardPane's own `selectable` prop) plus "Select all",
 * "Export N selected" (a session file - see lib/sessionFile.ts) and
 * "Delete N selected" (one POST /api/curves/delete-batch request instead
 * of N separate DELETE calls - see lib/api.ts).
 */
export function CurveCategoryPane({
  kind,
  records: allRecords,
  onDeleted,
  onRemeasure,
  remeasurePendingId = null,
}: {
  kind: string
  records: CurveRecord[]
  /** Refetch the curve list after a pane's own delete, the delete a
   * completed remeasure fires, or a batch delete here - App.tsx bumps its
   * reload token either way. Optional so this component still renders
   * standalone in tests that don't care about any of these workflows. */
  onDeleted?: () => void
  onRemeasure?: (record: CurveRecord) => void
  /** The curve id App.tsx currently has a pending remeasure for, if any
   * - passed through so that one pane can grey out its own delete/
   * remeasure controls while its replacement is in flight. */
  remeasurePendingId?: string | null
}) {
  const info = getMeasurementKindInfo(kind)
  const captureSession = useCaptureSession()
  const [scope, setScope] = useState<SessionScope>('all')
  // Everything is shown whenever no session is active, whatever `scope`
  // was last left at - the switch itself is hidden then.
  const records = useMemo(
    () => filterToSession(allRecords, scope, captureSession?.id ?? null),
    [allRecords, scope, captureSession?.id],
  )
  const filtered = captureSession !== null && scope === 'session'
  const [selected, setSelected] = useState<CurveRecord | null>(null)
  const readOnly = useReadOnly()
  const { mode: setupMode } = useSetupMode()

  const [selectMode, setSelectMode] = useState(false)
  const [rawSelectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchFailed, setBatchFailed] = useState<{ id: string; error: string }[] | null>(null)

  // Derived, not stored: a reload can drop records this pane had selected
  // (deleted elsewhere, or already removed by an earlier batch here), and
  // filtering here rather than syncing state in an effect means "Delete N
  // selected" can never count an id that no longer exists, with no extra
  // render pass.
  // A curve with a remeasure pending is promised to stay until its
  // replacement saves (see App.tsx), so it can never be batch-selected.
  const selectableIds = useMemo(
    () => records.map((r) => r.id).filter((id) => id !== remeasurePendingId),
    [records, remeasurePendingId],
  )
  const selectedIds = useMemo(() => {
    const known = new Set(selectableIds)
    return new Set([...rawSelectedIds].filter((id) => known.has(id)))
  }, [rawSelectedIds, selectableIds])

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
    setSelectedIds(
      selectedIds.size === selectableIds.length ? new Set() : new Set(selectableIds),
    )
  }

  /** Downloads the selected curves as a session file - see lib/sessionFile.ts.
   * No fetch needed: `records` already carries every point (GET
   * /api/curves serves full records), in either live or view mode. */
  function handleExport() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    const chosen = records.filter((r) => ids.includes(r.id))
    const defaultTitle = `${info.title} curves`
    const title = window.prompt('Session title', defaultTitle)
    if (title === null) return // cancelled
    downloadSessionFile(
      buildSessionFile({ title: title.trim() || defaultTitle, setup: setupMode, curves: chosen, runs: [] }),
    )
  }

  async function handleBatchDelete() {
    if (readOnly.enabled || selectedIds.size === 0 || batchDeleting) return // defense in depth
    const ids = Array.from(selectedIds)
    if (
      !window.confirm(
        `Delete ${ids.length} selected curve${ids.length === 1 ? '' : 's'} under "${info.title}"? This cannot be undone.`,
      )
    ) {
      return
    }
    setBatchDeleting(true)
    setBatchFailed(null)
    try {
      const result = await deleteCurvesBatch(ids)
      // Only the ones that failed stay selected - a retry then only
      // targets what's actually still there.
      setSelectedIds(new Set(result.failed.map((f) => f.id)))
      if (result.failed.length > 0) {
        setBatchFailed(result.failed)
      } else {
        exitSelectMode()
      }
      onDeleted?.()
    } catch (e) {
      // The request itself failed (network/server error), so nothing is
      // known to have been deleted - every id stays selected rather than
      // guessing which ones might have gone through.
      setBatchFailed(ids.map((id) => ({ id, error: e instanceof Error ? e.message : String(e) })))
    } finally {
      setBatchDeleting(false)
    }
  }

  const allSelected = selectableIds.length > 0 && selectedIds.size === selectableIds.length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{info.title}</h2>
          <p className="text-sm text-muted-foreground">{info.description}</p>
          <div className="mt-2">
            <SessionScopeFilter scope={scope} onScopeChange={setScope} />
          </div>
        </div>

        {records.length > 0 &&
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
                disabled={selectedIds.size === 0}
                focusableWhenDisabled
                title={selectedIds.size === 0 ? 'Select at least one curve first' : undefined}
              >
                <Download />
                {`Export ${selectedIds.size} selected`}
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
                      ? 'Select at least one curve first'
                      : undefined
                }
              >
                <Trash2 />
                {batchDeleting ? 'Deleting...' : `Delete ${selectedIds.size} selected`}
              </Button>
              <Button variant="outline" size="sm" onClick={exitSelectMode} disabled={batchDeleting}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
              Select
            </Button>
          ))}
      </div>

      {batchFailed && batchFailed.length > 0 && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Failed to delete {batchFailed.length} {batchFailed.length === 1 ? 'curve' : 'curves'}:{' '}
          {batchFailed
            .map((f) => `"${records.find((r) => r.id === f.id)?.label || f.id}" (${f.error})`)
            .join(', ')}
          . Still selected - try again, or Cancel to give up.
        </p>
      )}

      {records.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Nothing saved yet</CardTitle>
            <CardDescription>
              {filtered
                ? `No curves under \u201c${kind}\u201d were captured in this session. Switch to Everything to see the rest.`
                : `No curves saved under \u201c${kind}\u201d yet. Capture one from Measure.`}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {records.map((record) => (
            <CurveDashboardPane
              key={record.path}
              record={record}
              onOpen={() => setSelected(record)}
              onDeleted={onDeleted ?? (() => {})}
              onRemeasure={onRemeasure ?? (() => {})}
              remeasurePending={remeasurePendingId === record.id}
              selectable={selectMode}
              selected={selectedIds.has(record.id)}
              onToggleSelected={() => toggleSelected(record.id)}
            />
          ))}
        </div>
      )}

      <CurveDetailDialog record={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
