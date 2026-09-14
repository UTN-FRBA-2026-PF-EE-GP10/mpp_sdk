import { useEffect, useState } from 'react'
import { CurveWorkbench } from '@/components/CurveWorkbench'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCaptureMode } from '@/lib/captureMode'
import { getMeasurementKindInfo, type CurveRecord, type MeasurePrefill } from '@/types'

/**
 * Now that the flat page's kind cards are gone, the operator picks what
 * they're about to capture here, before Start Measurement - CurveWorkbench
 * itself still only ever knows about one kind at a time.
 */
export function MeasurePane({
  kinds,
  byKind,
  connected,
  onSaved,
  prefill = null,
  onPrefillApplied,
}: {
  kinds: string[]
  byKind: Map<string, CurveRecord[]>
  connected: boolean
  onSaved: () => void
  /** Set by Remeasure (App.tsx's `startRemeasure`) to preselect a kind
   * tab and prefill the Save form from the curve being replaced. Read
   * once, at mount - Remeasure only ever navigates here on a fresh
   * mount (there's no Remeasure control inside Measure itself), so this
   * component never needs to react to a prefill arriving mid-life. */
  prefill?: MeasurePrefill | null
  /** Tells the caller the prefill above has been read, so it can clear
   * its own state - otherwise a later, unrelated visit to Measure would
   * silently reapply a stale remeasure's values. */
  onPrefillApplied?: () => void
}) {
  const [kind, setKind] = useState<string>(() =>
    prefill && kinds.includes(prefill.kind) ? prefill.kind : (kinds[0] ?? 'baseline'),
  )
  const { mode } = useCaptureMode()
  const demo = mode === 'simulated'
  const emphasizeReplay = mode === 'firmware-replay'

  useEffect(() => {
    if (prefill) onPrefillApplied?.()
    // Mount-only, deliberately: see the `prefill` prop's own doc comment
    // above for why this never needs to re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="mb-2 text-sm text-muted-foreground">Capturing under:</p>
        <Tabs value={kind} onValueChange={(value) => setKind(value as string)}>
          <TabsList>
            {kinds.map((k) => (
              <TabsTrigger key={k} value={k}>
                {getMeasurementKindInfo(k).title}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <CurveWorkbench
        key={kind}
        kind={kind}
        records={byKind.get(kind) ?? []}
        connected={connected}
        onSaved={onSaved}
        demo={demo}
        emphasizeReplay={emphasizeReplay}
        initialLabel={prefill && prefill.kind === kind ? prefill.label : undefined}
        initialNotes={prefill && prefill.kind === kind ? prefill.notes : undefined}
        initialPanels={prefill && prefill.kind === kind ? prefill.panels : undefined}
      />
    </div>
  )
}
