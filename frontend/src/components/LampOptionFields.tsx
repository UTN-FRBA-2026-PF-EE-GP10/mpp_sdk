import type { LampOption } from '@/hooks/useLampOption'
import { LAMP_MAX_WARMUP_S, LAMP_STEP_MARGIN_S, lampPhaseText, type LampPhase } from '@/lib/lamp'

/** "Use the lamp for this measurement": the lamp is on only around the
 * sweep or run, lit and switched off by the server. */
export function LampOptionFields({ option }: { option: LampOption }) {
  const disabled = option.unavailableReason !== null
  return (
    <div className="flex flex-col gap-2 text-sm">
      <label className="flex items-center gap-2 text-foreground">
        <input
          type="checkbox"
          checked={option.checked}
          disabled={disabled}
          onChange={(e) => option.setChecked(e.target.checked)}
        />
        Use the lamp for this measurement
      </label>
      {disabled && <p className="text-xs text-muted-foreground">{option.unavailableReason}</p>}
      {option.checked && (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex min-w-[200px] flex-col gap-1 text-muted-foreground">
              <span>Lamp power: {option.powerPct} %</span>
              <input
                type="range"
                min={0}
                max={option.maxPct}
                step={1}
                value={option.powerPct}
                onChange={(e) => option.setPowerPct(Number(e.target.value))}
              />
            </label>
            <label className="flex w-32 flex-col gap-1 text-muted-foreground">
              Warm-up (s)
              <input
                type="number"
                min={0}
                max={LAMP_MAX_WARMUP_S}
                step={1}
                value={option.warmupText}
                onChange={(e) => option.setWarmupText(e.target.value)}
                onBlur={() => option.setWarmupText(String(option.warmupS))}
                className="rounded-md border bg-transparent px-2 py-1.5 text-foreground"
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            {option.onTimeS == null
              ? `Lamp on: ${option.warmupS} s warm-up, then until the sweep ends.`
              : `Lamp on for about ${Math.round(option.onTimeS)} s (${option.warmupS} s warm-up, the run and ${LAMP_STEP_MARGIN_S} s margin).`}
          </p>
          {option.blockReason && !disabled && (
            <p className="text-sm font-medium text-destructive" role="alert">
              {option.blockReason}
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** Live line while a lamp-assisted step runs. */
export function LampPhaseLine({
  phase,
  warmupLeftS,
  running,
}: {
  phase: LampPhase | null
  warmupLeftS: number | null
  /** The measurement is still running: only then does "off" need a line. */
  running: boolean
}) {
  const text = lampPhaseText(phase, warmupLeftS, running)
  if (!text) return null
  return (
    <p className="text-sm font-medium text-amber-700 dark:text-amber-400" aria-live="polite">
      {text}
    </p>
  )
}
