/** Shared by every place a curve's capture time is shown (the saved-curves
 * table, the dashboard panes, the expanded view) so they read identically. */
export function formatCapturedAt(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** A run's duration or playback position, one decimal place - used by the
 * runs table (duration_s) and the run player's transport (elapsed time),
 * so the two never disagree on how a span of seconds is written. */
export function formatSeconds(s: number): string {
  return `${s.toFixed(1)}s`
}
