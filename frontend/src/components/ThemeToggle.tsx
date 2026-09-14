import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'
import type { ThemeMode } from '@/lib/theme'

const NEXT: Record<ThemeMode, ThemeMode> = { light: 'dark', dark: 'system', system: 'light' }
const ICON: Record<ThemeMode, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }
const LABEL: Record<ThemeMode, string> = { light: 'Light', dark: 'Dark', system: 'System' }

/**
 * Cycles light -> dark -> system -> light. One button rather than a
 * three-way segmented control, matching UnitToggle's minimal footprint in
 * the header - the setting is page-wide, so it only needs one control.
 */
export function ThemeToggle() {
  const { mode, setMode } = useTheme()
  const Icon = ICON[mode]

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => setMode(NEXT[mode])}
      aria-label={`Theme: ${LABEL[mode]}. Click to switch to ${LABEL[NEXT[mode]]}.`}
      title={`Theme: ${LABEL[mode]} (click to change)`}
    >
      <Icon />
      {LABEL[mode]}
    </Button>
  )
}
