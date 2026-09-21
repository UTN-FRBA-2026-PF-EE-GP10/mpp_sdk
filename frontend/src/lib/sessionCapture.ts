// "Capture into this step": one action that starts a sweep or a run, waits
// for it, saves the result stamped with the session, and links it to the
// step. It reuses the same api.ts calls the Measure pane makes
// (start-sweep / save-curve, runs/start / runs/live) rather than a second
// path to the board.
//
// The order is the point: nothing is linked until the record is saved, and
// nothing is saved unless the capture finished. A failure at any earlier
// point therefore leaves the step exactly as it was - never a link to
// something that does not exist. One exception is not ours to prevent: a
// run that outlives the wait keeps going, and the server saves it, stamped
// but unlinked, when it ends.

import {
  fetchLiveRun,
  fetchLiveSweep,
  fetchRunConfig,
  saveCurve,
  startRun,
  startSweep,
} from '@/lib/api'
import { isSessionNotFound } from '@/lib/apiError'
import { abortReasonMessage } from '@/lib/liveRun'
import type { SessionStep } from '@/lib/sessions'

/** Thrown for every failure of the flow, with a message meant to be shown
 * to the operator as-is. */
export class CaptureError extends Error {}

/** The server said the session no longer exists - deleted in another tab,
 * say. The caller should stop filing into it. */
export class SessionGoneError extends CaptureError {}

export interface CaptureTimings {
  /** How often the sweep or run is polled. */
  pollMs: number
  /** Backstop for a sweep that never reports completion (a dropped link).
   * Not tied to any hardware timing - only there so the action cannot wait
   * forever. */
  sweepTimeoutMs: number
  /** Added to a run's own duration before giving up on it. */
  runGraceMs: number
}

export const DEFAULT_CAPTURE_TIMINGS: CaptureTimings = {
  pollMs: 500,
  sweepTimeoutMs: 120_000,
  runGraceMs: 30_000,
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Sweeps the panel and saves the curve, stamped with `sessionId`. Resolves
 * with the saved curve's id. */
async function captureCurve(
  sessionId: string,
  step: SessionStep,
  timings: CaptureTimings,
): Promise<string> {
  // The board serves one thing at a time, and the server accepts a sweep
  // command while a run is on: it queues it, and it then fires unattended
  // once the run ends. So a run in progress is refused here, not discovered
  // as a timeout.
  const liveRun = await fetchLiveRun(2)
  if (liveRun.status === 'running') {
    throw new CaptureError('A run is in progress - wait for it to finish before sweeping.')
  }
  const before = await fetchLiveSweep()
  // A sweep someone else started would be taken for ours.
  if (before.active) throw new CaptureError('A sweep is already in progress - wait for it to finish.')

  await startSweep()
  const deadline = Date.now() + timings.sweepTimeoutMs
  for (;;) {
    await sleep(timings.pollMs)
    const now = await fetchLiveSweep()
    if (now.commandError !== null && now.commandError !== before.commandError) {
      throw new CaptureError(`The sweep did not start: ${now.commandError}`)
    }
    // A new seq is the server saying a completed sweep replaced the old
    // points - without it, `points` is still the previous curve.
    if (now.seq !== before.seq && !now.active && now.points.length > 0) break
    if (Date.now() > deadline) throw new CaptureError('The sweep did not finish in time.')
  }

  const saved = await saveCurve({
    label: step.title,
    // A step does not say which kind of measurement it is, so the curve
    // must not claim one (baseline, tilted) it may not be.
    measurement: 'other',
    panels: [],
    notes: `Captured from session step "${step.title}".`,
    session_id: sessionId,
  })
  return saved.id
}

/** Runs `algorithm` (or the server's first one) with the server's default
 * bounds and saves the run, stamped with `sessionId`. Resolves with the
 * saved run's id. */
async function captureRun(
  sessionId: string,
  step: SessionStep,
  algorithm: string | undefined,
  timings: CaptureTimings,
): Promise<string> {
  const config = await fetchRunConfig()
  const chosen = algorithm ?? config.algorithms[0]
  if (!chosen) throw new CaptureError('The server offers no algorithm to run.')

  await startRun({
    algorithm: chosen,
    duration_s: config.defaultDurationS,
    initial_duty: config.defaultInitialDuty,
    v_max: config.defaultVMax,
    i_max: config.defaultIMax,
    v_out_max: config.defaultVOutMax,
    label: step.title,
    simulated: false,
    session_id: sessionId,
  })

  const deadline = Date.now() + config.defaultDurationS * 1000 + timings.runGraceMs
  for (;;) {
    await sleep(timings.pollMs)
    const live = await fetchLiveRun(2)
    if (live.status === 'done') {
      if (live.aborted) {
        // The server may have saved what was recorded before the abort. It
        // stays in the library, stamped, but is not linked as if it were
        // the measurement the step asks for.
        throw new CaptureError(
          `The run ended early - ${abortReasonMessage(live.abort_reason)} It was not linked to the step.`,
        )
      }
      if (live.saved_run_id === null) {
        throw new CaptureError(
          `The run finished but could not be saved: ${live.abort_reason ?? 'unknown error'}`,
        )
      }
      return live.saved_run_id
    }
    if (Date.now() > deadline) {
      // Giving up waiting does not stop the run: it is still driving the
      // converter, and the server saves it, stamped, when it ends.
      throw new CaptureError(
        'The run is taking longer than expected and is still going. When it ends it is ' +
          'saved under this session but not linked to this step - link it from the picker below.',
      )
    }
  }
}

export interface CaptureIntoStepOptions {
  sessionId: string
  step: SessionStep
  /** Run steps only. Omitted takes the server's first algorithm. */
  algorithm?: string
  /** Links the saved item to the step. Called at most once, and only after
   * the item is saved. */
  link: (kind: 'curve' | 'run', id: string) => Promise<void>
  timings?: Partial<CaptureTimings>
}

/** Captures for one `curve` or `run` step, end to end. Rejects with a
 * `CaptureError` whose message says what happened and, when the item was
 * saved but not linked, says so - the item is then in the library, stamped
 * with the session, and can be linked from the step's picker. */
export async function captureIntoStep(options: CaptureIntoStepOptions): Promise<void> {
  const { sessionId, step, algorithm, link } = options
  const timings = { ...DEFAULT_CAPTURE_TIMINGS, ...options.timings }
  const kind = step.kind === 'run' ? 'run' : 'curve'

  let id: string
  try {
    id =
      kind === 'run'
        ? await captureRun(sessionId, step, algorithm, timings)
        : await captureCurve(sessionId, step, timings)
  } catch (e) {
    if (e instanceof CaptureError) throw e
    if (isSessionNotFound(e)) {
      throw new SessionGoneError(
        'The session this capture was for no longer exists (it may have been deleted in ' +
          'another tab), so nothing was saved or linked. Filing into it has been turned off.',
      )
    }
    throw new CaptureError(`Capture failed: ${messageOf(e)}`)
  }

  try {
    await link(kind, id)
  } catch (e) {
    if (isSessionNotFound(e)) {
      throw new SessionGoneError(
        `Captured and saved the ${kind}, but the session no longer exists (it may have been ` +
          'deleted in another tab), so it could not be linked. Filing into it has been turned off.',
      )
    }
    throw new CaptureError(
      `Captured and saved the ${kind}, but linking it to this step failed: ${messageOf(e)}. ` +
        'It is in the library, filed under this session - link it from the picker below.',
    )
  }
}
