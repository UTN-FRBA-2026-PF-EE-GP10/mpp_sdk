import { Button } from '@/components/ui/button'
import { useSetupMode } from '@/lib/setupMode'
import type { SetupMode } from '@/lib/setupMode'

const NEXT: Record<SetupMode, SetupMode> = { single: 'full', full: 'single' }
const LABEL: Record<SetupMode, string> = { single: 'Single', full: 'Full' }

/**
 * Switches the bench setup between one panel (Single) and two (Full) -
 * decides what a fresh curve capture saves and what load the run form
 * suggests. One control for the whole page, same minimal footprint as
 * UnitToggle/ThemeToggle: the setting is global, so a per-pane switch
 * would silently change every other pane too.
 */
export function SetupModeToggle() {
  const { mode, setMode } = useSetupMode()
  const next = NEXT[mode]

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => setMode(next)}
      title={`Setup: ${LABEL[mode]} panel${mode === 'full' ? 's' : ''}. Click to switch to ${LABEL[next]}.`}
    >
      {LABEL[mode]}
    </Button>
  )
}
