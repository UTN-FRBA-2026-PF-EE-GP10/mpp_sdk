import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  CAPTURE_MODE_STORAGE_KEY,
  CaptureModeContext,
  isCaptureMode,
  type CaptureMode,
  type CaptureModeValue,
} from '@/lib/captureMode'

function readStoredMode(): CaptureMode {
  try {
    const stored = window.localStorage.getItem(CAPTURE_MODE_STORAGE_KEY)
    return isCaptureMode(stored) ? stored : 'hardware'
  } catch {
    return 'hardware'
  }
}

/** Supplies the page-wide capture mode - 'hardware' / 'firmware-replay' /
 * 'simulated', see lib/captureMode.ts. Persisted the same way
 * lib/units.ts persists the unit mode. App.tsx is responsible for the one
 * rule this provider itself doesn't know how to enforce: 'firmware-replay'
 * needs a live link, and falls back to 'hardware' when one isn't there -
 * see the effect in App.tsx that watches ConnectionStatus. */
export function CaptureModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<CaptureMode>(readStoredMode)

  useEffect(() => {
    try {
      window.localStorage.setItem(CAPTURE_MODE_STORAGE_KEY, mode)
    } catch {
      // A remembered preference is a convenience, not state depended on.
    }
  }, [mode])

  const value = useMemo<CaptureModeValue>(() => ({ mode, setMode }), [mode])

  return <CaptureModeContext.Provider value={value}>{children}</CaptureModeContext.Provider>
}
