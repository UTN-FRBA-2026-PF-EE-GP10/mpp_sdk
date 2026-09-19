import { useState, type DragEvent } from 'react'
import { readSessionFile, useSession, type SessionFile } from '@/lib/session'

/**
 * One place that turns a `File` (from the Open-session control or a page
 * drop) into an imported session, or a clear error - shared so the two
 * entry points can never validate differently. A failed import leaves the
 * current view untouched: `session.enter` is only called once
 * `readSessionFile` has already thrown or succeeded.
 */
export function useSessionFileImport(onImported?: (session: SessionFile) => void) {
  const session = useSession()
  const [error, setError] = useState<string | null>(null)

  async function importFile(file: File) {
    setError(null)
    try {
      const parsed = await readSessionFile(file)
      session.enter(parsed)
      // Fired from the same event that caused the change, not derived
      // later in an effect - lets App.tsx pick a sensible first thing to
      // show (the session's own content, not the now-inert Measure pane)
      // without re-deriving it from state on every render.
      onImported?.(parsed)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) void importFile(file)
  }

  function handleDragOver(e: DragEvent) {
    // Without this, the browser's default is to reject the drop entirely.
    e.preventDefault()
  }

  return {
    error,
    dismissError: () => setError(null),
    importFile,
    handleDrop,
    handleDragOver,
  }
}
