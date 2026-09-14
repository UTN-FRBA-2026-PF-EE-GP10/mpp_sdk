// Display units for current and power, shared by every chart and readout
// so they can never disagree with each other on screen.
//
// The data itself is always amps and watts - that is what the curve
// library stores and what GET /api/curves serves (see api.ts's mA/A
// boundary note). This is purely a presentation choice: milliamps suit
// the lamp-lit bench, where a panel sources a couple of hundred mA, while
// amps suit real sun.
//
// Split from UnitsProvider.tsx so that file exports only a component,
// which is what React Fast Refresh wants.

import { createContext, useContext } from 'react'

export type UnitMode = 'milli' | 'base'

export const UNITS_STORAGE_KEY = 'mpp-sdk.units'

export interface UnitsValue {
  mode: UnitMode
  setMode: (mode: UnitMode) => void
  /** Multiplier taking stored amps/watts to the displayed unit. */
  factor: number
  currentLabel: string
  powerLabel: string
  formatCurrent: (amps: number) => string
  formatPower: (watts: number) => string
}

export const UnitsContext = createContext<UnitsValue | null>(null)

/** Builds the context value for `mode`. Three decimals in base units
 * keeps a 6 mA reading legible as 0.006 A rather than rounding it away. */
export function unitsValue(mode: UnitMode, setMode: (mode: UnitMode) => void): UnitsValue {
  const milli = mode === 'milli'
  return {
    mode,
    setMode,
    factor: milli ? 1000 : 1,
    currentLabel: milli ? 'mA' : 'A',
    powerLabel: milli ? 'mW' : 'W',
    formatCurrent: (amps) => (milli ? `${(amps * 1000).toFixed(1)} mA` : `${amps.toFixed(3)} A`),
    formatPower: (watts) => (milli ? `${(watts * 1000).toFixed(1)} mW` : `${watts.toFixed(3)} W`),
  }
}

export function useUnits(): UnitsValue {
  const value = useContext(UnitsContext)
  if (value === null) {
    throw new Error('useUnits must be used inside a UnitsProvider')
  }
  return value
}
