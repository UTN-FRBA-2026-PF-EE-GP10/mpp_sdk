import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { UNITS_STORAGE_KEY, UnitsContext, unitsValue, type UnitMode } from '@/lib/units'

function readStoredMode(): UnitMode {
  // localStorage throws in a private window or with site data blocked, and
  // returns nothing on a first visit - neither is worth failing a render.
  try {
    return window.localStorage.getItem(UNITS_STORAGE_KEY) === 'base' ? 'base' : 'milli'
  } catch {
    return 'milli'
  }
}

/** Supplies the page-wide current/power unit setting. See lib/units.ts. */
export function UnitsProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<UnitMode>(readStoredMode)

  useEffect(() => {
    try {
      window.localStorage.setItem(UNITS_STORAGE_KEY, mode)
    } catch {
      // A remembered preference is a convenience, not state we depend on.
    }
  }, [mode])

  const value = useMemo(() => unitsValue(mode, setMode), [mode])

  return <UnitsContext.Provider value={value}>{children}</UnitsContext.Provider>
}
