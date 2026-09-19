import { useEffect, useState } from 'react'
import { CurveDetailDialog } from '@/components/CurveDetailDialog'
import { LiveChart } from '@/components/LiveChart'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useDemoCapture } from '@/hooks/useDemoCapture'
import { useLiveSweep } from '@/hooks/useLiveSweep'
import { saveCurve } from '@/lib/api'
import { formatCapturedAt } from '@/lib/format'
import { useSetupMode } from '@/lib/setupMode'
import { useUnits } from '@/lib/units'
import {
  getMeasurementKindInfo,
  PANEL_A_TILT_DEG,
  PANEL_B_TILT_OPTIONS_DEG,
  type CurveRecord,
  type PanelSetup,
} from '@/types'

const DEFAULT_PANELS: PanelSetup[] = [
  { id: 'A', tilt_deg: PANEL_A_TILT_DEG },
  { id: 'B', tilt_deg: 90 },
]

// Single setup: the Luxen LN-10P session - one panel, no B to tilt.
const SINGLE_PANELS: PanelSetup[] = [{ id: 'A', tilt_deg: PANEL_A_TILT_DEG }]

function SaveCurveForm({
  kind,
  hasCapture,
  demo,
  onSaved,
  initialLabel,
  initialNotes,
  initialPanels,
}: {
  kind: string
  hasCapture: boolean
  demo: boolean
  /** Called with the kind just saved under - lets a remeasure in progress
   * (App.tsx's `handleCurveSaved`) tell "this is the save it was waiting
   * for" from "an unrelated save happened elsewhere in Measure". */
  onSaved: (kind: string) => void
  /** Remeasure's prefill (see App.tsx's `startRemeasure`) - read once as
   * this form's starting state, same as any other initial-state prop:
   * later changes to these don't reset what the operator has typed. */
  initialLabel?: string
  initialNotes?: string
  initialPanels?: PanelSetup[]
}) {
  const { mode: setupMode } = useSetupMode()
  const single = setupMode === 'single'
  // `initialPanels` is a "read once" remeasure prefill, same contract as
  // `initialLabel`/`initialNotes` (see their doc comments): MeasurePane
  // clears it from its parent shortly after mount (`onPrefillApplied`),
  // so the *prop* goes back to undefined a moment later even mid-remeasure.
  // Capturing it once here, instead of reading the live prop on every
  // render, is what lets a two-panel remeasure keep showing panel B for
  // its whole lifetime regardless of the current global setup.
  const [isRemeasure] = useState(() => initialPanels !== undefined)
  const [remeasureHasPanelB] = useState(() => (initialPanels?.length ?? 0) > 1)
  const showPanelB = isRemeasure ? remeasureHasPanelB : !single

  const [label, setLabel] = useState(initialLabel ?? '')
  const [notes, setNotes] = useState(initialNotes ?? '')
  const [panels, setPanels] = useState<PanelSetup[]>(
    initialPanels ?? (single ? SINGLE_PANELS : DEFAULT_PANELS),
  )
  const [status, setStatus] = useState<string>('')
  const [saving, setSaving] = useState(false)

  // Only for a fresh capture (no remeasure prefill): flipping the global
  // setup while this form is open must not leave a stale panel B in state
  // once the field hides - otherwise a Single-mode save could still send
  // two panels. A remeasure's own panel count is fixed at mount and never
  // touched here.
  useEffect(() => {
    if (isRemeasure) return
    setPanels(single ? SINGLE_PANELS : DEFAULT_PANELS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [single])

  function updatePanelBTilt(tilt_deg: number) {
    setPanels((prev) => prev.map((p) => (p.id === 'B' ? { ...p, tilt_deg } : p)))
  }

  async function handleSave() {
    if (demo) return // defense in depth - the button is disabled anyway
    setSaving(true)
    setStatus('')
    try {
      const result = await saveCurve({ label, measurement: kind, panels, notes })
      setStatus(`saved: ${result.path}`)
      setLabel('')
      setNotes('')
      onSaved(kind)
    } catch (e) {
      setStatus(`save failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap gap-3">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="label, e.g. 'both flat, midday sun'"
          className="min-w-[220px] flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm"
        />
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="notes (optional)"
          className="min-w-[160px] flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">Panel A: fixed at 90° (reference)</span>
        {showPanelB && (
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Panel B tilt
            <select
              value={panels.find((p) => p.id === 'B')?.tilt_deg ?? 90}
              onChange={(e) => updatePanelBTilt(Number(e.target.value))}
              className="rounded-md border bg-transparent px-2 py-1 text-sm"
            >
              {PANEL_B_TILT_OPTIONS_DEG.map((deg) => (
                <option key={deg} value={deg}>
                  {deg}°
                </option>
              ))}
            </select>
          </label>
        )}
        <Button
          size="sm"
          onClick={handleSave}
          disabled={demo || !hasCapture || saving || !label.trim()}
          // See CurveDashboardPane's note - keeps the demo-mode `title`
          // reachable by hover/focus instead of native disabled's
          // pointer-events: none swallowing both.
          focusableWhenDisabled
          title={demo ? 'Saving is unavailable in demo mode - a replay must not enter your real curve library' : undefined}
          className="ml-auto"
        >
          {saving ? 'Saving...' : 'Save curve'}
        </Button>
      </div>
      {showPanelB ? (
        <p className="text-xs text-muted-foreground">
          90° faces the lamp squarely (both panels matching = baseline); lower angles tilt panel B
          right, away from the light.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Single setup: one panel (A), fixed at 90° facing the lamp squarely.
        </p>
      )}
      {isRemeasure && remeasureHasPanelB && single && (
        <p className="text-xs text-muted-foreground">
          This curve has two panels - the replacement keeps both, even though setup is Single.
        </p>
      )}
      {demo && (
        <p className="text-xs text-muted-foreground">
          Saving is unavailable in demo mode - a replay must not enter your real curve library.
        </p>
      )}
      {status && <p className="text-xs text-muted-foreground">{status}</p>}
    </div>
  )
}

export function CurveWorkbench({
  kind,
  records,
  connected,
  onSaved,
  demo = false,
  emphasizeReplay = false,
  initialLabel,
  initialNotes,
  initialPanels,
}: {
  kind: string
  records: CurveRecord[]
  connected: boolean
  /** Forwarded to SaveCurveForm - see its own doc comment. */
  onSaved: (kind: string) => void
  /** CaptureMode 'simulated' (see lib/captureMode.ts): the two "Demo
   * curve" buttons replay a bundled fixture locally instead of over SPI;
   * Start Measurement, Release Relay, and Save curve are hardware/write
   * actions with no local equivalent and stay disabled. */
  demo?: boolean
  /** CaptureMode 'firmware-replay' ("Demo with PICO"): everything still
   * works exactly as it does in 'hardware' mode (both need `connected`),
   * this only swaps which button row reads as the primary action - real
   * SPI either way, never set alongside `demo`. */
  emphasizeReplay?: boolean
  /** Remeasure's prefill for the Save form - forwarded straight through
   * to SaveCurveForm. See MeasurePane, which only supplies these when
   * this workbench's `kind` matches the prefill's. */
  initialLabel?: string
  initialNotes?: string
  initialPanels?: PanelSetup[]
}) {
  const info = getMeasurementKindInfo(kind)
  const { formatCurrent, formatPower } = useUnits()
  // The replay buttons belong to the two demo modes only - see the note
  // where they are rendered.
  const showDemoCurveButtons = demo || emphasizeReplay
  // Both hooks are always called (rules of hooks) - useLiveSweep is simply
  // told not to poll while `demo` is on, so switching modes can never
  // leave a stray `/api/data` poll running for the capture pane.
  const live = useLiveSweep(!demo)
  const demoCapture = useDemoCapture()
  const { partial, points, active, commandError, demoSource, start, startDemo, releaseRelay } =
    demo ? demoCapture : live
  // Deliberately excludes `active`: POST /api/save-curve persists the
  // cache's last *completed* sweep (see curve_tracer_server.py's
  // post_save_curve), not whatever `partial` is currently drawing.
  // Allowing Save mid-sweep would silently save the previous sweep's
  // points under the label meant for the one still in progress.
  const hasCapture = !active && points.length > 0
  const [selected, setSelected] = useState<CurveRecord | null>(null)
  // Demo-curve replays run regardless of `connected` (they're local), but
  // Start Measurement/Release Relay never fire in demo mode either way.
  const demoButtonsDisabled = active || (!demo && !connected)

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{info.title}</CardTitle>
            <p className="text-sm text-muted-foreground">{info.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant={emphasizeReplay ? 'outline' : 'default'}
              onClick={start}
              disabled={demo || !connected || active}
              focusableWhenDisabled
              title={demo ? 'Start Measurement needs real hardware - unavailable in demo mode' : undefined}
            >
              {active ? 'Measuring...' : 'Start Measurement'}
            </Button>
            {/* Only in the two demo modes. Off the board they replay a
                curve stored in the firmware over the real SPI link; in
                demo mode they replay the matching bundled fixture locally
                (see useDemoCapture) - same buttons, same pacing, no SPI,
                no relay. In 'hardware' mode they are noise: the point
                there is measuring a real panel, and a replay button next
                to Start Measurement only invites a mis-click that
                overwrites a live capture. */}
            {showDemoCurveButtons && (
              <>
                <Button
                  variant={emphasizeReplay ? 'default' : 'secondary'}
                  onClick={() => startDemo(false)}
                  disabled={demoButtonsDisabled}
                >
                  Demo curve (dim)
                </Button>
                <Button
                  variant={emphasizeReplay ? 'default' : 'secondary'}
                  onClick={() => startDemo(true)}
                  disabled={demoButtonsDisabled}
                >
                  Demo curve (bright)
                </Button>
              </>
            )}
            <Button
              variant="outline"
              onClick={releaseRelay}
              disabled={demo || !connected}
              focusableWhenDisabled
              title={demo ? 'Release Relay needs real hardware - unavailable in demo mode' : undefined}
            >
              Release Relay
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {demo && (
          <p className="rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-700 dark:text-violet-300">
            Demo mode: the Demo curve buttons replay a bundled sample locally. Start Measurement,
            Release Relay, and Save curve talk to real hardware or write to your library, so they
            stay off.
          </p>
        )}
        {emphasizeReplay && (
          <p className="rounded-md border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-700 dark:text-indigo-300">
            Demo with PICO: the Demo curve buttons are the point here - real SPI, a curve already
            stored in the firmware, not measured this session. Start Measurement and Save curve
            still work normally.
          </p>
        )}
        {commandError && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {commandError}
          </p>
        )}

        <div>
          <LiveChart partial={partial} points={points} />
          <p className="mt-1 text-center text-xs text-muted-foreground">
            {active
              ? `capturing... ${partial.length} point${partial.length === 1 ? '' : 's'}`
              : points.length
                ? `last capture: ${points.length} points${demoSource ? ' (replayed from firmware, not measured)' : ''}`
                : 'no curve yet - press Start Measurement'}
          </p>
        </div>

        <SaveCurveForm
          kind={kind}
          hasCapture={hasCapture}
          demo={demo}
          onSaved={onSaved}
          initialLabel={initialLabel}
          initialNotes={initialNotes}
          initialPanels={initialPanels}
        />

        <Separator />

        <div>
          <h3 className="mb-2 text-sm font-medium text-foreground">
            Saved curves ({records.length})
          </h3>
          {records.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing saved under &ldquo;{kind}&rdquo; yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Captured</TableHead>
                    <TableHead>Panels</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Voc</TableHead>
                    <TableHead className="text-right">Isc</TableHead>
                    <TableHead className="text-right">P_mpp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {records.map((r) => (
                    <TableRow
                      key={r.path}
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
                      <TableCell className="font-medium">{r.label}</TableCell>
                      <TableCell>{formatCapturedAt(r.captured_at)}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {r.panels.map((p) => (
                            <Badge key={p.id} variant="outline">
                              {p.id}: {p.tilt_deg}°
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <ProvenanceBadge source={r.source} />
                      </TableCell>
                      <TableCell className="text-right">{r.voc.toFixed(2)} V</TableCell>
                      <TableCell className="text-right">{formatCurrent(r.isc)}</TableCell>
                      <TableCell className="text-right">{formatPower(r.p_mpp)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </CardContent>

      <CurveDetailDialog record={selected} onClose={() => setSelected(null)} />
    </Card>
  )
}
