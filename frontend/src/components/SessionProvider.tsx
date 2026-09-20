import { useMemo, useState, type ReactNode } from 'react'
import { SessionContext, type SessionFile, type SessionValue } from '@/lib/session'

/** Holds an imported session file, if any - view mode. Deliberately not
 * persisted (no localStorage/sessionStorage): a session file can be large
 * (up to 50 MB) and, like the pending-remeasure state in App.tsx, a reload
 * should drop back to the normal mode rather than resurrect a stale view.
 * Close only ever clears this - it never touches capture mode or setup
 * mode, so "restores the previous mode" happens for free: App.tsx's
 * records/runs fall straight back through the same sandbox/live chain
 * they used before a session was opened. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionFile | null>(null)

  const value = useMemo<SessionValue>(() => {
    if (session === null) {
      return {
        active: false,
        title: null,
        setup: null,
        report: null,
        curves: [],
        runs: [],
        missing: { curve_ids: [], run_ids: [] },
        enter: setSession,
        close: () => setSession(null),
      }
    }
    return {
      active: true,
      title: session.title,
      setup: session.setup,
      report: session.report,
      curves: session.curves.map((entry) => entry.record),
      runs: session.runs.map((entry) => entry.record),
      missing: session.missing,
      enter: setSession,
      close: () => setSession(null),
    }
  }, [session])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
