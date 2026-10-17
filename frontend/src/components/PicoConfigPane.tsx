import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Power,
  RefreshCw,
  RotateCcw,
  Send,
  Shield,
  ShieldAlert,
  Sliders,
  Thermometer,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  fetchPicoConfig,
  resetPicoCutoff,
  sendPicoConfig,
  type PicoConfig,
  type SendPicoConfigInput,
} from '@/lib/api'
import { useCaptureMode } from '@/lib/captureMode'
import { DEMO_PICO_CONFIG } from '@/lib/demoFixtures'
import { cn } from '@/lib/utils'

export type ConfigFieldKey =
  | 'vin_range'
  | 'vout_range'
  | 'ron_mohm'
  | 'max31865'
  | 'i_max_ma'
  | 'v_max_mv'
  | 'psu_mode'
  | 'psu_vout_target_mv'
  | 'psu_fixed_duty'

export function PicoConfigPane({
  connected = true,
}: {
  connected?: boolean
}) {
  const { mode: captureMode } = useCaptureMode()
  const isDemo = captureMode === 'simulated'

  const [activeConfig, setActiveConfig] = useState<PicoConfig>(DEMO_PICO_CONFIG.config)
  const [defaults, setDefaults] = useState<PicoConfig>(DEMO_PICO_CONFIG.defaults)
  const [loading, setLoading] = useState(false)
  const [sendingBatch, setSendingBatch] = useState(false)
  const [sendingSingle, setSendingSingle] = useState<string | null>(null)
  const [resettingCutoff, setResettingCutoff] = useState(false)
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error'
    message: string
  } | null>(null)

  // Selection checkboxes for which configs to include in the batch send
  const [selectedFields, setSelectedFields] = useState<Record<ConfigFieldKey, boolean>>({
    vin_range: true,
    vout_range: true,
    ron_mohm: false,
    max31865: false,
    i_max_ma: true,
    v_max_mv: true,
    psu_mode: false,
    psu_vout_target_mv: false,
    psu_fixed_duty: false,
  })

  // Editable form values
  const [vinRange, setVinRange] = useState<'low' | 'mid' | 'full'>('low')
  const [voutRange, setVoutRange] = useState<'low' | 'mid' | 'full'>('low')
  const [ronMohm, setRonMohm] = useState<number>(6)
  const [max31865, setMax31865] = useState<boolean>(false)
  const [iMaxMa, setIMaxMa] = useState<number>(1000)
  const [vMaxMv, setVMaxMv] = useState<number>(40000)
  const [psuEnabled, setPsuEnabled] = useState<boolean>(false)
  const [psuOpenLoop, setPsuOpenLoop] = useState<boolean>(false)
  const [psuVoutTargetMv, setPsuVoutTargetMv] = useState<number>(5000)
  const [psuFixedDuty, setPsuFixedDuty] = useState<number>(0.5)

  // Fetch initial config from server
  const loadConfig = async () => {
    if (isDemo) {
      setActiveConfig(DEMO_PICO_CONFIG.config)
      setDefaults(DEMO_PICO_CONFIG.defaults)
      return
    }
    setLoading(true)
    try {
      const res = await fetchPicoConfig()
      setActiveConfig(res.config)
      setDefaults(res.defaults)

      const normalizeRange = (val: string | number): 'low' | 'mid' | 'full' => {
        if (val === 0 || val === 'full') return 'full'
        if (val === 1 || val === 'mid') return 'mid'
        return 'low'
      }

      setVinRange(normalizeRange(res.config.vin_range))
      setVoutRange(normalizeRange(res.config.vout_range))
      setRonMohm(res.config.ron_mohm)
      setMax31865(res.config.max31865)
      setIMaxMa(res.config.i_max_ma)
      setVMaxMv(res.config.v_max_mv)
      setPsuEnabled(res.config.psu_enabled)
      setPsuOpenLoop(res.config.psu_open_loop)
      setPsuVoutTargetMv(res.config.psu_vout_target_mv)
      setPsuFixedDuty(res.config.psu_fixed_duty)
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to fetch Pico configuration',
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDemo])

  const toggleField = (key: ConfigFieldKey) => {
    setSelectedFields((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const selectAll = (select: boolean) => {
    setSelectedFields({
      vin_range: select,
      vout_range: select,
      ron_mohm: select,
      max31865: select,
      i_max_ma: select,
      v_max_mv: select,
      psu_mode: select,
      psu_vout_target_mv: select,
      psu_fixed_duty: select,
    })
  }

  const resetFormToDefaults = () => {
    setVinRange('low')
    setVoutRange('low')
    setRonMohm(defaults.ron_mohm ?? 6)
    setMax31865(defaults.max31865 ?? false)
    setIMaxMa(defaults.i_max_ma ?? 1000)
    setVMaxMv(defaults.v_max_mv ?? 40000)
    setPsuEnabled(defaults.psu_enabled ?? false)
    setPsuOpenLoop(defaults.psu_open_loop ?? false)
    setPsuVoutTargetMv(defaults.psu_vout_target_mv ?? 5000)
    setPsuFixedDuty(defaults.psu_fixed_duty ?? 0.5)
    setFeedback({
      type: 'success',
      message: 'Form inputs reset to default values.',
    })
  }

  const buildPayloadForKeys = (keys: ConfigFieldKey[]): SendPicoConfigInput => {
    const payload: SendPicoConfigInput = {}
    for (const key of keys) {
      switch (key) {
        case 'vin_range':
          payload.vin_range = vinRange
          break
        case 'vout_range':
          payload.vout_range = voutRange
          break
        case 'ron_mohm':
          payload.ron_mohm = ronMohm
          break
        case 'max31865':
          payload.max31865 = max31865
          break
        case 'i_max_ma':
          payload.i_max_ma = iMaxMa
          break
        case 'v_max_mv':
          payload.v_max_mv = vMaxMv
          break
        case 'psu_mode':
          payload.psu_enabled = psuEnabled
          payload.psu_open_loop = psuOpenLoop
          break
        case 'psu_vout_target_mv':
          payload.psu_vout_target_mv = psuVoutTargetMv
          break
        case 'psu_fixed_duty':
          payload.psu_fixed_duty = psuFixedDuty
          break
      }
    }
    return payload
  }

  // PowerSupply mode drives the converter with no Pi watchdog. The operator
  // must confirm the input is a bench supply; the server refuses without it.
  const confirmPsuIfNeeded = (payload: SendPicoConfigInput): boolean => {
    if (!payload.psu_enabled) return true
    const ok = window.confirm(
      'Power supply mode drives the converter with no Pi watchdog.\n\n' +
        'Check that the input is a bench supply, NOT the solar panel, and that ' +
        'the output load is connected. Continue?',
    )
    if (ok) payload.psu_confirm = true
    return ok
  }

  // Send batch of selected parameters
  const handleSendSelected = async () => {
    const selectedKeys = (Object.keys(selectedFields) as ConfigFieldKey[]).filter(
      (k) => selectedFields[k],
    )
    if (selectedKeys.length === 0) {
      setFeedback({
        type: 'error',
        message: 'No parameters selected. Check at least one parameter to send.',
      })
      return
    }

    const payload = buildPayloadForKeys(selectedKeys)
    if (!confirmPsuIfNeeded(payload)) return
    setSendingBatch(true)
    setFeedback(null)
    try {
      if (!isDemo) {
        await sendPicoConfig(payload)
      }
      setActiveConfig((prev) => ({
        ...prev,
        ...payload,
      }))
      setFeedback({
        type: 'success',
        message: `Successfully transmitted ${selectedKeys.length} parameter(s) to RP2040 Pico.`,
      })
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Error sending configuration to Pico',
      })
    } finally {
      setSendingBatch(false)
    }
  }

  // Send a single specific parameter
  const handleSendSingle = async (key: ConfigFieldKey, label: string) => {
    const payload = buildPayloadForKeys([key])
    if (!confirmPsuIfNeeded(payload)) return
    setSendingSingle(key)
    setFeedback(null)
    try {
      if (!isDemo) {
        await sendPicoConfig(payload)
      }
      setActiveConfig((prev) => ({
        ...prev,
        ...payload,
      }))
      setFeedback({
        type: 'success',
        message: `Sent ${label} to Pico successfully.`,
      })
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : `Failed to send ${label}`,
      })
    } finally {
      setSendingSingle(null)
    }
  }

  // Reset safety cutoff trip
  const handleResetCutoff = async () => {
    setResettingCutoff(true)
    setFeedback(null)
    try {
      if (!isDemo) {
        await resetPicoCutoff()
      }
      setFeedback({
        type: 'success',
        message: 'Hardware cutoff reset signal dispatched. Normal PWM gate drive restored.',
      })
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to reset hardware cutoff',
      })
    } finally {
      setResettingCutoff(false)
    }
  }

  const selectedCount = Object.values(selectedFields).filter(Boolean).length

  return (
    <div className="flex flex-col gap-6">
      {/* Header section */}
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Cpu className="size-6 text-primary" />
            <h2 className="text-2xl font-bold tracking-tight">Pico Dynamic Configuration</h2>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure ADC jumper ranges, safety cutoffs, power supply mode, and hardware parameters
            on the fly via high-speed SPI.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {isDemo ? (
            <Badge variant="outline" className="border-violet-500/40 text-violet-600 dark:text-violet-400">
              Simulated Mode
            </Badge>
          ) : connected ? (
            <Badge variant="outline" className="border-emerald-500/40 text-emerald-600 dark:text-emerald-400">
              <span className="mr-1.5 size-2 inline-block rounded-full bg-emerald-500" />
              Pico Linked
            </Badge>
          ) : (
            <Badge variant="destructive">
              <span className="mr-1.5 size-2 inline-block rounded-full bg-white animate-pulse" />
              Pico Disconnected
            </Badge>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={loadConfig}
            disabled={loading}
            className="gap-1.5"
            title="Refresh current parameters from Pico"
          >
            <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Alert banners */}
      {feedback && (
        <div
          className={cn(
            'flex items-center justify-between gap-3 rounded-lg border p-4 text-sm',
            feedback.type === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300'
              : 'border-destructive/30 bg-destructive/10 text-destructive',
          )}
        >
          <div className="flex items-center gap-2">
            {feedback.type === 'success' ? (
              <CheckCircle2 className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertCircle className="size-5 shrink-0 text-destructive" />
            )}
            <span>{feedback.message}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => setFeedback(null)}
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* Top Global Action Control Bar */}
      <Card className="border-primary/20 bg-muted/30">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-medium text-foreground">
              Selection: <strong className="text-primary">{selectedCount}</strong> of 9 parameters
            </span>
            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => selectAll(true)}
                className="h-8 text-xs text-muted-foreground hover:text-foreground"
              >
                Select All
              </Button>
              <span className="text-muted-foreground">·</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => selectAll(false)}
                className="h-8 text-xs text-muted-foreground hover:text-foreground"
              >
                Deselect All
              </Button>
              <span className="text-muted-foreground">·</span>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Reset to Defaults"
                onClick={resetFormToDefaults}
                className="h-8 text-xs text-muted-foreground hover:text-foreground gap-1"
                title="Restore input values to default settings"
              >
                <RotateCcw className="size-3" />
                Defaults
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              aria-label="Reset Cutoff"
              onClick={handleResetCutoff}
              disabled={resettingCutoff || (!connected && !isDemo)}
              className="gap-1.5 border-amber-500/40 text-amber-700 hover:bg-amber-500/10 dark:text-amber-400"
            >
              <ShieldAlert className={cn('size-4', resettingCutoff && 'animate-spin')} />
              Reset Tripped Cutoff
            </Button>

            <Button
              size="sm"
              onClick={handleSendSelected}
              disabled={sendingBatch || selectedCount === 0 || (!connected && !isDemo)}
              className="gap-2 font-semibold shadow-sm"
            >
              <Send className={cn('size-4', sendingBatch && 'animate-pulse')} />
              {sendingBatch ? 'Sending...' : `Send Selected (${selectedCount})`}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Grid of configuration sections */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 1. ADC Voltage Divider Jumpers */}
        <Card className={cn(selectedFields.vin_range || selectedFields.vout_range ? 'border-primary/40' : '')}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sliders className="size-5 text-sky-500" />
                <CardTitle className="text-base font-semibold">ADC Voltage Dividers</CardTitle>
              </div>
              <Badge variant="secondary" className="text-xs">
                Active: Vin={String(activeConfig.vin_range).toUpperCase()}, Vout={String(activeConfig.vout_range).toUpperCase()}
              </Badge>
            </div>
            <CardDescription>
              Configures the hardware voltage scaling factor to match physical jumper positions.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {/* Vin Range */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.vin_range}
                    onChange={() => toggleField('vin_range')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Vin Divider Range (ADC_PWR)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('vin_range', 'Vin Divider')}
                  disabled={sendingSingle === 'vin_range' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="grid grid-cols-3 gap-2 pt-1">
                {(['low', 'mid', 'full'] as const).map((range) => (
                  <button
                    key={range}
                    type="button"
                    onClick={() => {
                      setVinRange(range)
                      setSelectedFields((p) => ({ ...p, vin_range: true }))
                    }}
                    className={cn(
                      'flex flex-col items-center justify-center rounded-md border p-2 text-xs transition-all',
                      vinRange === range
                        ? 'border-primary bg-primary/10 font-semibold text-primary shadow-xs'
                        : 'border-border/60 hover:bg-muted/50 text-muted-foreground',
                    )}
                  >
                    <span className="capitalize">{range}</span>
                    <span className="text-[10px] opacity-75">
                      {range === 'low' ? '~27.3V' : range === 'mid' ? '~51.5V' : '~75.6V'}
                    </span>
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-muted-foreground">Default: Low (1x 75k divider, 27.3 V max)</span>
            </div>

            {/* Vout Range */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.vout_range}
                    onChange={() => toggleField('vout_range')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Vout Divider Range (ADC_VOUT)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('vout_range', 'Vout Divider')}
                  disabled={sendingSingle === 'vout_range' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="grid grid-cols-3 gap-2 pt-1">
                {(['low', 'mid', 'full'] as const).map((range) => (
                  <button
                    key={range}
                    type="button"
                    onClick={() => {
                      setVoutRange(range)
                      setSelectedFields((p) => ({ ...p, vout_range: true }))
                    }}
                    className={cn(
                      'flex flex-col items-center justify-center rounded-md border p-2 text-xs transition-all',
                      voutRange === range
                        ? 'border-primary bg-primary/10 font-semibold text-primary shadow-xs'
                        : 'border-border/60 hover:bg-muted/50 text-muted-foreground',
                    )}
                  >
                    <span className="capitalize">{range}</span>
                    <span className="text-[10px] opacity-75">
                      {range === 'low' ? '~27.3V' : range === 'mid' ? '~51.5V' : '~75.6V'}
                    </span>
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-muted-foreground">Default: Low (1x 75k divider, 27.3 V max)</span>
            </div>
          </CardContent>
        </Card>

        {/* 2. Hardware Safety Cutoffs */}
        <Card className={cn(selectedFields.i_max_ma || selectedFields.v_max_mv ? 'border-primary/40' : '')}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="size-5 text-emerald-500" />
                <CardTitle className="text-base font-semibold">Hardware Safety Cutoffs</CardTitle>
              </div>
              <Badge variant="secondary" className="text-xs">
                Active: {activeConfig.i_max_ma} mA / {activeConfig.v_max_mv / 1000} V
              </Badge>
            </div>
            <CardDescription>
              Automatic protection: trips PWM gate to 0% duty immediately if thresholds are breached.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {/* Current Cutoff */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.i_max_ma}
                    onChange={() => toggleField('i_max_ma')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Max Current Limit (I_max)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('i_max_ma', 'Current Limit')}
                  disabled={sendingSingle === 'i_max_ma' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="number"
                  min={100}
                  max={1000}
                  step={50}
                  value={iMaxMa}
                  onChange={(e) => {
                    setIMaxMa(Math.max(0, parseInt(e.target.value, 10) || 0))
                    setSelectedFields((p) => ({ ...p, i_max_ma: true }))
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-hidden focus:ring-2 focus:ring-ring"
                />
                <span className="text-sm font-medium text-muted-foreground">mA</span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  ({(iMaxMa / 1000).toFixed(2)} A)
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Default: 1000 mA (1.0 A)</span>
            </div>

            {/* Voltage Cutoff */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.v_max_mv}
                    onChange={() => toggleField('v_max_mv')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Max Voltage Limit (V_max)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('v_max_mv', 'Voltage Limit')}
                  disabled={sendingSingle === 'v_max_mv' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="number"
                  min={1000}
                  max={40000}
                  step={500}
                  value={vMaxMv}
                  onChange={(e) => {
                    setVMaxMv(Math.max(0, parseInt(e.target.value, 10) || 0))
                    setSelectedFields((p) => ({ ...p, v_max_mv: true }))
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-hidden focus:ring-2 focus:ring-ring"
                />
                <span className="text-sm font-medium text-muted-foreground">mV</span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  ({(vMaxMv / 1000).toFixed(1)} V)
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Default: 40000 mV (40.0 V)</span>
            </div>
          </CardContent>
        </Card>

        {/* 3. Hardware Characteristics & Sensors */}
        <Card className={cn(selectedFields.ron_mohm || selectedFields.max31865 ? 'border-primary/40' : '')}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap className="size-5 text-amber-500" />
                <CardTitle className="text-base font-semibold">Power Stage & Sensors</CardTitle>
              </div>
              <Badge variant="secondary" className="text-xs">
                Ron={activeConfig.ron_mohm} mΩ · MAX31865={activeConfig.max31865 ? 'ON' : 'OFF'}
              </Badge>
            </div>
            <CardDescription>
              MOSFET switch resistance and optional external RTD temperature sensor polling.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {/* Ron Switch Resistance */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.ron_mohm}
                    onChange={() => toggleField('ron_mohm')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Switch Resistance (R_on)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Send Ron"
                  onClick={() => handleSendSingle('ron_mohm', 'R_on')}
                  disabled={sendingSingle === 'ron_mohm' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="number"
                  aria-label="On-resistance"
                  min={1}
                  max={500}
                  value={ronMohm}
                  onChange={(e) => {
                    setRonMohm(Math.max(0, parseInt(e.target.value, 10) || 0))
                    setSelectedFields((p) => ({ ...p, ron_mohm: true }))
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-hidden focus:ring-2 focus:ring-ring"
                />
                <span className="text-sm font-medium text-muted-foreground">mΩ</span>
              </div>
              <span className="text-[11px] text-muted-foreground">
                Default: 6 mΩ (Infineon IPP060N06N MOSFET)
              </span>
            </div>

            {/* MAX31865 Temperature Sensor */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.max31865}
                    onChange={() => toggleField('max31865')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span className="flex items-center gap-1.5">
                    <Thermometer className="size-4 text-rose-500" />
                    MAX31865 RTD PT100 Sensor
                  </span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('max31865', 'MAX31865 Sensor')}
                  disabled={sendingSingle === 'max31865' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center justify-between pt-1">
                <div className="text-xs text-muted-foreground">
                  Status:{' '}
                  <span className={cn('font-semibold', max31865 ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>
                    {max31865 ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setMax31865(!max31865)
                    setSelectedFields((p) => ({ ...p, max31865: true }))
                  }}
                  className={cn(
                    'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
                    max31865 ? 'bg-primary' : 'bg-muted',
                  )}
                >
                  <span
                    className={cn(
                      'pointer-events-none inline-block size-5 transform rounded-full bg-background shadow-lg ring-0 transition-transform',
                      max31865 ? 'translate-x-5' : 'translate-x-0',
                    )}
                  />
                </button>
              </div>
              <span className="text-[11px] text-muted-foreground">
                Default: Disabled (turn on when PT100 temperature probe is connected)
              </span>
            </div>
          </CardContent>
        </Card>

        {/* 4. Bench Power Supply Mode */}
        <Card className={cn(selectedFields.psu_mode || selectedFields.psu_vout_target_mv || selectedFields.psu_fixed_duty ? 'border-primary/40' : '')}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Power className="size-5 text-indigo-500" />
                <CardTitle className="text-base font-semibold">Bench Power Supply Mode</CardTitle>
              </div>
              <Badge variant="secondary" className="text-xs">
                Mode: {activeConfig.psu_enabled ? 'PSU' : 'MPPT'} · {activeConfig.psu_open_loop ? 'OpenLoop' : 'ClosedLoop'}
              </Badge>
            </div>
            <CardDescription>
              Local output voltage regulation on the RP2040 (independent of host tracking algorithm).
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {/* Mode & Loop Toggle */}
            <div className="flex flex-col gap-3 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.psu_mode}
                    onChange={() => toggleField('psu_mode')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Firmware Operating Mode</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('psu_mode', 'PSU Mode')}
                  disabled={sendingSingle === 'psu_mode' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setPsuEnabled(false)
                    setSelectedFields((p) => ({ ...p, psu_mode: true }))
                  }}
                  className={cn(
                    'flex flex-col items-center justify-center rounded-md border p-2 text-xs transition-all',
                    !psuEnabled
                      ? 'border-primary bg-primary/10 font-semibold text-primary shadow-xs'
                      : 'border-border/60 hover:bg-muted/50 text-muted-foreground',
                  )}
                >
                  <span>MPPT Tracker</span>
                  <span className="text-[10px] opacity-75">Host algorithm drive</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPsuEnabled(true)
                    setSelectedFields((p) => ({ ...p, psu_mode: true }))
                  }}
                  className={cn(
                    'flex flex-col items-center justify-center rounded-md border p-2 text-xs transition-all',
                    psuEnabled
                      ? 'border-primary bg-primary/10 font-semibold text-primary shadow-xs'
                      : 'border-border/60 hover:bg-muted/50 text-muted-foreground',
                  )}
                >
                  <span>Power Supply</span>
                  <span className="text-[10px] opacity-75">Bench supply mode</span>
                </button>
              </div>

              {psuEnabled && (
                <div className="flex items-center justify-between border-t pt-2.5 mt-1">
                  <span className="text-xs font-medium">Regulation Loop:</span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setPsuOpenLoop(false)
                        setSelectedFields((p) => ({ ...p, psu_mode: true }))
                      }}
                      className={cn(
                        'rounded px-2.5 py-1 text-xs transition-colors',
                        !psuOpenLoop
                          ? 'bg-primary text-primary-foreground font-medium'
                          : 'bg-muted text-muted-foreground hover:bg-muted/80',
                      )}
                    >
                      Closed Loop (PI)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setPsuOpenLoop(true)
                        setSelectedFields((p) => ({ ...p, psu_mode: true }))
                      }}
                      className={cn(
                        'rounded px-2.5 py-1 text-xs transition-colors',
                        psuOpenLoop
                          ? 'bg-primary text-primary-foreground font-medium'
                          : 'bg-muted text-muted-foreground hover:bg-muted/80',
                      )}
                    >
                      Open Loop (Fixed D)
                    </button>
                  </div>
                </div>
              )}
              <span className="text-[11px] text-muted-foreground">Default: MPPT Tracker / ClosedLoop</span>
            </div>

            {/* Target Vout */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.psu_vout_target_mv}
                    onChange={() => toggleField('psu_vout_target_mv')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Target Output Voltage (V_out setpoint)</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('psu_vout_target_mv', 'Target Vout')}
                  disabled={sendingSingle === 'psu_vout_target_mv' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="number"
                  min={1000}
                  max={25000}
                  step={250}
                  value={psuVoutTargetMv}
                  onChange={(e) => {
                    setPsuVoutTargetMv(Math.max(0, parseInt(e.target.value, 10) || 0))
                    setSelectedFields((p) => ({ ...p, psu_vout_target_mv: true }))
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-hidden focus:ring-2 focus:ring-ring"
                />
                <span className="text-sm font-medium text-muted-foreground">mV</span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  ({(psuVoutTargetMv / 1000).toFixed(2)} V)
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Default: 5000 mV (5.0 V)</span>
            </div>

            {/* Fixed Duty */}
            <div className="flex flex-col gap-2 rounded-lg border p-3.5 bg-card/50">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={selectedFields.psu_fixed_duty}
                    onChange={() => toggleField('psu_fixed_duty')}
                    className="size-4 rounded border-muted-foreground/40 text-primary focus:ring-primary"
                  />
                  <span>Open-Loop Fixed Duty Cycle</span>
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSendSingle('psu_fixed_duty', 'Fixed Duty')}
                  disabled={sendingSingle === 'psu_fixed_duty' || (!connected && !isDemo)}
                  className="h-7 px-2 text-xs gap-1"
                >
                  <Send className="size-3" />
                  Send
                </Button>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <input
                  type="range"
                  min={0.05}
                  max={0.9}
                  step={0.01}
                  value={psuFixedDuty}
                  onChange={(e) => {
                    setPsuFixedDuty(parseFloat(e.target.value))
                    setSelectedFields((p) => ({ ...p, psu_fixed_duty: true }))
                  }}
                  className="flex-1 accent-primary"
                />
                <span className="w-16 font-mono text-xs font-semibold text-right">
                  {(psuFixedDuty * 100).toFixed(0)} %
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">Default: 50% (D = 0.50)</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
