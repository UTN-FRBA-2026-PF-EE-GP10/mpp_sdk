// The bench session new captures are filed into. A curve saved from
// Measure, or a run started from it, is stamped with this session's id
// (`session_id` on POST /api/save-curve and POST /api/runs/start), so the
// session can later show what was measured for it.
//
// A client concept on purpose: the server keeps no "current session", the
// id travels with each request - two browsers must not fight over one.
// It is remembered in localStorage only so a page reload does not silently
// stop filing into the session the operator was working on.
//
// A stamp is not ownership. Clearing or deleting the active session never
// touches the curves and runs already stamped with it.
//
// Split from ActiveSessionProvider.tsx so that file exports only a
// component, which is what React Fast Refresh wants - same reasoning as
// lib/setupMode.ts.

import { createContext, useContext } from 'react'
import { useReadOnly } from '@/lib/sessionFile'

export const ACTIVE_SESSION_STORAGE_KEY = 'mpp-sdk.active-session'

export interface ActiveSession {
  id: string
  /** Kept next to the id so the indicator and the Measure pane can name
   * the session without each fetching the session list. */
  title: string
}

export interface ActiveSessionValue {
  active: ActiveSession | null
  /** Makes `id` the session captures are filed into. */
  setActive: (id: string, title: string) => void
  /** Stops filing into any session. Existing stamps stay as they are. */
  clear: () => void
}

// Fails safe the same way CaptureModeContext does: a component rendered
// without the provider (most tests) files nothing rather than throwing.
const NO_ACTIVE_SESSION: ActiveSessionValue = {
  active: null,
  setActive: () => {},
  clear: () => {},
}

export const ActiveSessionContext = createContext<ActiveSessionValue>(NO_ACTIVE_SESSION)

export function useActiveSession(): ActiveSessionValue {
  return useContext(ActiveSessionContext)
}

/** The session a capture would be filed into right now: the active one,
 * except in demo mode and while viewing an imported session file, where
 * nothing is written and so nothing is filed. The one place that rule is
 * decided - read this, not `useActiveSession`, anywhere a request is built
 * or a "filing into" notice is shown. */
export function useCaptureSession(): ActiveSession | null {
  const { active } = useActiveSession()
  const readOnly = useReadOnly()
  return readOnly.enabled ? null : active
}

/** Parses what is in localStorage, ignoring anything that is not an
 * `{id, title}` pair of strings - a stale or hand-edited value must not
 * become a session id sent to the server. */
export function parseStoredActiveSession(raw: string | null): ActiveSession | null {
  if (raw === null) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null) return null
    const { id, title } = value as Record<string, unknown>
    if (typeof id !== 'string' || id === '' || typeof title !== 'string') return null
    return { id, title }
  } catch {
    return null
  }
}

export type SessionScope = 'session' | 'all'

/** What a Curves or Runs list shows: everything, or only what was stamped
 * with the active session. A stamp naming a session that no longer exists
 * matches nothing here and so shows up under "everything" only - it is
 * never an error. */
export function filterToSession<T extends { session_id?: string | null }>(
  items: T[],
  scope: SessionScope,
  sessionId: string | null,
): T[] {
  if (scope === 'all' || sessionId === null) return items
  return items.filter((item) => item.session_id === sessionId)
}
