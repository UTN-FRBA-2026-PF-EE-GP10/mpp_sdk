import { formatCapturedAt } from '@/lib/format'
import { useUnits } from '@/lib/units'
import type { CurveRecord } from '@/types'

function panelTilt(record: CurveRecord, id: string): string {
  const panel = record.panels.find((p) => p.id === id)
  return panel ? `${panel.tilt_deg}°` : '-'
}

function Field({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-full' : undefined}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{value}</dd>
    </div>
  )
}

/**
 * The fields a curve pane and its expanded view both show below the plot
 * (label is shown separately, as the pane/dialog title). One definition
 * so a units fix or an added field never needs to be kept in sync between
 * a compact and an expanded copy.
 */
export function CurveMetadata({ record, className }: { record: CurveRecord; className?: string }) {
  const { formatCurrent, formatPower } = useUnits()

  return (
    <dl className={className}>
      <Field label="Captured" value={formatCapturedAt(record.captured_at)} />
      <Field label="Panel A" value={panelTilt(record, 'A')} />
      <Field label="Panel B" value={panelTilt(record, 'B')} />
      <Field label="Voc" value={`${record.voc.toFixed(2)} V`} />
      <Field label="Isc" value={formatCurrent(record.isc)} />
      <Field label="P_mpp" value={formatPower(record.p_mpp)} />
      <Field label="Points" value={String(record.n_points)} />
      {record.notes && <Field label="Notes" value={record.notes} wide />}
    </dl>
  )
}
