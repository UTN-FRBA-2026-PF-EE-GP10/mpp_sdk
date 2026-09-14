import { CurveChart } from '@/components/CurveChart'
import { CurveMetadata } from '@/components/CurveMetadata'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogPopup, DialogTitle } from '@/components/ui/dialog'
import { downloadCurve } from '@/lib/curveExport'
import { getMeasurementKindInfo, type CurveRecord } from '@/types'

/**
 * The one expanded view for a saved curve - opened from a dashboard pane
 * (CurveCategoryPane) or a Saved-curves table row (CurveWorkbench), so
 * there is exactly one place an operator learns to read a curve in
 * detail. `record` doubles as the open/closed flag: rendering with `null`
 * keeps the dialog mounted-but-closed instead of unmounting/remounting it
 * on every curve click.
 */
export function CurveDetailDialog({
  record,
  onClose,
}: {
  record: CurveRecord | null
  onClose: () => void
}) {
  return (
    <Dialog
      open={record !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogPopup className="max-w-2xl">
        {record && <CurveDetailContent record={record} />}
      </DialogPopup>
    </Dialog>
  )
}

function CurveDetailContent({ record }: { record: CurveRecord }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2 pr-6">
        <div>
          <DialogTitle>{record.label || 'Untitled curve'}</DialogTitle>
          <p className="text-sm text-muted-foreground">
            {getMeasurementKindInfo(record.measurement).title}
          </p>
        </div>
        <ProvenanceBadge source={record.source} />
      </div>

      <CurveChart points={record.points} heightClassName="h-80" />

      <CurveMetadata
        record={record}
        className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3"
      />

      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => downloadCurve(record, 'json')}>
          Download JSON
        </Button>
        <Button variant="outline" size="sm" onClick={() => downloadCurve(record, 'csv')}>
          Download CSV
        </Button>
      </div>
    </div>
  )
}
