import { Menu } from '@base-ui/react/menu'
import { useState } from 'react'
import { statusFromLink } from '@/hooks/useConnectionStatus'
import { fetchLiveSweep } from '@/lib/api'
import { CAPTURE_MODE_LABEL, useCaptureMode, type CaptureMode } from '@/lib/captureMode'
import { cn } from '@/lib/utils'
import type { ConnectionStatus } from '@/types'

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Checking PICO...',
  connected: 'PICO connected',
  disconnected: 'PICO not connected',
  demo: 'Demo mode - simulated', // curve_tracer_server.py --demo, a server-side status - distinct from CaptureMode's client-side 'simulated', see lib/captureMode.ts
}

// 'firmware-replay' ("Demo with PICO") needs a real board on the other end
// of a real link - the server's own --demo status is itself a simulated
// stand-in with nothing to replay from, so it doesn't count.
function firmwareReplayAvailable(status: ConnectionStatus): boolean {
  return status === 'connected'
}

function displayLabel(status: ConnectionStatus, mode: CaptureMode): string {
  if (mode === 'simulated') return CAPTURE_MODE_LABEL.simulated
  if (status === 'demo') return STATUS_LABEL.demo
  if (status === 'connected') return CAPTURE_MODE_LABEL[mode === 'firmware-replay' ? 'firmware-replay' : 'hardware']
  return STATUS_LABEL[status]
}

function dotClass(status: ConnectionStatus, mode: CaptureMode): string {
  if (mode === 'simulated') return 'bg-violet-500'
  if (status === 'demo') return 'bg-sky-500'
  if (status === 'connected') return mode === 'firmware-replay' ? 'bg-indigo-500' : 'bg-emerald-500'
  if (status === 'connecting') return 'bg-amber-500'
  return 'bg-red-500'
}

const itemClass =
  'flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-50'

/**
 * The connection status pill - and, by clicking it, the three-way capture
 * mode menu (lib/captureMode.ts): 'hardware' ("PICO connected"),
 * 'firmware-replay' ("Demo with PICO", needs a live link), 'simulated'
 * ("Demo", fully offline). Only one of the three is ever shown, and the
 * label always matches whichever `source` a curve captured right now
 * would be stamped with - see captureMode.ts's docstring.
 */
export function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  const { mode, setMode } = useCaptureMode()
  const label = displayLabel(status, mode)
  const dot = dotClass(status, mode)
  const pulsing = mode === 'simulated' || status === 'connected' || status === 'demo'

  // In 'hardware'/'firmware-replay' the background link poll (see
  // useConnectionStatus) keeps `status` live, so it already answers
  // whether 'firmware-replay' can be selected. In 'simulated' mode that
  // poll is stopped outright - demo mode promises no background network
  // activity - so `status` is whatever it was the moment demo mode was
  // entered, not the truth. A one-shot check, fired only when this menu
  // is actually opened, is demo mode's only source of truth for this;
  // `null` (never opened, or still in flight) reads as unavailable, same
  // as a failed check - "Demo with PICO" must never be selectable on stale
  // or missing information.
  const [demoLinkStatus, setDemoLinkStatus] = useState<ConnectionStatus | null>(null)
  const replayAvailable =
    mode === 'simulated'
      ? demoLinkStatus !== null && firmwareReplayAvailable(demoLinkStatus)
      : firmwareReplayAvailable(status)

  function handleOpenChange(open: boolean) {
    if (!open || mode !== 'simulated') return
    fetchLiveSweep()
      .then((data) => setDemoLinkStatus(statusFromLink(data.link)))
      .catch(() => setDemoLinkStatus('disconnected'))
  }

  return (
    <Menu.Root onOpenChange={handleOpenChange}>
      <Menu.Trigger
        aria-label={`Capture mode: ${label}. Click to change.`}
        title="Click to change capture mode"
        className={cn(
          'flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground transition-colors',
          'hover:bg-muted hover:text-foreground',
          'outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
          mode === 'simulated' &&
            'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300',
          mode === 'firmware-replay' &&
            status === 'connected' &&
            'border-indigo-500/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
        )}
      >
        <span className="relative flex size-2.5">
          {pulsing && (
            <span
              className={cn(
                'absolute inline-flex size-full animate-ping rounded-full opacity-60',
                dot,
              )}
            />
          )}
          <span className={cn('relative inline-flex size-2.5 rounded-full', dot)} />
        </span>
        {label}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="end" sideOffset={6}>
          <Menu.Popup className="z-50 min-w-56 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg outline-none">
            <Menu.RadioGroup
              value={mode}
              onValueChange={(value) => setMode(value as CaptureMode)}
            >
              <Menu.RadioItem value="hardware" closeOnClick className={itemClass}>
                <div className="flex flex-col">
                  <span>{CAPTURE_MODE_LABEL.hardware}</span>
                  <span className="text-xs text-muted-foreground">
                    Live measurement off a real panel.
                  </span>
                </div>
              </Menu.RadioItem>
              <Menu.RadioItem
                value="firmware-replay"
                disabled={!replayAvailable}
                closeOnClick
                className={itemClass}
              >
                <div className="flex flex-col">
                  <span>{CAPTURE_MODE_LABEL['firmware-replay']}</span>
                  <span className="text-xs text-muted-foreground">
                    {replayAvailable
                      ? 'Real board, a curve replayed from the firmware.'
                      : 'Needs a live link to the Pi.'}
                  </span>
                </div>
              </Menu.RadioItem>
              <Menu.RadioItem value="simulated" closeOnClick className={itemClass}>
                <div className="flex flex-col">
                  <span>Demo</span>
                  <span className="text-xs text-muted-foreground">
                    No board - bundled sample data only.
                  </span>
                </div>
              </Menu.RadioItem>
            </Menu.RadioGroup>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}
