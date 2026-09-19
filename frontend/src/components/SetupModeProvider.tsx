import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { SETUP_MODE_STORAGE_KEY, SetupModeContext, type SetupMode } from '@/lib/setupMode'

function readStoredMode(): SetupMode {
  // localStorage throws in a private window or with site data blocked, and
  // returns nothing on a first visit - neither is worth failing a render.
  try {
    return window.localStorage.getItem(SETUP_MODE_STORAGE_KEY) === 'single' ? 'single' : 'full'
  } catch {
    return 'full'
  }
}

/** Supplies the page-wide single/full bench setup. See lib/setupMode.ts. */
export function SetupModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<SetupMode>(readStoredMode)

  useEffect(() => {
    try {
      window.localStorage.setItem(SETUP_MODE_STORAGE_KEY, mode)
    } catch {
      // A remembered preference is a convenience, not state we depend on.
    }
  }, [mode])

  const value = useMemo(() => ({ mode, setMode }), [mode])

  return <SetupModeContext.Provider value={value}>{children}</SetupModeContext.Provider>
}
