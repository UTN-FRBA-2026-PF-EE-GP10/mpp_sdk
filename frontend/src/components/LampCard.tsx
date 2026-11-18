import { CircleSlash, Lightbulb, LightbulbOff, ShieldAlert, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { UNKNOWN_AFTER_FAILURES, useLamp } from '@/hooks/useLamp'
import { useCaptureMode } from '@/lib/captureMode'
import {
  LAMP_DEFAULT_POWER_PCT,
  LAMP_DEFAULT_WINDOW_S,
  LAMP_MAX_WINDOW_S,
  LAMP_MIN_WINDOW_S,
  alphaDegForPower,
  clampWindowS,
} from '@/lib/lamp'

type BadgeKey = 'off' | 'on' | 'tripped' | 'nolink'

const BADGES = {
  off: { label: 'OFF', Icon: LightbulbOff, cls: '' },
  on: {
    label: 'ON',
    Icon: Lightbulb,
    cls: 'border-amber-500/50 text-amber-700 dark:text-amber-400',
  },
  tripped: { label: 'TRIPPED', Icon: ShieldAlert, cls: 'border-destructive/50 text-destructive' },
  nolink: { label: 'NO LINK', Icon: WifiOff, cls: 'border-destructive/50 text-destructive' },
} as const

/** Lamp control: a bounded exposure window, never a latching switch. */
export function LampCard() {
  const { mode } = useCaptureMode()
  const demo = mode === 'simulated'
  const { status, receivedAt, failures, busy, message, turnOn, turnOff } = useLamp(!demo)
  const [powerPct, setPowerPct] = useState(LAMP_DEFAULT_POWER_PCT)
  const [windowText, setWindowText] = useState(String(LAMP_DEFAULT_WINDOW_S))
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [])

  const unknown = failures >= UNKNOWN_AFTER_FAILURES
  const pollFailing = failures > 0
  const maxPct = status ? Math.max(0, Math.floor(status.max_power * 100)) : 100
  const shownPct = Math.min(powerPct, maxPct)
  const alpha = alphaDegForPower(shownPct / 100)
  const windowS = clampWindowS(Number(windowText))
  const windowOutOfRange =
    windowText.trim() !== '' &&
    (Number(windowText) < LAMP_MIN_WINDOW_S || Number(windowText) > LAMP_MAX_WINDOW_S)

  let badge: BadgeKey = 'off'
  if (pollFailing || (status && (!status.available || !status.link_ok))) badge = 'nolink'
  else if (status?.tripped || status?.state === 'tripped') badge = 'tripped'
  else if (status?.state === 'on') badge = 'on'

  const elapsedS = (now - receivedAt) / 1000
  // A stale reading must not drive a countdown that looks alive.
  const live = status && !pollFailing
  const windowLeft =
    live && status.state === 'on' && status.window_left_s != null
      ? Math.max(0, Math.ceil(status.window_left_s - elapsedS))
      : null
  const budgetLeft =
    live && status.budget_s != null
      ? Math.max(
          0,
          Math.ceil(
            status.state === 'on' || status.tripped
              ? status.budget_s - elapsedS
              : status.budget_s,
          ),
        )
      : null

  const canOn =
    !demo && !!status && status.available && status.link_ok && !status.tripped &&
    !pollFailing && !busy
  const Icon = BADGES[badge].Icon

  let notice: string | null = null
  if (demo) notice = 'Lamp not available in Demo mode.'
  else if (unknown) notice = 'Lamp status unknown: no answer from the server. Press Off to be sure.'
  else if (status && !status.available)
    notice = `Lamp not available${status.error ? `: ${status.error}` : ''}`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Lightbulb className="size-5 text-primary" aria-hidden="true" />
          Lamp
          <Badge variant="outline" className={BADGES[badge].cls}>
            <Icon aria-hidden="true" />
            <span aria-live="polite" aria-atomic="true" data-testid="lamp-state">
              {BADGES[badge].label}
            </span>
          </Badge>
          {status && !pollFailing && status.available && (
            <>
              <Badge variant="outline">{status.mains ? 'Mains present' : 'No mains'}</Badge>
              {status.locked && <Badge variant="outline">Locked</Badge>}
              {status.timed_out && <Badge variant="outline">Timed out</Badge>}
            </>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <CircleSlash className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          The board switches mains voltage. The lamp turns itself off at the end of the window.
        </p>

        {notice && (
          <p className="text-sm font-medium text-destructive" role="alert">
            {notice}
          </p>
        )}

        {status?.tripped && !pollFailing && (
          <p className="text-sm font-medium text-destructive" role="alert">
            {(budgetLeft ?? 0) > 0
              ? `Tripped: the lamp is off to protect the lamp and the panels. Wait ${budgetLeft} s, then press Off and ask again`
              : 'Tripped: the lamp is off to protect the lamp and the panels. Cooled down: press Off, then ask again'}
          </p>
        )}

        <div className="flex flex-wrap items-end gap-4">
          <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm text-muted-foreground">
            <span>
              Power: {shownPct} % (firing angle {alpha.toFixed(1)} deg)
            </span>
            <input
              type="range"
              min={0}
              max={maxPct}
              step={1}
              value={shownPct}
              onChange={(e) => setPowerPct(Number(e.target.value))}
              aria-valuetext={`${shownPct} percent, firing angle ${alpha.toFixed(1)} degrees`}
            />
            {maxPct < 100 && (
              <span className="text-xs">Server limit: {maxPct} % at most.</span>
            )}
          </label>
          <label className="flex w-36 flex-col gap-1 text-sm text-muted-foreground">
            Window (s)
            <input
              type="number"
              min={LAMP_MIN_WINDOW_S}
              max={LAMP_MAX_WINDOW_S}
              step={1}
              value={windowText}
              onChange={(e) => setWindowText(e.target.value)}
              onBlur={() => setWindowText(String(windowS))}
              className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
            />
            <span className="text-xs">
              {LAMP_MIN_WINDOW_S} to {LAMP_MAX_WINDOW_S} s
              {windowOutOfRange ? `, using ${windowS} s` : ''}
            </span>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={!canOn} onClick={() => turnOn(shownPct / 100, windowS)}>
            Lamp on
          </Button>
          <Button variant="destructive" onClick={() => turnOff()}>
            Off
          </Button>
          {windowLeft != null && (
            <span className="text-sm tabular-nums">Window left: {windowLeft} s</span>
          )}
          {budgetLeft != null && !status?.tripped && (
            <span className="text-sm tabular-nums text-muted-foreground">
              Lamp on time left: {budgetLeft} s
            </span>
          )}
        </div>

        {message && (
          <p className="text-sm text-destructive" role="alert">
            {message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
