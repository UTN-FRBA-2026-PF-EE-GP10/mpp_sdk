import { useMemo, useState, type ReactNode } from 'react'
import { useLamp } from '@/hooks/useLamp'
import { useCaptureMode } from '@/lib/captureMode'
import { LAMP_DEFAULT_POWER_PCT } from '@/lib/lamp'
import { LampContext, type LampShared } from '@/lib/lampContext'

/** Polls the lamp once for everything below it: the card and the options
 * on the sweep and run start. `active` false stops the polling. */
export function LampProvider({
  active = true,
  children,
}: {
  active?: boolean
  children: ReactNode
}) {
  const { mode } = useCaptureMode()
  const demo = mode === 'simulated'
  const lamp = useLamp(!demo && active)
  const [powerPct, setPowerPct] = useState(LAMP_DEFAULT_POWER_PCT)
  const value = useMemo<LampShared>(
    () => ({ ...lamp, powerPct, setPowerPct, demo }),
    [lamp, powerPct, demo],
  )
  return <LampContext.Provider value={value}>{children}</LampContext.Provider>
}
