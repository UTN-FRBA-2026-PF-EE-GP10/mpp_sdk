import { useState } from 'react'
import {
  LAMP_DEFAULT_WARMUP_S,
  LAMP_STEP_MARGIN_S,
  LAMP_STEP_MAX_ON_S,
  clampWarmupS,
  parseLampPhase,
  type LampPhase,
  type LampRequest,
} from '@/lib/lamp'
import { fetchLiveRun, fetchLiveSweep } from '@/lib/api'
import { usePolling } from '@/hooks/usePolling'
import { lampUnavailableReason, useLampShared } from '@/lib/lampContext'

/** `durationS` of a run is null while it is not known yet (config not loaded). */
export type LampOptionTarget = { kind: 'sweep' } | { kind: 'run'; durationS: number | null }

/** State of "Use the lamp for this measurement". It lives in the form that
 * owns it, so it is remembered for the tab only and never stored. */
export function useLampOption(target: LampOptionTarget) {
  const lamp = useLampShared()
  const [checked, setChecked] = useState(false)
  // null follows the lamp card slider until the operator types a value here.
  const [ownPct, setOwnPct] = useState<number | null>(null)
  const [warmupText, setWarmupText] = useState(String(LAMP_DEFAULT_WARMUP_S))

  const unavailableReason = lampUnavailableReason(lamp)
  const maxPct =
    lamp.status && Number.isFinite(lamp.status.max_power)
      ? Math.min(100, Math.max(0, Math.floor(lamp.status.max_power * 100)))
      : 100
  const powerPct = Math.min(ownPct ?? lamp.powerPct, maxPct)
  const warmupS = clampWarmupS(Number(warmupText))

  const durationS = target.kind === 'run' ? target.durationS : null
  const onTimeS = durationS == null ? null : warmupS + durationS + LAMP_STEP_MARGIN_S

  let blockReason: string | null = null
  if (checked) {
    if (unavailableReason) blockReason = unavailableReason
    else if (powerPct <= 0) blockReason = 'The lamp power is 0 %: raise it above 0.'
    else if (onTimeS != null && onTimeS > LAMP_STEP_MAX_ON_S)
      blockReason = `The lamp would be on for ${Math.round(onTimeS)} s (warm-up, run and ${LAMP_STEP_MARGIN_S} s margin). The limit is ${LAMP_STEP_MAX_ON_S} s: shorten the run or the warm-up.`
  }

  const request: LampRequest | null =
    checked && !blockReason ? { power: powerPct / 100, warmup_s: warmupS } : null

  return {
    checked,
    setChecked,
    powerPct,
    setPowerPct: setOwnPct,
    maxPct,
    warmupText,
    setWarmupText,
    warmupS,
    onTimeS,
    unavailableReason,
    blockReason,
    request,
  }
}

export type LampOption = ReturnType<typeof useLampOption>

/** The lamp phase of the other kind of measurement (a run for a sweep form
 * and the reverse), read once a second. Only a warm-up there blocks Start:
 * the server answers 409 while a lamp-assisted step is in progress. A fetch
 * failure counts as no phase. Idle when `enabled` is false. */
export function useOtherStepPhase(own: 'sweep' | 'run', enabled: boolean): LampPhase | null {
  const [phase, setPhase] = useState<LampPhase | null>(null)
  usePolling(
    async () => {
      const data = own === 'sweep' ? await fetchLiveRun() : await fetchLiveSweep()
      return parseLampPhase((data as { lamp_phase?: unknown; lampPhase?: unknown }).lamp_phase ??
        (data as { lampPhase?: unknown }).lampPhase)
    },
    setPhase,
    () => setPhase(null),
    1000,
    enabled,
  )
  return phase
}

/** Why Start must wait because of a lamp-assisted step, or null. */
export function stepBusyReason(own: LampPhase | null, other: LampPhase | null): string | null {
  if (own === 'warming' || own === 'measuring' || other === 'warming')
    return 'A lamp-assisted measurement is in progress.'
  return null
}
