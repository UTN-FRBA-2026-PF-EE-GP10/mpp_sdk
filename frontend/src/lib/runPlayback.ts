// Pure logic behind the run player (components/RunPlayerDialog.tsx,
// hooks/useRunPlayback.ts) - kept dependency-free and separate from the
// animation itself so it can be unit tested directly, the same split
// curveMath.ts makes for CurveChart's MPP marker.

import type { RunSample } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/** Playback duration in seconds - the run's own elapsed time, not
 * wall-clock. `RunSample.t` is seconds since the run started (see
 * mpp_sdk/runs/record.py), so this is just the span between the first and
 * last sample. Zero for a run too short to animate. */
export function runDuration(samples: RunSample[]): number {
  if (samples.length < 2) return 0
  return samples[samples.length - 1].t - samples[0].t
}

/** The sample the player should show at `elapsedS` seconds into playback
 * - the last sample whose relative time (time since the first sample) has
 * not yet passed. Clamps to the first/last sample outside the run's
 * range, so a caller never has to special-case the ends. `-1` for an
 * empty run. Binary search: this runs every animation frame against a
 * run that can hold a couple of thousand samples. */
export function sampleIndexAtTime(samples: RunSample[], elapsedS: number): number {
  if (samples.length === 0) return -1
  const t0 = samples[0].t
  if (elapsedS <= 0) return 0
  let lo = 0
  let hi = samples.length - 1
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (samples[mid].t - t0 <= elapsedS) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Every sample from the start of the run up to and including `index` -
 * the trail the operating point drags behind it. `index < 0` (an empty
 * run) draws no trail. */
export function trailUpTo(samples: RunSample[], index: number): RunSample[] {
  if (index < 0) return []
  return samples.slice(0, index + 1)
}

/** `curve_ref` is a filename under mpp_sdk.curves.library.default_dir()
 * (see RunRecord's docstring), while a fetched CurveRecord's `path` is
 * that file's full server-side path - so matching means comparing
 * basenames, not the raw strings. `null` if there is no reference or it
 * was not found among the curves the caller has (deleted, or the id
 * simply doesn't resolve). */
export function findCurveForRun(curves: CurveRecord[], curveRef: string | null): CurveRecord | null {
  if (curveRef === null) return null
  return curves.find((c) => c.path.split('/').pop() === curveRef) ?? null
}

/** The message to show in place of the faded reference curve when there
 * isn't one to draw - `null` means a reference curve was found and no
 * message is needed. Kept separate from `findCurveForRun` so the two
 * "missing" cases (never had one vs. had one that's now gone) read
 * differently instead of collapsing into one silent blank background. */
export function referenceCurveMessage(curveRef: string | null, found: CurveRecord | null): string | null {
  if (curveRef === null) return 'No reference curve was captured for this run.'
  if (found === null) return `Reference curve "${curveRef}" was not found - it may have been deleted.`
  return null
}
