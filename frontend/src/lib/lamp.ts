// Lamp helpers. The dimmer takes a firing angle, the operator thinks in
// lamp power, so the card converts with the same law as
// mpp_sdk/io/dimmer.py (phase cut of a resistive load).

export const LAMP_DEFAULT_POWER_PCT = 30
export const LAMP_DEFAULT_WINDOW_S = 30
export const LAMP_MIN_WINDOW_S = 1
export const LAMP_MAX_WINDOW_S = 120

// Lamp use around one measurement (sweep or run). The server lights the
// lamp, waits for the warm-up, measures and switches the lamp off again.

/** The server refuses a step when warm-up + duration + margin is over the max. */
export const LAMP_STEP_MAX_ON_S = 110
export const LAMP_STEP_MARGIN_S = 5
export const LAMP_DEFAULT_WARMUP_S = 3
export const LAMP_MAX_WARMUP_S = 30

/** The `lamp` object of a sweep or run start request. */
export interface LampRequest {
  power: number
  warmup_s: number
}

export type LampPhase = 'warming' | 'measuring' | 'off'

/** Anything the server sends that is not a known phase counts as no phase. */
export function parseLampPhase(value: unknown): LampPhase | null {
  return value === 'warming' || value === 'measuring' || value === 'off' ? value : null
}

export function parseWarmupLeft(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : null
}

/** Warm-up seconds forced into 0..30; NaN falls back to the default. */
export function clampWarmupS(value: number): number {
  if (!Number.isFinite(value)) return LAMP_DEFAULT_WARMUP_S
  return Math.min(LAMP_MAX_WARMUP_S, Math.max(0, Math.round(value)))
}

/** The status line for a lamp-assisted step, or null when there is nothing to say. */
export function lampPhaseText(
  phase: LampPhase | null,
  warmupLeftS: number | null,
  running = true,
): string | null {
  if (phase === 'warming') {
    return warmupLeftS == null
      ? 'Warming up the lamp'
      : `Warming up the lamp, ${Math.ceil(warmupLeftS)} s`
  }
  if (phase === 'measuring') return 'Lamp on for the measurement'
  if (phase === 'off' && running)
    return 'The lamp is off, this measurement is running without light'
  return null
}

/** Fraction of full power at firing angle `alphaRad`: 1 - a/pi + sin(2a)/(2pi). */
export function powerForAlpha(alphaRad: number): number {
  return 1 - alphaRad / Math.PI + Math.sin(2 * alphaRad) / (2 * Math.PI)
}

/** Firing angle in degrees for a power fraction 0..1 (bisection: the power
 * falls monotonically as the angle grows). 0 gives 180, 1 gives 0. */
export function alphaDegForPower(power: number): number {
  const p = Math.min(1, Math.max(0, power))
  if (p <= 0) return 180
  if (p >= 1) return 0
  let lo = 0
  let hi = Math.PI
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    if (powerForAlpha(mid) > p) lo = mid
    else hi = mid
  }
  return (((lo + hi) / 2) * 180) / Math.PI
}

/** Window length in seconds forced into the allowed range; NaN falls back to the default. */
export function clampWindowS(value: number): number {
  if (!Number.isFinite(value)) return LAMP_DEFAULT_WINDOW_S
  return Math.min(LAMP_MAX_WINDOW_S, Math.max(LAMP_MIN_WINDOW_S, Math.round(value)))
}
