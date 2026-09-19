import { useEffect, useRef, useState } from 'react'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { Field } from '@/components/RunReadouts'
import { RunChart } from '@/components/RunChart'
import { RunPlayerDialog } from '@/components/RunPlayerDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useLiveRun } from '@/hooks/useLiveRun'
import { fetchRunConfig, fetchRuns, type RunConfig } from '@/lib/api'
import type { StartRunInput } from '@/lib/api'
import { formatCapturedAt } from '@/lib/format'
import { abortReasonMessage } from '@/lib/liveRun'
import { findCurveForRun, referenceCurveMessage } from '@/lib/runPlayback'
import { useSandbox } from '@/lib/sandbox'
import { useUnits } from '@/lib/units'
import type { LiveRunState, RunSummary } from '@/lib/runs'
import type { ConnectionStatus, CurveRecord } from '@/types'

// A stable empty array for "no reference curve" - see RunPlayerDialog's
// NO_POINTS for why this matters to chart.js's memoised data.
const NO_POINTS: CurveRecord['points'] = []

/**
 * Measure's other half, alongside CurveWorkbench: drives a live
 * closed-loop MPPT run on the real converter and watches it happen.
 * Reuses RunChart/RunPlayerDialog - the run player's own machinery for
 * drawing a static reference curve with a moving operating point - rather
 * than a second implementation; the only difference here is that the
 * data arrives from polling GET /api/runs/live instead of a saved file.
 */
export function RunPane({
  curves,
  connectionStatus,
  onRunSaved,
}: {
  curves: CurveRecord[]
  connectionStatus: ConnectionStatus
  onRunSaved: () => void
}) {
  const sandbox = useSandbox()
  const [runConfig, setRunConfig] = useState<RunConfig | null>(null)
  const [algorithmsError, setAlgorithmsError] = useState<string | null>(null)
  const { phase, live, starting, startError, stopping, stopError, start, stop, reset } =
    useLiveRun()
  const [openRun, setOpenRun] = useState<RunSummary | null>(null)
  const [openRunError, setOpenRunError] = useState<string | null>(null)
  const lastSavedIdRef = useRef<string | null>(null)

  // In demo mode the run that can be started is a simulated one - it
  // needs no board, so sandbox mode does not block it the way it blocks
  // everything else here (see RunSetupForm/handleStart, which sends
  // `simulated: true` and skips the hardware-run confirmation). Outside
  // demo mode a run still only ever drives the real converter, and still
  // needs a live link for that - connectionStatus 'demo' does not count
  // as available here the way isLiveConnection treats it for
  // CurveWorkbench, since there is no board standing in for a real one.
  const disabledReason =
    !sandbox.enabled && connectionStatus !== 'connected'
      ? 'Starting a run needs a live link to the board'
      : null
  const canStart = disabledReason === null

  useEffect(() => {
    // GET /api/run-config needs the server either way - even a simulated
    // run in demo mode is Python running server-side (see frontend/
    // README.md's demo-mode note), so this fetch is not gated on sandbox
    // the way fetchCurves/fetchRuns/fetchMeasurementKinds are in App.tsx.
    fetchRunConfig()
      .then(setRunConfig)
      .catch((e) => setAlgorithmsError(e instanceof Error ? e.message : String(e)))
  }, [])

  // Refreshes the sidebar's run list (App.tsx's reloadToken) the moment a
  // run is actually saved - keyed on the id itself, not `phase`, so this
  // fires exactly once per run even if a later poll re-delivers the same
  // "done" snapshot.
  useEffect(() => {
    if (live?.saved_run_id && live.saved_run_id !== lastSavedIdRef.current) {
      lastSavedIdRef.current = live.saved_run_id
      onRunSaved()
    }
  }, [live?.saved_run_id, onRunSaved])

  async function handleOpenInPlayer() {
    if (!live?.saved_run_id) return
    setOpenRunError(null)
    try {
      const all = await fetchRuns()
      const found = all.find((r) => r.id === live.saved_run_id)
      if (!found) {
        setOpenRunError('Saved, but not yet visible in the run library - try again shortly.')
        return
      }
      setOpenRun(found)
    } catch (e) {
      setOpenRunError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live MPPT run</CardTitle>
        <p className="text-sm text-muted-foreground">
          {sandbox.enabled
            ? 'Drive a simulated SEPIC converter with a chosen algorithm and watch it track the maximum power point as it happens - no board involved.'
            : 'Drive the real SEPIC converter with a chosen algorithm and watch it track the maximum power point as it happens.'}
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {sandbox.enabled && (
          <p className="rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-700 dark:text-violet-300">
            Demo mode: starting a run here drives a simulated converter, not the real one - the
            algorithm hunts the maximum power point of the chosen demo curve, or a built-in
            reference panel. Nothing physical happens.
          </p>
        )}
        {!sandbox.enabled && connectionStatus !== 'connected' && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            No live link to the board right now - a run needs real hardware to drive, so starting
            one stays off until the link is up.
          </p>
        )}
        {algorithmsError && (
          <p className="text-sm text-destructive">
            Failed to load the algorithm list: {algorithmsError}
          </p>
        )}

        {phase === 'idle' && (
          <RunSetupForm
            config={runConfig}
            curves={curves}
            canStart={canStart}
            disabledReason={disabledReason}
            simulated={sandbox.enabled}
            starting={starting}
            startError={startError}
            onStart={start}
          />
        )}

        {phase !== 'idle' && !live && (
          <p className="text-sm text-muted-foreground">Starting the run...</p>
        )}

        {phase !== 'idle' && live && (
          <RunMonitor
            phase={phase}
            live={live}
            curves={curves}
            stopping={stopping}
            stopError={stopError}
            onStop={stop}
            onReset={reset}
            onOpenPlayer={handleOpenInPlayer}
            openRunError={openRunError}
          />
        )}
      </CardContent>

      <RunPlayerDialog
        run={openRun}
        curves={curves}
        onClose={() => setOpenRun(null)}
        onDeleted={onRunSaved}
        // The preview of the run just watched keeps the grey curve the
        // live view drew, even when the saved run cannot name it.
        fallbackReferencePoints={
          openRun !== null && openRun.id === live?.saved_run_id
            ? live.reference_points
            : undefined
        }
      />
    </Card>
  )
}

