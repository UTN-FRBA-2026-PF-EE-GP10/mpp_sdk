import { useMemo, useState, type ReactNode } from 'react'
import { ImportedSessionContext, type ImportedSessionValue, type SessionFile } from '@/lib/sessionFile'

/** Holds an imported session file, if any - view mode. Deliberately not
 * persisted (no localStorage/sessionStorage): a session file can be large
 * (up to 50 MB) and, like the pending-remeasure state in App.tsx, a reload
 * should drop back to the normal mode rather than resurrect a stale view.
 * Close only ever clears this - it never touches capture mode or setup
 * mode, so "restores the previous mode" happens for free: App.tsx's
 * records/runs fall straight back through the same sandbox/live chain
 * they used before a file was opened. */
export function ImportedSessionProvider({ children }: { children: ReactNode }) {
  const [file, setFile] = useState<SessionFile | null>(null)

  const value = useMemo<ImportedSessionValue>(() => {
    if (file === null) {
      return {
        active: false,
        title: null,
        setup: null,
        session: null,
        curves: [],
        runs: [],
        missing: { curve_ids: [], run_ids: [] },
        enter: setFile,
        close: () => setFile(null),
      }
    }
    return {
      active: true,
      title: file.title,
      setup: file.setup,
      session: file.session,
      curves: file.curves.map((entry) => entry.record),
      runs: file.runs.map((entry) => entry.record),
      missing: file.missing,
      enter: setFile,
      close: () => setFile(null),
    }
  }, [file])

  return <ImportedSessionContext.Provider value={value}>{children}</ImportedSessionContext.Provider>
}
