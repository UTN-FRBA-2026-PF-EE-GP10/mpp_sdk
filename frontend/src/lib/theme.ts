// Light/dark theme setting - "sun and moon": a warm near-white surface in
// light mode, a deep blue-black one at night. Persisted the same way
// lib/units.ts persists the unit mode (localStorage, wrapped in try/catch -
// a private window or blocked site data shouldn't fail a render).
//
// `resolvedDark` is the actual boolean the rest of the app needs (charts,
// most of all - see lib/chartConfig.ts): `mode` can be 'system', which
// isn't by itself an answer to "is it dark right now". Resolving that once
// here means chart code never has to touch matchMedia itself.

import { createContext, useContext } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'

export const THEME_STORAGE_KEY = 'mpp-sdk.theme'

export interface ThemeValue {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  resolvedDark: boolean
}

export const ThemeContext = createContext<ThemeValue | null>(null)

/** Whether `mode` currently means "dark", resolving 'system' against the
 * OS preference. Also used for ThemeProvider's initial state, so the very
 * first render already agrees with the inline no-flash script in
 * index.html instead of correcting itself a frame later. */
export function resolveDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true
  if (mode === 'light') return false
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext)
  if (value === null) {
    throw new Error('useTheme must be used inside a ThemeProvider')
  }
  return value
}
