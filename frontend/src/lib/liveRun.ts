// Pure logic behind the live-run setup/monitor (components/RunPane.tsx) -
// kept dependency-free and separate from polling/rendering, the same
// split runPlayback.ts makes for the run player.

// Only the first two are the safety system actually firing - 'stopped' is
// a deliberate operator action and 'link-down' is neither, so the wording
// only claims "safety cutoff" where that's literally what happened
// (see run_control_loop in scripts/run_algorithm.py).
const ABORT_REASON_MESSAGES: Record<string, string> = {
  overvoltage: 'the safety cutoff fired - panel voltage exceeded the v_max limit.',
  overcurrent: 'the safety cutoff fired - panel current exceeded the i_max limit.',
  'link-down': 'the link to the board was lost mid-run.',
  stopped: 'stopped by the operator.',
}

/** A one-line, human explanation of why a run ended early - the four
 * reasons `run_control_loop` (scripts/run_algorithm.py) can report, or the
 * reason text verbatim for the rarer free-text ones (an unexpected
 * exception, a save that failed). `null` reads as "reason unknown", not as
 * "not aborted" - callers only reach for this once `aborted` is already
 * true. */
export function abortReasonMessage(reason: string | null): string {
  if (reason === null) return 'no reason was recorded.'
  return ABORT_REASON_MESSAGES[reason] ?? reason
}
