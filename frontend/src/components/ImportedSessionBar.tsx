import { useMemo, useState } from 'react'
import { SessionView } from '@/components/SessionView'
import { Dialog, DialogPopup, DialogTitle } from '@/components/ui/dialog'
import { useImportedSession } from '@/lib/sessionFile'
import type { RunDetail } from '@/lib/runs'

/**
 * The banner shown while an imported session file is the active view (see
 * lib/sessionFile.ts/ImportedSessionProvider). Close only clears the
 * imported session - see ImportedSessionProvider's doc comment for why
 * that alone is enough to restore whatever mode was active before the
 * import.
 *
 * "View session" renders the file's own session record through SessionView
 * - the same component the live workbench uses - fed straight from the
 * file's bundled curves/runs, with no fetch and no PATCH (readOnly).
 */
export function ImportedSessionBar() {
  const importedSession = useImportedSession()
  const [sessionOpen, setSessionOpen] = useState(false)

  // SessionView wants runDetails keyed by id; the file's own runs already
  // carry full samples (see sessionFile.ts's SessionRunEntry), so this is
  // just a reshape, never a fetch.
  const runDetails = useMemo(() => {
    const byId: Record<string, RunDetail> = {}
    for (const run of importedSession.runs) byId[run.id] = run
    return byId
  }, [importedSession.runs])

  if (!importedSession.active) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-500/30 bg-sky-500/10 px-4 py-1.5 text-xs font-medium text-sky-800 dark:text-sky-300">
      <span>
        Viewing: {importedSession.title || 'Untitled session'} - read-only, nothing here is saved
        or sent to a server.
      </span>
      <div className="flex shrink-0 items-center gap-2">
        {importedSession.session !== null && (
          <button
            type="button"
            onClick={() => setSessionOpen(true)}
            className="rounded-md border border-sky-500/40 px-2 py-0.5 hover:bg-sky-500/20"
          >
            View session
          </button>
        )}
        <button
          type="button"
          onClick={importedSession.close}
          className="rounded-md border border-sky-500/40 px-2 py-0.5 hover:bg-sky-500/20"
        >
          Close
        </button>
      </div>

      <Dialog open={sessionOpen} onOpenChange={setSessionOpen}>
        <DialogPopup className="max-w-3xl">
          <DialogTitle className="sr-only">Session</DialogTitle>
          {importedSession.session && (
            <SessionView
              session={importedSession.session}
              curves={importedSession.curves}
              runs={importedSession.runs}
              runDetails={runDetails}
              readOnly
            />
          )}
        </DialogPopup>
      </Dialog>
    </div>
  )
}
