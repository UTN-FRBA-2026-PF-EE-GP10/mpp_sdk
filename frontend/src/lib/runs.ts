// Shapes for the sidebar's Runs section, mirroring GET /api/runs and
// GET /api/runs/{id} in scripts/curve_tracer_server.py (backed by
// mpp_sdk/runs/record.py's RunRecord). api.ts's fetchRuns/fetchRun cross
// the wire; groupRunsByDate here turns a summary list into what the
// sidebar renders, the same way GET /api/curves feeds byKind in App.tsx.

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
}

// One control-loop sample, volts/amps/duty - see api.ts's note on why this
// differs from GET /api/data's milliamps.
export interface RunSample {
  t: number
  v: number
  i: number
  d: number
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
