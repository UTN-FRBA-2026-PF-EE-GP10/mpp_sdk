import { createContext, useContext } from 'react'
import type { LampHook } from '@/hooks/useLamp'

/** One lamp poll shared by the card and the measurement options. */
export interface LampShared extends LampHook {
  /** Lamp card slider, in percent. The measurement options start from it. */
  powerPct: number
  setPowerPct: (pct: number) => void
  /** Demo mode: there is no lamp to ask. */
  demo: boolean
}

// Outside a provider there is no lamp: status stays null.
const NO_LAMP: LampShared = {
  status: null,
  receivedAt: 0,
  failures: 0,
  stale: false,
  busy: false,
  message: null,
  turnOn: async () => {},
  turnOff: async () => {},
  powerPct: 30,
  setPowerPct: () => {},
  demo: false,
}

export const LampContext = createContext<LampShared>(NO_LAMP)

export function useLampShared(): LampShared {
  return useContext(LampContext)
}

/** Why the lamp cannot be used for a measurement now, or null when it can. */
export function lampUnavailableReason(lamp: LampShared): string | null {
  if (lamp.demo) return 'The lamp is not available in Demo mode.'
  const s = lamp.status
  if (!s) return 'The lamp status is not known yet.'
  if (lamp.failures > 0 || lamp.stale)
    return 'The lamp status is unknown: no answer from the server.'
  if (!s.available || !s.link_ok)
    return `The lamp is not available${s.error ? `: ${s.error}` : ''}.`
  if (s.tripped || s.state === 'tripped')
    return 'The lamp is tripped. Wait, press Off on the lamp card, then try again.'
  return null
}
