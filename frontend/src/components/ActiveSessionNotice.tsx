import { useCaptureSession } from '@/lib/activeSession'
import { useReadOnly } from '@/lib/sessionFile'

/**
 * The in-pane counterpart of ActiveSessionBar: the Measure pane and the run
 * form say where the next capture will be filed, right where the operator
 * presses Start. Says so both ways - "not filed into any session" is the
 * state that causes the confusion this exists to prevent.
 *
 * Renders nothing in demo mode and while viewing an imported session file,
 * where nothing is written.
 */
export function ActiveSessionNotice({ what }: { what: 'curve' | 'run' }) {
  const session = useCaptureSession()
  const readOnly = useReadOnly()
  if (readOnly.enabled) return null
  const noun = what === 'curve' ? 'curve' : 'run'
  return session === null ? (
    <p className="text-xs text-muted-foreground" data-testid="active-session-notice">
      Not filed into any session - open a session to file the next {noun} into it.
    </p>
  ) : (
    <p
      className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300"
      data-testid="active-session-notice"
    >
      This {noun} will be filed into session &ldquo;{session.title || session.id}&rdquo;.
    </p>
  )
}
