import { cn } from '@/lib/utils'
import { provenanceInfo } from '@/lib/provenance'

/**
 * "hardware" is the normal case on this bench and stays quiet - small
 * muted text, not a badge. Anything else means the curve was not measured
 * off a panel, so it gets a filled, high-contrast pill instead: someone
 * screenshotting a pane for a thesis must not be able to mistake a
 * replayed or simulated curve for a measurement.
 */
export function ProvenanceBadge({ source, className }: { source: string; className?: string }) {
  const info = provenanceInfo(source)
  if (info.measured) {
    return <span className={cn('text-xs text-muted-foreground', className)}>{info.label}</span>
  }
  return (
    <span
      className={cn(
        'inline-flex w-fit items-center gap-1 rounded-md bg-amber-500 px-2 py-0.5 text-xs font-semibold text-white dark:bg-amber-600',
        className,
      )}
    >
      {info.label}
    </span>
  )
}
