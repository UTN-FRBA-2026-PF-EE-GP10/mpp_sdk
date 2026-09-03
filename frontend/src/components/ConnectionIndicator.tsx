import { cn } from '@/lib/utils'
import type { ConnectionStatus } from '@/types'

const LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connecting...',
  connected: 'Pi connected',
  disconnected: 'Disconnected',
}

const DOT_CLASS: Record<ConnectionStatus, string> = {
  connecting: 'bg-amber-500',
  connected: 'bg-emerald-500',
  disconnected: 'bg-red-500',
}

export function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  return (
    <div className="flex items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground">
      <span className="relative flex size-2.5">
        {status === 'connected' && (
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
