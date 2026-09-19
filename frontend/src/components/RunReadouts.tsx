import { useUnits } from '@/lib/units'
import type { RunSample } from '@/lib/runs'
import type { CurvePoint } from '@/types'

/** Exported for RunPane's live readouts row, which needs the same
 * label/value layout plus a field (`vout`) that has no place on a
 * `RunSample` - see runs.ts's LiveRunState for why. */
export function Field({ label, value }: { label: string; value: string }) {
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
export function RunReadouts({
  sample,
  mppTh = null,
}: {
  sample: RunSample | null
  /** The reference curve's maximum-power point, when the run has one. */
  mppTh?: CurvePoint | null
}) {
  const { formatCurrent, formatPower } = useUnits()
  const pTh = mppTh ? mppTh.v * mppTh.i : 0
  // P / MPP_th is the tracking efficiency at this frame - the number that
  // answers "how close to the peak is it right now".
  const ratio = sample && pTh > 0 ? (sample.v * sample.i) / pTh : null

  return (
    <div className="flex flex-col gap-1.5">
      <dl
        className={
          'grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm ' +
          (mppTh ? 'sm:grid-cols-6' : 'sm:grid-cols-5')
        }
      >
        <Field label="t" value={sample ? `${sample.t.toFixed(2)} s` : '-'} />
        <Field label="V" value={sample ? `${sample.v.toFixed(2)} V` : '-'} />
        <Field label="I" value={sample ? formatCurrent(sample.i) : '-'} />
        <Field label="P" value={sample ? formatPower(sample.v * sample.i) : '-'} />
        <Field label="Duty" value={sample ? `${(sample.d * 100).toFixed(1)} %` : '-'} />
        {mppTh && (
          <Field
            label="P / MPP_th"
            value={ratio !== null ? `${(ratio * 100).toFixed(1)} %` : '-'}
          />
        )}
      </dl>
      {mppTh && (
        <p className="text-xs text-muted-foreground tabular-nums">
          MPP_th (peak of the reference curve): {mppTh.v.toFixed(2)} V,{' '}
          {formatCurrent(mppTh.i)}, {formatPower(pTh)}
        </p>
      )}
    </div>
  )
}
