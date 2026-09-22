import { useActiveSession, useCaptureSession } from '@/lib/activeSession'

/**
 * The banner that says which session new captures are being filed into,
 * visible from every section - the operator must never have to remember
 * which session is active. Dismissing it stops the filing; the curves and
 * runs already stamped are untouched.
 *
 * Hidden in demo mode and while viewing an imported session file: nothing
 * is written there, so nothing is filed (see useCaptureSession).
 */
export function ActiveSessionBar({ onOpen }: { onOpen?: (sessionId: string) => void }) {
  const session = useCaptureSession()
  const { clear } = useActiveSession()

  if (session === null) return null

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-500/30 bg-emerald-500/10 px-4 py-1.5 text-xs font-medium text-emerald-800 dark:text-emerald-300 print:hidden"
    >
      <span>
        Filing new captures into session &ldquo;{session.title || session.id}&rdquo;.
      </span>
      <div className="flex shrink-0 items-center gap-2">
        {onOpen && (
          <button
            type="button"
            onClick={() => onOpen(session.id)}
            className="rounded-md border border-emerald-500/40 px-2 py-0.5 hover:bg-emerald-500/20"
          >
            Open session
          </button>
        )}
        <button
          type="button"
          onClick={clear}
          className="rounded-md border border-emerald-500/40 px-2 py-0.5 hover:bg-emerald-500/20"
        >
          Stop filing
        </button>
      </div>
    </div>
  )
}
