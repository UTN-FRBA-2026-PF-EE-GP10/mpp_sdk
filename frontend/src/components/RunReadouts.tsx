import { useUnits } from '@/lib/units'
import type { RunSample } from '@/lib/runs'

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground tabular-nums">{value}</dd>
    </div>
  )
}

/**
 * The numbers that matter while a run plays: elapsed time, the measured
 * operating point, and the duty cycle the algorithm actually commanded.
 * Duty gets its own field rather than being folded into a tooltip - it's
 * the control variable the algorithm sets, not a derived quantity (see
 * AGENTS.md's modelling conventions), so a reader trying to judge the
 * controller's behaviour needs it in view at all times, not on hover.
 */
export function RunReadouts({ sample }: { sample: RunSample | null }) {
  const { formatCurrent, formatPower } = useUnits()

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-5">
      <Field label="t" value={sample ? `${sample.t.toFixed(2)} s` : '-'} />
      <Field label="V" value={sample ? `${sample.v.toFixed(2)} V` : '-'} />
      <Field label="I" value={sample ? formatCurrent(sample.i) : '-'} />
      <Field label="P" value={sample ? formatPower(sample.v * sample.i) : '-'} />
      <Field label="Duty" value={sample ? `${(sample.d * 100).toFixed(1)} %` : '-'} />
    </dl>
  )
}
