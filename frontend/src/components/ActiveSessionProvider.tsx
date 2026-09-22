import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ACTIVE_SESSION_STORAGE_KEY,
  ActiveSessionContext,
  parseStoredActiveSession,
  type ActiveSession,
  type ActiveSessionValue,
} from '@/lib/activeSession'

function readStored(): ActiveSession | null {
  // localStorage throws in a private window or with site data blocked, and
  // returns nothing on a first visit - neither is worth failing a render.
  try {
    return parseStoredActiveSession(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY))
  } catch {
    return null
  }
}

/** Supplies the page-wide active session. See lib/activeSession.ts. */
export function ActiveSessionProvider({ children }: { children: ReactNode }) {
  const [active, setActiveState] = useState<ActiveSession | null>(readStored)

  useEffect(() => {
    try {
      if (active === null) window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY)
      else window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(active))
    } catch {
      // A remembered choice is a convenience, not state we depend on.
    }
  }, [active])

  const setActive = useCallback((id: string, title: string) => {
    // Same value again must not re-render every consumer.
    setActiveState((prev) => (prev?.id === id && prev.title === title ? prev : { id, title }))
  }, [])
  const clear = useCallback(() => setActiveState(null), [])

  const value = useMemo<ActiveSessionValue>(
    () => ({ active, setActive, clear }),
    [active, setActive, clear],
  )

  return <ActiveSessionContext.Provider value={value}>{children}</ActiveSessionContext.Provider>
}
