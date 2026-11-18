import { useState } from 'react'
import { LAMP_DEFAULT_WARMUP_S, LAMP_MAX_ON_S, clampWarmupS, type LampRequest } from '@/lib/lamp'
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
  const onTimeS = durationS == null ? null : warmupS + durationS

  let blockReason: string | null = null
  if (checked) {
    if (unavailableReason) blockReason = unavailableReason
    else if (onTimeS != null && onTimeS > LAMP_MAX_ON_S)
      blockReason = `The lamp would be on for ${Math.round(onTimeS)} s (warm-up plus run). The limit is ${LAMP_MAX_ON_S} s: shorten the run or the warm-up.`
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
