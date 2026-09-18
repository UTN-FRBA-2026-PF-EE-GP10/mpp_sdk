import { Download, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { CurveChart } from '@/components/CurveChart'
import { CurveMetadata } from '@/components/CurveMetadata'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { deleteCurve } from '@/lib/api'
import { downloadCurve } from '@/lib/curveExport'
import { formatCapturedAt } from '@/lib/format'
import { useSandbox } from '@/lib/sandbox'
import type { CurveRecord } from '@/types'

/**
 * One dashboard tile per saved curve. The whole card is the click/zoom
 * trigger for CurveDetailDialog; the delete/save/remeasure controls sit in
 * a corner overlay that stays quiet until hovered or focused, so a page of
 * panes doesn't read as a wall of buttons. Every control there stops event
 * propagation - without it, a click or an Enter/Space keypress on a nested
 * button would bubble up and also fire the card's own onOpen.
 */
export function CurveDashboardPane({
  record,
  onOpen,
  onDeleted,
  onRemeasure,
  remeasurePending = false,
  selectable = false,
  selected = false,
  onToggleSelected,
}: {
  record: CurveRecord
  onOpen: () => void
  /** Refetch the curve list - called once a delete (this pane's own, or
   * the one a completed remeasure fires) has actually removed a file. */
  onDeleted: () => void
  /** Starts the remeasure workflow for this curve - confirming is this
   * component's job, everything after (navigating to Measure, prefilling
   * the form, holding the pending delete) belongs to the caller, since it
   * spans well outside this one pane's lifetime. */
  onRemeasure: (record: CurveRecord) => void
  /** True while this exact curve is the subject of an already-pending
   * remeasure elsewhere - blocks starting a second one, or deleting the
   * curve a pending replacement still refers to. */
  remeasurePending?: boolean
  /** Batch-delete selection mode, driven by CurveCategoryPane - shows the
   * checkbox below and leaves the single-pane delete/remeasure controls
   * untouched, since selecting a curve for a batch is independent of
   * either. */
  selectable?: boolean
  selected?: boolean
  onToggleSelected?: () => void
}) {
  const sandbox = useSandbox()
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const label = record.label || 'Untitled curve'
  const deleteDisabled = sandbox.enabled || remeasurePending || deleting
  const remeasureDisabled = sandbox.enabled || remeasurePending

  async function handleDelete() {
    if (deleteDisabled) return // defense in depth - the button is disabled anyway
    if (
      !window.confirm(
        `Delete curve "${label}" (captured ${formatCapturedAt(record.captured_at)})? This cannot be undone.`,
      )
    ) {
      return
    }
    setDeleting(true)
    setActionError(null)
    try {
      await deleteCurve(record.id)
      onDeleted()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
      setDeleting(false)
    }
  }

  function handleRemeasure() {
    if (remeasureDisabled) return // defense in depth - the button is disabled anyway
    if (
      !window.confirm(
        `Remeasure "${label}"? You'll capture a replacement with the same label, notes, and panel angles. The old curve is only removed after the replacement is saved.`,
      )
    ) {
      return
    }
    onRemeasure(record)
  }

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen()
        }
      }}
      className={
        'group/card relative cursor-pointer transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none' +
        (selected ? ' ring-2 ring-primary' : '')
      }
    >
      {selectable && (
        // Its own corner, away from the save/remeasure/delete overlay -
        // both can be visible at once (selection mode doesn't disable
        // per-pane actions), so they must not overlap.
        <label
          className="absolute top-2 left-2 z-10 flex items-center rounded-md bg-card/80 p-1 backdrop-blur-sm"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected?.()}
            aria-label={`Select "${label}" for batch delete`}
            className="size-4 accent-primary"
          />
        </label>
      )}
      <CardHeader>
        <div
          className={
            'flex flex-wrap items-start justify-between gap-2' + (selectable ? ' pl-6' : '')
          }
        >
          <CardTitle className="truncate">{label}</CardTitle>
          <ProvenanceBadge source={record.source} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <CurveChart points={record.points} heightClassName="h-40" />
        <CurveMetadata
          record={record}
          className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-3"
        />
        {actionError && (
          <p className="text-xs text-destructive">Delete failed: {actionError}</p>
        )}
      </CardContent>

      {/* Quiet at rest, revealed on hover or when a control inside gets
          keyboard focus - `group-focus-within/card` covers Tab landing
          directly on a button without the pointer ever hovering the
          card. */}
      <div
        className="absolute right-2 bottom-2 flex items-center gap-1 rounded-md bg-card/80 p-0.5 opacity-0 backdrop-blur-sm transition-opacity group-hover/card:opacity-100 group-focus-within/card:opacity-100"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="ghost" size="icon-sm" title="Save (download)">
                <Download />
              </Button>
            }
          />
          <DropdownMenuContent>
            <DropdownMenuItem onClick={() => downloadCurve(record, 'json')}>
              Download JSON
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => downloadCurve(record, 'csv')}>
              Download CSV
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleRemeasure}
          disabled={remeasureDisabled}
          // Icon-only, and the `title` below is its only explanation - a
          // plain `disabled` becomes a native attribute with
          // pointer-events: none, which means the element can never
          // receive hover and the title tooltip can never appear.
          // focusableWhenDisabled keeps it hoverable/focusable (base-ui
          // still blocks the click itself) so the reason stays reachable.
          focusableWhenDisabled
          title={
            sandbox.enabled
              ? 'Remeasure needs real hardware - unavailable in demo mode'
              : remeasurePending
                ? 'A replacement capture is already pending for this curve'
                : 'Capture a replacement, then remove this curve'
          }
        >
          <RefreshCw />
        </Button>

        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleDelete}
          disabled={deleteDisabled}
          focusableWhenDisabled
          title={
            sandbox.enabled
              ? 'Deleting is unavailable in demo mode'
              : remeasurePending
                ? 'A replacement capture is already pending for this curve'
                : deleting
                  ? 'Deleting...'
                  : 'Delete this curve'
          }
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          <Trash2 />
        </Button>
      </div>
    </Card>
  )
}
