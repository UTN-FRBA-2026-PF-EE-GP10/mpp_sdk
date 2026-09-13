import { cn } from '@/lib/utils'
import { isLiveConnection, type ConnectionStatus } from '@/types'

const LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connecting...',
  connected: 'Pi connected',
  disconnected: 'Disconnected',
  demo: 'Demo mode - simulated',
}

const DOT_CLASS: Record<ConnectionStatus, string> = {
  connecting: 'bg-amber-500',
  connected: 'bg-emerald-500',
  disconnected: 'bg-red-500',
  demo: 'bg-sky-500',
}

/**
 * Sits beside `ConnectionIndicator` and answers a different question. The
 * connection dot says whether the Pi is talking to the Pico; this one says
 * the curve on screen came from the firmware's stored curves rather than a
 * panel. Both can be lit at once, and that combination is the normal case
 * when working away from a lit bench: a real, healthy SPI link carrying
 * replayed data.
 */
export function DemoIndicator() {
  return (
    <div className="flex items-center gap-2 rounded-full border border-violet-500/40 bg-violet-500/10 px-3 py-1 text-sm text-violet-600 dark:text-violet-400">
      <span className="relative inline-flex size-2.5 rounded-full bg-violet-500" />
      Replayed curve
    </div>
  )
}

export function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  return (
    <div className="flex items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground">
      <span className="relative flex size-2.5">
        {isLiveConnection(status) && (
          <span
            className={cn(
              'absolute inline-flex size-full animate-ping rounded-full opacity-60',
              DOT_CLASS[status],
            )}
          />
        )}
        <span className={cn('relative inline-flex size-2.5 rounded-full', DOT_CLASS[status])} />
      </span>
      {LABEL[status]}
    </div>
  )
}
