// The boolean most of the app actually needs: "is capture fully offline
// right now" - true only for CaptureMode's 'simulated' value (on screen:
// "Demo"). CurveWorkbench, RunPlayerDialog and App.tsx don't care which of
// the other two modes ('hardware' vs 'firmware-replay') is active - both
// are equally "live" as far as gating writes and hardware commands goes,
// since 'firmware-replay' still requires and uses a real link. Only
// 'simulated' turns writes and hardware commands off.
//
// See lib/captureMode.ts for the three-mode selector this derives from,
// and for why "sandbox" is this codebase's code-only name for 'simulated'
// (kept apart from ConnectionStatus's own 'demo' value and this mode's
// on-screen name, "Demo").

import { useCaptureMode } from './captureMode'

export interface SandboxValue {
  enabled: boolean
}

/** Read this - not `ConnectionStatus`, not a scattered prop - anywhere a
 * control needs to know "are we fully offline in demo mode". One hook so
 * the gating rule (no writes, no hardware commands) can only be expressed
 * one way. */
export function useSandbox(): SandboxValue {
  const { mode } = useCaptureMode()
  return { enabled: mode === 'simulated' }
}
