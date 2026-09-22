// The error api.ts throws for a response that is not OK. Kept apart from
// api.ts so callers can tell "the server said 404" from "the network
// failed" without importing the fetch functions - and so tests that mock
// api.ts wholesale still get the real class.

export class ApiError extends Error {
  readonly status: number
  /** The server's `detail` text, without the "METHOD /path:" prefix that
   * `message` carries. */
  readonly detail: string

  constructor(message: string, status: number, detail: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** True for the server refusing a request because the `session_id` it
 * carried names no session - a session deleted in another tab, say. See
 * curve_tracer_server.py's `_session_path`. Not any 404: a run start also
 * answers 404 for a missing reference curve, and that is not this. */
export function isSessionNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404 && e.detail === 'session not found'
}
