// Single/full bench setup, shared so the capture form, the run form's load
// hint, and the header toggle can never disagree about which rig is on the
// bench.
//
// Single: one panel (A) - the Luxen LN-10P session. Full: both panels, A
// fixed at 90 degrees and B on its tilt mount - today's default behaviour.
// This is a display/form choice only: it decides what a fresh capture
// saves and what hint the run form shows, nothing about how a captured
// curve or run is interpreted afterward.
//
// Split from SetupModeProvider.tsx so that file exports only a component,
// which is what React Fast Refresh wants - same reasoning as lib/units.ts.

import { createContext, useContext } from 'react'

export type SetupMode = 'single' | 'full'

export const SETUP_MODE_STORAGE_KEY = 'mpp-sdk.setup-mode'

export interface SetupModeValue {
  mode: SetupMode
  setMode: (mode: SetupMode) => void
}

export const SetupModeContext = createContext<SetupModeValue | null>(null)

export function useSetupMode(): SetupModeValue {
  const value = useContext(SetupModeContext)
  if (value === null) {
    throw new Error('useSetupMode must be used inside a SetupModeProvider')
  }
  return value
}
