import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogPopup, DialogTitle } from '@/components/ui/dialog'
import { useSession } from '@/lib/session'

/**
 * The banner shown while an imported session is the active view (see
 * lib/session.ts/SessionProvider). Close only clears the session - see
 * SessionProvider's doc comment for why that alone is enough to restore
 * whatever mode was active before the import.
 *
 * The report placeholder here is deliberate: Part C (the real report view)
 * is a separate, in-progress change. Until it lands, a session that
 * carries a report still says so, rather than silently dropping it.
 */
export function SessionViewBar() {
  const session = useSession()
  const [reportOpen, setReportOpen] = useState(false)

  if (!session.active) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-500/30 bg-sky-500/10 px-4 py-1.5 text-xs font-medium text-sky-800 dark:text-sky-300">
      <span>
        Viewing: {session.title || 'Untitled session'} - read-only, nothing here is saved or sent
        to a server.
      </span>
      <div className="flex shrink-0 items-center gap-2">
        {session.report !== null && (
          <button
            type="button"
            onClick={() => setReportOpen(true)}
            className="rounded-md border border-sky-500/40 px-2 py-0.5 hover:bg-sky-500/20"
          >
            View report
          </button>
        )}
        <button
          type="button"
          onClick={session.close}
          className="rounded-md border border-sky-500/40 px-2 py-0.5 hover:bg-sky-500/20"
        >
          Close
        </button>
      </div>

      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogPopup className="max-w-md">
          <DialogTitle>Report</DialogTitle>
          <p className="text-sm text-muted-foreground">
            This session contains a report; report view coming soon.
          </p>
          <Button variant="outline" size="sm" onClick={() => setReportOpen(false)} className="self-start">
            Close
          </Button>
        </DialogPopup>
      </Dialog>
    </div>
  )
}