function RunSetupForm({
  config,
  curves,
  canStart,
  disabledReason,
  simulated,
  starting,
  startError,
  onStart,
}: {
  config: RunConfig | null
  curves: CurveRecord[]
  canStart: boolean
  disabledReason: string | null
  /** Demo mode: the run this form starts drives a `SimulatedSource`, not
   * the real converter - see RunPane. Skips the hardware-run confirmation.
   * `curves` in demo mode is the bundled fixture list (App.tsx's
   * DEMO_CURVES), which the server's curve library does not have, so the
   * chosen curve is sent as `curve_points` instead of `curve_ref`. */
  simulated: boolean
  starting: boolean
  startError: string | null
  onStart: (input: StartRunInput) => void
}) {
  const [algorithm, setAlgorithm] = useState('')
  const [curveRef, setCurveRef] = useState('')
  const [durationInput, setDurationInput] = useState('')
  // Not cosmetic: the local trackers hill-climb from this seed, so on a
  // multi-peak curve it decides which maximum the run settles on.
  const [initialDuty, setInitialDuty] = useState<number | null>(null)
  // Seeded from the server's own defaults once they arrive, so the form
  // never shows a bound the server would not actually enforce.
  const [vMax, setVMax] = useState<number | null>(null)
  const [iMax, setIMax] = useState<number | null>(null)
  const [vOutMax, setVOutMax] = useState<number | null>(null)

  const algorithms = config?.algorithms ?? []

  // Toggling demo mode swaps `curves` for a different list; a pick from
  // the old one must not linger as a value no option matches.
  useEffect(() => {
    if (curveRef !== '' && !curves.some((c) => c.id === curveRef)) setCurveRef('')
  }, [curves, curveRef])

  // The config arrives asynchronously (GET /api/run-config); once it does,
  // default the picker to the first algorithm and seed the safety bounds
  // from the server's own values rather than leaving placeholders.
  useEffect(() => {
    if (config === null) return
    if (config.algorithms.length > 0 && !config.algorithms.includes(algorithm)) {
      setAlgorithm(config.algorithms[0])
    }
    setInitialDuty((d) => d ?? config.defaultInitialDuty)
    setVMax((v) => v ?? config.defaultVMax)
    setVOutMax((v) => v ?? config.defaultVOutMax)
    setIMax((i) => i ?? config.defaultIMax)
    // Only re-run when the fetched roster changes - re-selecting on every
    // `algorithm` change would fight the operator's own picks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config])

  function handleStart() {
    if (!canStart || starting || !algorithm) return
    const trimmed = durationInput.trim()
    const duration = trimmed === '' ? undefined : Number(trimmed)
    if (!simulated) {
      const durationText =
        duration === undefined
          ? `${config?.defaultDurationS ?? '...'}s`
          : `${duration}s`
      // This drives a real power converter against a real panel - the same
      // bar as CurveDashboardPane's delete/remeasure confirmations, for a
      // higher-stakes action. A simulated run skips this: nothing physical
      // happens, so there is nothing to confirm.
      if (
        !window.confirm(
          `Start a live "${algorithm}" run (${durationText})? This drives the real converter.`,
        )
      ) {
        return
      }
    }
    const chosen = curves.find((c) => c.id === curveRef)
    onStart({
      algorithm,
      duration_s: duration,
      initial_duty: initialDuty ?? config?.defaultInitialDuty,
      v_max: vMax ?? config?.defaultVMax ?? 0,
      i_max: iMax ?? config?.defaultIMax ?? 0,
      v_out_max: vOutMax ?? config?.defaultVOutMax ?? 0,
      curve_ref: simulated ? null : curveRef || null,
      curve_points: simulated && chosen ? chosen.points.map((p) => [p.v, p.i]) : null,
      // Lets the saved run's curve_ref name the chosen demo curve, even
      // though it never lived in the server's own library - see
      // StartRunInput's own doc comment on reference_label.
      reference_label: simulated && chosen ? chosen.id : null,
      simulated,
    })
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Algorithm
          <select
            value={algorithm}
            onChange={(e) => setAlgorithm(e.target.value)}
            disabled={algorithms.length === 0}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          >
            {algorithms.length === 0 && <option value="">Loading...</option>}
            {algorithms.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Reference curve
          <select
            value={curveRef}
            onChange={(e) => setCurveRef(e.target.value)}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          >
            <option value="">
              {simulated ? 'Built-in reference panel' : 'None - run ungraded'}
            </option>
            {curves.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label || c.id} ({formatCapturedAt(c.captured_at)})
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Duration (s)
          <input
            type="number"
            min={1}
            value={durationInput}
            onChange={(e) => setDurationInput(e.target.value)}
            placeholder={`default ${config?.defaultDurationS ?? '...'}, max ${config?.maxDurationS ?? '...'}`}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Starting duty cycle
          <input
            type="number"
            min={0.01}
            max={0.99}
            step={0.01}
            value={initialDuty ?? ''}
            onChange={(e) => setInitialDuty(Number(e.target.value))}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          />
          <span className="text-xs">
            Where the algorithm starts hill-climbing from. On a curve with more than one
            peak this decides which maximum it settles on.
          </span>
        </label>

        <div className="flex gap-3">
          <label className="flex flex-1 flex-col gap-1 text-sm text-muted-foreground">
            v_max (V)
            <input
              type="number"
              value={vMax ?? ''}
              onChange={(e) => setVMax(Number(e.target.value))}
              className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-sm text-muted-foreground">
            i_max (A)
            <input
              type="number"
              value={iMax ?? ''}
              onChange={(e) => setIMax(Number(e.target.value))}
              className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-sm text-muted-foreground">
            v_out_max (V)
            <input
              type="number"
              value={vOutMax ?? ''}
              onChange={(e) => setVOutMax(Number(e.target.value))}
              className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
            />
          </label>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Leave duration blank to run up to the server's {config?.maxDurationS ?? '...'}s safety backstop
        - a longer request is clamped to it, never rejected. The run aborts immediately if a
        reading ever exceeds v_max/i_max, or the converter output exceeds v_out_max.
      </p>
      {!simulated && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
          Put a load on the converter output (for example 10 Ohm, 10 W) before a real run. With no
          load the SEPIC output climbs far above the panel voltage.
        </p>
      )}
      {!simulated && curveRef === '' && (
        <p className="text-xs text-muted-foreground">
          No reference curve selected - the run still works, there is simply no curve to grade it
          against on the chart below.
        </p>
      )}

      <Button
        onClick={handleStart}
        disabled={!canStart || starting || !algorithm}
        // See CurveWorkbench's Start Measurement for the same fix:
        // focusableWhenDisabled keeps the disabled reason reachable by
        // hover/focus instead of native `disabled` swallowing pointer
        // events outright.
        focusableWhenDisabled
        title={disabledReason ?? undefined}
        className="self-start"
      >
        {starting ? 'Starting...' : simulated ? 'Start simulated run' : 'Start run'}
      </Button>
      {!canStart && disabledReason && (
        <p className="text-xs text-muted-foreground">{disabledReason}</p>
      )}
      {startError && <p className="text-sm text-destructive">Failed to start: {startError}</p>}
    </div>
  )
}

function LiveReadouts({
  voltage,
  vout,
  current,
  duty,
}: {
  voltage: number | null
  vout: number | null
  current: number | null
  duty: number | null
}) {
  const { formatCurrent, formatPower } = useUnits()
  const power = voltage !== null && current !== null ? voltage * current : null

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-5">
      <Field label="V in" value={voltage !== null ? `${voltage.toFixed(2)} V` : '-'} />
      <Field label="V out" value={vout !== null ? `${vout.toFixed(2)} V` : '-'} />
      <Field label="I" value={current !== null ? formatCurrent(current) : '-'} />
      <Field label="P" value={power !== null ? formatPower(power) : '-'} />
      <Field label="Duty" value={duty !== null ? `${(duty * 100).toFixed(1)} %` : '-'} />
    </dl>
  )
}

function RunMonitor({
  phase,
  live,
  curves,
  stopping,
  stopError,
  onStop,
  onReset,
  onOpenPlayer,
  openRunError,
}: {
  phase: 'live' | 'done'
  live: LiveRunState
  curves: CurveRecord[]
  stopping: boolean
  stopError: string | null
  onStop: () => void
  onReset: () => void
  onOpenPlayer: () => void
  openRunError: string | null
}) {
  // The server sends the curve the run tracks; the library lookup is only
  // a fallback for a server that predates `reference_points`.
  const serverReference = live.reference_points ?? NO_POINTS
  const referenceCurve =
    serverReference.length > 0 ? null : findCurveForRun(curves, live.curve_ref)
  const referencePoints =
    serverReference.length > 0 ? serverReference : (referenceCurve?.points ?? NO_POINTS)
  const referenceMessage =
    serverReference.length > 0 ? null : referenceCurveMessage(live.curve_ref, referenceCurve)
  const current = live.samples.length > 0 ? live.samples[live.samples.length - 1] : null
  const saveFailed = phase === 'done' && !live.aborted && live.saved_run_id === null

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium text-foreground">{live.label || live.algorithm}</p>
            {/* Unmissable regardless of phase - the operator must never
                mistake a simulated run for one driving the real converter,
                while it runs or afterward. Same pattern ProvenanceBadge
                already uses for a replayed curve. */}
            <ProvenanceBadge source={live.source} />
          </div>
          <p className="text-xs text-muted-foreground">
            {phase === 'live'
              ? `Running - ${live.n_samples} sample${live.n_samples === 1 ? '' : 's'} captured`
              : 'Finished'}
          </p>
        </div>
        {phase === 'live' ? (
          <Button variant="destructive" onClick={onStop} disabled={stopping}>
            {stopping ? 'Stopping...' : 'Stop run'}
          </Button>
        ) : live.aborted ? (
          <Badge variant="destructive">Aborted</Badge>
        ) : (
          <Badge>Completed</Badge>
        )}
      </div>

      {phase === 'done' &&
        (live.aborted ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            This run ended early - {abortReasonMessage(live.abort_reason)}
          </p>
        ) : saveFailed ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            Run completed, but saving it failed: {live.abort_reason ?? 'unknown error'}
          </p>
        ) : (
          <p className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
            Completed the full run.
          </p>
        ))}

      {live.downsampled && (
        <p className="text-xs text-muted-foreground">
          Showing {live.samples.length} of {live.n_samples} samples, downsampled for display -
          some brief excursions may not be visible.
        </p>
      )}
      {referenceMessage && <p className="text-xs text-muted-foreground">{referenceMessage}</p>}

      <RunChart
        referencePoints={referencePoints}
        trail={live.samples}
        current={current}
      />

      <LiveReadouts
        voltage={live.voltage}
        vout={live.vout}
        current={live.current}
        duty={live.duty}
      />

      {stopError && <p className="text-sm text-destructive">Failed to stop: {stopError}</p>}

      {phase === 'done' && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={onOpenPlayer}
            disabled={!live.saved_run_id}
            focusableWhenDisabled
            title={live.saved_run_id ? undefined : 'Nothing was saved for this run'}
          >
            Open in player
          </Button>
          <Button size="sm" variant="outline" onClick={onReset}>
            Start another run
          </Button>
        </div>
      )}
      {openRunError && <p className="text-xs text-destructive">{openRunError}</p>}
    </div>
  )
}
