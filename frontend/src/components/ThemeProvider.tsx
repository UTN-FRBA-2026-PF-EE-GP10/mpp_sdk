import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { resolveDark, THEME_STORAGE_KEY, ThemeContext, type ThemeMode, type ThemeValue } from '@/lib/theme'

function readStoredMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

/** Supplies the page-wide light/dark/system setting and keeps the `dark`
 * class on `<html>` in sync with it - see lib/theme.ts and index.html's
 * inline script (which applies the stored choice before this ever mounts,
 * so there's no flash of the wrong theme on load). */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readStoredMode)
  const [resolvedDark, setResolvedDark] = useState<boolean>(() => resolveDark(mode))

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, mode)
    } catch {
      // A remembered preference is a convenience, not state depended on.
    }
  }, [mode])

  useEffect(() => {
    let media: MediaQueryList | null = null
    function apply() {
      const dark = resolveDark(mode)
      document.documentElement.classList.toggle('dark', dark)
      setResolvedDark(dark)
    }
    apply()
    // Only 'system' needs to track a live OS change - 'light'/'dark' are
    // pinned regardless of what the OS is doing.
    if (mode !== 'system') return
    try {
      media = window.matchMedia('(prefers-color-scheme: dark)')
      media.addEventListener('change', apply)
    } catch {
      // matchMedia can be missing in a very old or synthetic environment -
      // 'system' just won't live-update there, which is a fallback, not a
      // crash.
    }
    return () => media?.removeEventListener('change', apply)
  }, [mode])

  const value = useMemo<ThemeValue>(() => ({ mode, setMode, resolvedDark }), [mode, resolvedDark])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
