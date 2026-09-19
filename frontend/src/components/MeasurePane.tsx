import { useEffect, useMemo, useState } from 'react'
import { CurveWorkbench } from '@/components/CurveWorkbench'
import { RunPane } from '@/components/RunPane'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCaptureMode } from '@/lib/captureMode'
import { useSetupMode } from '@/lib/setupMode'
import {
  getMeasurementKindInfo,
  type ConnectionStatus,
  type CurveRecord,
  type MeasurePrefill,
} from '@/types'

type Section = 'curve' | 'run'

/**
 * Now that the flat page's kind cards are gone, the operator picks what
 * they're about to capture here, before Start Measurement - CurveWorkbench
 * itself still only ever knows about one kind at a time. The Curve/Run
 * split above that picks between capturing a static I-V curve (unchanged)
 * and driving a live closed-loop MPPT run (RunPane) - two different
 * things the board can do, and the SPI link can only ever serve one at a
 * time (see curve_tracer_server.py's module docstring).
 */
export function MeasurePane({
  kinds,
  byKind,
  curves,
  connected,
  connectionStatus,
  onSaved,
  onRunSaved,
  prefill = null,
  onPrefillApplied,
}: {
  kinds: string[]
  byKind: Map<string, CurveRecord[]>
  /** Every saved curve, regardless of kind - RunPane's reference-curve
   * picker draws from the whole library, not just one kind's bucket. */
  curves: CurveRecord[]
  connected: boolean
  /** Raw link state, for RunPane: unlike curve capture's `connected`
   * (true for 'connected' or the server's own 'demo' status), a live run
   * needs a real board either way - see RunPane's own note on why. */
  connectionStatus: ConnectionStatus
  /** Forwarded to CurveWorkbench/SaveCurveForm - called with the kind
   * just saved under, so App.tsx's remeasure logic can tell an unrelated
   * save (a different kind) from the one it's waiting for. */
  onSaved: (kind: string) => void
  /** Refetch the run list - called once a live run has actually saved. */
  onRunSaved: () => void
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
  const [section, setSection] = useState<Section>('curve')
  const [kind, setKind] = useState<string>(() =>
    prefill && kinds.includes(prefill.kind) ? prefill.kind : (kinds[0] ?? 'baseline'),
  )
  const { mode } = useCaptureMode()
  const demo = mode === 'simulated'
  const emphasizeReplay = mode === 'firmware-replay'
  const { mode: setupMode } = useSetupMode()
  const single = setupMode === 'single'

  // Tilted needs a panel B, which Single setup doesn't have - offered for
  // capture only in Full. Filtered here rather than upstream (App.tsx's
  // seedKinds) so a curve already saved under "tilted" still counts and
  // groups normally everywhere else; this only hides it as a thing to
  // capture next.
  const capturableKinds = useMemo(
    () => (single ? kinds.filter((k) => k !== 'tilted') : kinds),
    [kinds, single],
  )

  useEffect(() => {
    if (prefill) onPrefillApplied?.()
    // Mount-only, deliberately: see the `prefill` prop's own doc comment
    // above for why this never needs to re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Switching to Single while Tilted is the selected tab would otherwise
  // leave `kind` pointing at a tab that just vanished from the row above -
  // jump to the first still-capturable kind instead. Only reacts to
  // `single` flipping, not to `kind`/`kinds` themselves, so it never fights
  // an operator's own pick the rest of the time (same reasoning as the
  // prefill effect above).
  useEffect(() => {
    if (single && kind === 'tilted') {
      setKind(capturableKinds[0] ?? kind)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [single])

  return (
    <div className="flex flex-col gap-4">
      <Tabs value={section} onValueChange={(value) => setSection(value as Section)}>
        <TabsList>
          <TabsTrigger value="curve">Capture a curve</TabsTrigger>
          <TabsTrigger value="run">Run an algorithm</TabsTrigger>
        </TabsList>
      </Tabs>

      {section === 'curve' && (
        <>
          <div>
            <p className="mb-2 text-sm text-muted-foreground">Capturing under:</p>
            <Tabs value={kind} onValueChange={(value) => setKind(value as string)}>
              <TabsList>
                {capturableKinds.map((k) => (
                  <TabsTrigger key={k} value={k}>
                    {getMeasurementKindInfo(k).title}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            {single && kinds.includes('tilted') && (
              <p className="mt-1 text-xs text-muted-foreground">
                Tilted needs panel B - unavailable in Single setup.
              </p>
            )}
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
        </>
      )}

      {section === 'run' && (
        <RunPane curves={curves} connectionStatus={connectionStatus} onRunSaved={onRunSaved} />
      )}
    </div>
  )
}
