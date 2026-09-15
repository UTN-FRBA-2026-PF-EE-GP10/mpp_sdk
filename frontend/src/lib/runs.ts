// Shapes for the sidebar's Runs section, mirroring GET /api/runs and
// GET /api/runs/{id} in scripts/curve_tracer_server.py (backed by
// mpp_sdk/runs/record.py's RunRecord). api.ts's fetchRuns/fetchRun cross
// the wire; groupRunsByDate here turns a summary list into what the
// sidebar renders, the same way GET /api/curves feeds byKind in App.tsx.

/** Where a run's samples actually came from - see RUN_SOURCES in
 * mpp_sdk/runs/record.py. Kept as an open union, same pattern as
 * CurveRecord['source'] in types.ts, so an unrecognised value still
 * type-checks instead of being narrowed away. Anything but "hardware"
 * means the converter was never driven - see ProvenanceBadge. */
export type RunSource = 'hardware' | 'simulated' | 'unknown' | (string & {})

export interface RunSummary {
  id: string
  path: string
  captured_at: string
  label: string
  algorithm: string
  n_samples: number
  duration_s: number
  aborted: boolean
  curve_ref: string | null
  notes: string
  source: RunSource
}

// One control-loop sample, volts/amps/duty - see api.ts's note on why this
// differs from GET /api/data's milliamps.
export interface RunSample {
  t: number
  v: number
  i: number
  d: number
}

/** One of the abort paths `run_control_loop` (scripts/run_algorithm.py)
 * can trip - or an open string for the rarer cases the server reports as
 * free text (an unexpected exception, or a save that failed after an
 * otherwise clean run). Kept as an open union, same pattern as
 * CurveRecord['source'] in types.ts, so an unrecognised value still
 * type-checks instead of being narrowed away. */
export type AbortReason =
  | 'overvoltage'
  | 'overcurrent'
  | 'link-down'
  | 'stopped'
  | (string & {})

/** GET /api/runs/live's shape - the one closed-loop run in progress, or
 * the most recently finished one until the next starts. Volts/amps/duty
 * like RunSample above; `vout` is the converter's output voltage, read
 * live off the board but never persisted on RunSample/RunRecord (see
 * curve_tracer_server.py's module docstring on why) - this is the only
 * place it appears. `voltage`/`current`/`duty` mirror the latest sample
 * in `samples` for a caller that wants a live readout without indexing
 * into it. */
export interface LiveRunState {
  status: 'idle' | 'running' | 'done'
  algorithm: string | null
  label: string
  curve_ref: string | null
  n_samples: number
  downsampled: boolean
  samples: RunSample[]
  voltage: number | null
  current: number | null
  duty: number | null
  vout: number | null
  aborted: boolean
  abort_reason: AbortReason | null
  saved_run_id: string | null
  /** Which kind of run is in flight (or just finished) - "hardware" or
   * "simulated", never "unknown": a live run always knows which source it
   * started against. See RunSource. */
  source: RunSource
}

// GET /api/runs/{id}'s shape: everything in RunSummary plus the samples
// themselves. `n_samples` stays the true on-disk count even when
// `downsampled` is true and `samples` is shorter - see fetchRun in api.ts.
export interface RunDetail extends RunSummary {
  downsampled: boolean
  samples: RunSample[]
}

export interface RunDateGroup {
  date: string
  runs: RunSummary[]
}

/**
 * Groups by the calendar-day prefix of `captured_at` (an ISO string, same
 * convention as CurveRecord), newest date first and newest run first
 * within a date. Plain string slicing/comparison, not `Date` parsing -
 * consistent with how App.tsx already orders CurveRecords, and avoids a
 * bare-date parse quietly shifting to a different calendar day in a
 * timezone west of UTC.
 */
export function groupRunsByDate(runs: RunSummary[]): RunDateGroup[] {
  const groups = new Map<string, RunSummary[]>()
  for (const run of runs) {
    const date = run.captured_at.slice(0, 10)
    if (!groups.has(date)) groups.set(date, [])
    groups.get(date)?.push(run)
  }
  for (const bucket of groups.values()) {
    bucket.sort((a, b) => b.captured_at.localeCompare(a.captured_at))
  }
  return Array.from(groups.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([date, dateRuns]) => ({ date, runs: dateRuns }))
}
