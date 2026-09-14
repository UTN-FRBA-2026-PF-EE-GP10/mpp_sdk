import { useState } from 'react'
import { CurveDashboardPane } from '@/components/CurveDashboardPane'
import { CurveDetailDialog } from '@/components/CurveDetailDialog'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getMeasurementKindInfo, type CurveRecord } from '@/types'

/**
 * One dashboard tile per curve saved under `kind`, newest first (App.tsx
 * sorts `records` before handing them here). Clicking a tile opens the
 * same expanded view (CurveDetailDialog) that a Saved-curves table row in
 * CurveWorkbench opens - one place to inspect a curve, reachable from
 * both.
 */
export function CurveCategoryPane({
  kind,
  records,
  onDeleted,
  onRemeasure,
  remeasurePendingId = null,
}: {
  kind: string
  records: CurveRecord[]
  /** Refetch the curve list after a pane's own delete, or the delete a
   * completed remeasure fires - App.tsx bumps its reload token either
   * way. Optional so this component still renders standalone in tests
   * that don't care about either workflow. */
  onDeleted?: () => void
  onRemeasure?: (record: CurveRecord) => void
  /** The curve id App.tsx currently has a pending remeasure for, if any
   * - passed through so that one pane can grey out its own delete/
   * remeasure controls while its replacement is in flight. */
  remeasurePendingId?: string | null
}) {
  const info = getMeasurementKindInfo(kind)
  const [selected, setSelected] = useState<CurveRecord | null>(null)

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{info.title}</h2>
        <p className="text-sm text-muted-foreground">{info.description}</p>
      </div>

      {records.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Nothing saved yet</CardTitle>
            <CardDescription>
              No curves saved under &ldquo;{kind}&rdquo; yet. Capture one from Measure.
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
            />
          ))}
        </div>
      )}

      <CurveDetailDialog record={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
