import { Pause, Play, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ProvenanceBadge } from '@/components/ProvenanceBadge'
import { RunChart } from '@/components/RunChart'
import { RunReadouts } from '@/components/RunReadouts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogPopup, DialogTitle } from '@/components/ui/dialog'
import { useRunPlayback } from '@/hooks/useRunPlayback'
import { deleteRun, fetchRun } from '@/lib/api'
import { DEMO_RUNS } from '@/lib/demoFixtures'
import { formatCapturedAt, formatSeconds } from '@/lib/format'
import { findCurveForRun, referenceCurveMessage, trailUpTo } from '@/lib/runPlayback'
import { readOnlyReasonText, useReadOnly, useSession } from '@/lib/session'
import type { RunDetail, RunSummary } from '@/lib/runs'
import { mppPoint } from '@/lib/curveMath'
import type { CurvePoint, CurveRecord } from '@/types'

const SPEEDS = [0.25, 0.5, 1, 2, 4]

// A stable empty array for "no reference curve" - `referenceCurve?.points
// ?? []` would otherwise allocate a fresh array every render, and that
// new identity is enough to make RunChart's memoised chart.js data (and
// so a real chart redraw) recompute for a re-render that has nothing to
// do with the chart at all.
const NO_POINTS: CurveRecord['points'] = []

/**
 * The run player - opened from RunDatePane's list, standing alongside
 * CurveDetailDialog as the app's other "one expanded view" dialog.
 * `run` doubles as the open/closed flag, same convention as
 * CurveDetailDialog's `record`. The dialog owns fetching the full sample
 * series: RunDatePane only ever has summaries (GET /api/runs), so opening
 * a run always means one GET /api/runs/{id} first.
 */
