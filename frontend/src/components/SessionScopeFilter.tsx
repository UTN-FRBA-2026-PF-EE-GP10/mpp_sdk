import { useCaptureSession, type SessionScope } from '@/lib/activeSession'

/**
 * "This session / Everything" switch for a Curves or Runs list. Offered only
 * while a session is active - without one there is nothing to narrow to.
 * The scope itself lives in the list, not here, so each list keeps its own.
 */
export function SessionScopeFilter({
  scope,
  onScopeChange,
}: {
  scope: SessionScope
  onScopeChange: (scope: SessionScope) => void
}) {
  const session = useCaptureSession()
  if (session === null) return null

  const options: { value: SessionScope; label: string }[] = [
    { value: 'session', label: 'This session' },
    { value: 'all', label: 'Everything' },
  ]

  return (
    <div
      role="group"
      aria-label="Show"
      className="inline-flex items-center gap-1 text-xs"
      title={`This session: "${session.title || session.id}"`}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={scope === o.value}
          onClick={() => onScopeChange(o.value)}
          className={
            scope === o.value
              ? 'rounded-md border border-primary bg-primary px-2 py-0.5 text-primary-foreground'
              : 'rounded-md border px-2 py-0.5 text-muted-foreground hover:bg-muted'
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
