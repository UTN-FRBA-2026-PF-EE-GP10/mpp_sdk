// The three ways the capture pane can be driven - named to match
// mpp_sdk/curves/record.py's CURVE_SOURCES exactly, so the mode selector
// and a saved curve's provenance can never drift apart. "Demo" is
// overloaded elsewhere in this app (a fourth, server-side meaning lives in
// ConnectionStatus's own 'demo' value - see ConnectionIndicator.tsx), so
// each on-screen label below has to be tellable apart from the others at
// a glance, not just from its internal name:
//
//   'hardware'         PICO connected      - Start Measurement: a real
//                       sweep off a real panel.
//   'firmware-replay'  Replay on the board - the "Replay curve" buttons:
//                       real SPI, a curve already stored in the firmware,
//                       not measured this session. Requires a live link
//                       to the Pi - there's nothing to replay from
//                       without one.
//   'simulated'        Demo                - no board at all. Bundled
//                       fixtures (lib/demoFixtures.ts), replayed locally
//                       (hooks/useDemoCapture.ts). Called "sandbox" in
//                       code (lib/sandbox.ts) to avoid colliding with
//                       ConnectionStatus's own 'demo' value ("Simulated
//                       board" on screen - the server's --demo flag, a
//                       simulated sweep source standing in for a board).
//
// A curve captured or replayed under a given mode is stamped with exactly
// that CURVE_SOURCES value - that's the whole point of `source` existing
// (see ProvenanceBadge): a replay must never be mistaken for a
// measurement, so the mode you picked and the label the curve carries
// forever after must be the same word.

import { createContext, useContext } from 'react'

export type CaptureMode = 'hardware' | 'firmware-replay' | 'simulated'

export const CAPTURE_MODE_STORAGE_KEY = 'mpp-sdk.capture-mode'

export const CAPTURE_MODE_LABEL: Record<CaptureMode, string> = {
  // Named for the PICO, not the Pi: the workbench is normally opened on
  // the Pi itself, where "is the Pi connected" is not a question anyone
  // needs answered. What matters is whether the external board is there.
  hardware: 'PICO connected',
  'firmware-replay': 'Replay on the board',
  simulated: 'Demo',
}

export function isCaptureMode(value: unknown): value is CaptureMode {
  return value === 'hardware' || value === 'firmware-replay' || value === 'simulated'
}

export interface CaptureModeValue {
  mode: CaptureMode
  setMode: (mode: CaptureMode) => void
}

// Defaults to 'hardware' - the same fully-capable, unrestricted behaviour
// the app always had before this selector existed - rather than throwing
// outside a provider. A component that renders without CaptureModeProvider
// (a test, most likely) must fail safe into "acts like production with no
// demo mode", never into a crash or a silently-stuck restricted mode.
const DEFAULT_CAPTURE_MODE_VALUE: CaptureModeValue = { mode: 'hardware', setMode: () => {} }

export const CaptureModeContext = createContext<CaptureModeValue>(DEFAULT_CAPTURE_MODE_VALUE)

export function useCaptureMode(): CaptureModeValue {
  return useContext(CaptureModeContext)
}
