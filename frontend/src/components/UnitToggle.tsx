import { Button } from '@/components/ui/button'
import { useUnits } from '@/lib/units'

/**
 * Switches every chart and readout between mA/mW and A/W. One control for
 * the whole page rather than one per pane: the setting is global, so a
 * per-pane button would silently change every other pane too.
 */
export function UnitToggle() {
  const { mode, setMode, currentLabel, powerLabel } = useUnits()

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => setMode(mode === 'milli' ? 'base' : 'milli')}
      title="Switch between milliamps/milliwatts and amps/watts"
    >
      {currentLabel} / {powerLabel}
    </Button>
  )
}