export function RunPlayerDialog({
  run,
  curves,
  onClose,
  onDeleted,
  fallbackReferencePoints,
}: {
  run: RunSummary | null
  curves: CurveRecord[]
  onClose: () => void
  onDeleted: () => void
  /** The curve the live view drew for this run (the server's
   * `reference_points`), used when the saved run's `curve_ref` finds
   * nothing - e.g. the built-in panel, which no saved curve describes.
   * Only RunPane passes it, for the run it has just watched. */
  fallbackReferencePoints?: CurvePoint[]
}) {
  return (
    <Dialog
      open={run !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogPopup className="max-w-3xl">
        {run && (
          <RunPlayerContent
            key={run.id}
            run={run}
            curves={curves}
            onClose={onClose}
            onDeleted={onDeleted}
            fallbackReferencePoints={fallbackReferencePoints}
          />
        )}
      </DialogPopup>
    </Dialog>
  )
}

function RunPlayerContent({
  run,
  curves,
  onClose,
  onDeleted,
  fallbackReferencePoints,
}: {
  run: RunSummary
  curves: CurveRecord[]
  onClose: () => void
  onDeleted: () => void
  fallbackReferencePoints?: CurvePoint[]
}) {
  const readOnly = useReadOnly()
  const session = useSession()

  // Most runs opened in demo mode are one of DEMO_RUNS (RunDatePane's list
  // comes straight from the bundled fixtures, see App.tsx), so the detail
  // is looked up locally instead of a GET /api/runs/{id} that would 404
  // against a real backend that was never there to begin with. This is
  // resolved synchronously, during the initial render, rather than in the
  // effect below - it's derived from props already in hand, not fetched.
  // An imported session's runs (view mode) work the same way, for the same
  // reason: session.runs already carries every sample, and there is no
  // server to fetch from at all - see lib/session.ts.
  //
  // Gated on fixture/session membership, not `readOnly.enabled` alone: a
  // simulated run started from RunPane while in demo mode genuinely lives
  // on the real server (see frontend/README.md's demo-mode note - starting
  // a run is the one write demo mode still makes), so its id is never one
  // of the bundled fixtures and must still be fetched normally, even here.
  const isBundledFixture = DEMO_RUNS.some((r) => r.id === run.id)
  const sessionRun = session.active ? (session.runs.find((r) => r.id === run.id) ?? null) : null
  const [detail, setDetail] = useState<RunDetail | null>(() =>
    sessionRun ?? (isBundledFixture ? (DEMO_RUNS.find((r) => r.id === run.id) ?? null) : null),
  )
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // `run.id` only ever changes by remounting this component (the dialog
  // keys RunPlayerContent by it), so `detail`/`loadError` already start
  // fresh from their initial state - no reset needed here, just the
  // fetch itself. A bundled fixture's or a session's initial state is
  // already the answer (see above), so there is nothing left for this
  // effect to do there.
  useEffect(() => {
    if (isBundledFixture || sessionRun) return
    fetchRun(run.id)
      .then(setDetail)
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [run.id, isBundledFixture, sessionRun])

  async function handleDelete() {
    if (readOnly.enabled) return // defense in depth - the button is disabled anyway
    if (!window.confirm(`Delete run "${run.label || run.id}"? This cannot be undone.`)) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteRun(run.id)
      onDeleted()
      onClose()
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2 pr-6">
        <div>
          <DialogTitle>{run.label || 'Untitled run'}</DialogTitle>
          <p className="text-sm text-muted-foreground">
            {run.algorithm} - {formatCapturedAt(run.captured_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ProvenanceBadge source={run.source} />
          {run.aborted && <Badge variant="destructive">Aborted</Badge>}
        </div>
      </div>

      {run.aborted && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          This run stopped early - the client-side safety cutoff fired before it completed. Read
          the trace as a truncated attempt, not a finished one.
        </p>
      )}

      {loadError && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Failed to load run: {loadError}
        </p>
      )}

      {!detail && !loadError && (
        <p className="text-sm text-muted-foreground">Loading run...</p>
      )}

      {detail && (
        <RunPlayer
          detail={detail}
          curves={curves}
          fallbackReferencePoints={fallbackReferencePoints}
        />
      )}

      {deleteError && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Failed to delete run: {deleteError}
        </p>
      )}

      <div className="flex flex-col items-end gap-1">
        <Button
          variant="destructive"
          size="sm"
          onClick={handleDelete}
          disabled={deleting || readOnly.enabled}
          focusableWhenDisabled
          title={readOnly.enabled ? readOnlyReasonText(readOnly.reason ?? 'demo', 'Deleting') : undefined}
        >
          <Trash2 />
          {deleting ? 'Deleting...' : 'Delete run'}
        </Button>
        {readOnly.enabled && (
          <p className="text-xs text-muted-foreground">
            {readOnlyReasonText(readOnly.reason ?? 'demo', 'Delete')}.
          </p>
        )}
      </div>
    </div>
  )
}

function RunPlayer({
  detail,
  curves,
  fallbackReferencePoints,
}: {
  detail: RunDetail
  curves: CurveRecord[]
  fallbackReferencePoints?: CurvePoint[]
}) {
  const playback = useRunPlayback(detail.samples)
  const current = playback.index >= 0 ? detail.samples[playback.index] : null
  // Memoised so an unrelated re-render (e.g. the delete button's local
  // state) doesn't hand RunChart a new array reference every time -
  // `trailUpTo` slices, which always allocates, and chart.js redraws
  // whenever the data object it's given changes identity.
  const trail = useMemo(
    () => trailUpTo(detail.samples, playback.index),
    [detail.samples, playback.index],
  )

  const referenceCurve = findCurveForRun(curves, detail.curve_ref)
  const fallback = fallbackReferencePoints ?? NO_POINTS
  const useFallback = referenceCurve === null && fallback.length > 0
  const referencePoints = referenceCurve?.points ?? (useFallback ? fallback : NO_POINTS)
  const referenceMessage = useFallback
    ? null
    : referenceCurveMessage(detail.curve_ref, referenceCurve)
  const mppTh = useMemo(() => mppPoint(referencePoints), [referencePoints])

  return (
    <div className="flex flex-col gap-3">
      {detail.downsampled && (
        <p className="text-xs text-muted-foreground">
          Showing {detail.samples.length} of {detail.n_samples} samples, downsampled for
          playback - some brief excursions may not be visible.
        </p>
      )}

      {referenceMessage && <p className="text-xs text-muted-foreground">{referenceMessage}</p>}

      <RunChart
        referencePoints={referencePoints}
        trail={trail}
        current={current}
      />

      <RunReadouts sample={current} mppTh={mppTh} />

      <RunTransport playback={playback} />
    </div>
  )
}

function RunTransport({ playback }: { playback: ReturnType<typeof useRunPlayback> }) {
  const { playing, time, duration, toggle, restart, seek, speed, setSpeed } = playback
  const disabled = duration <= 0

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        variant="outline"
        size="icon-sm"
        onClick={toggle}
        disabled={disabled}
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing ? <Pause /> : <Play />}
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={restart}
        disabled={disabled}
        aria-label="Restart"
      >
        <RotateCcw />
      </Button>
      <input
        type="range"
        min={0}
        max={disabled ? 1 : duration}
        step={disabled ? 1 : duration / 1000}
        value={time}
        onChange={(e) => seek(Number(e.target.value))}
        disabled={disabled}
        aria-label="Playback position"
        className="min-w-[140px] flex-1"
      />
      <span className="w-24 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
        {formatSeconds(time)} / {formatSeconds(duration)}
      </span>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        Speed
        <select
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="rounded-md border bg-transparent px-1.5 py-1 text-xs"
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}x
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
