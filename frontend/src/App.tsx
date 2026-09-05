import { useEffect, useMemo, useState } from 'react'
import { ConnectionIndicator } from '@/components/ConnectionIndicator'
import { CurveWorkbench } from '@/components/CurveWorkbench'
import { MeasurementKindCard } from '@/components/MeasurementKindCard'
import { useConnectionStatus } from '@/hooks/useConnectionStatus'
import { fetchCurves, fetchMeasurementKinds } from '@/lib/api'
import { MEASUREMENT_KINDS, type CurveRecord } from '@/types'

export default function App() {
  const connectionStatus = useConnectionStatus()
  const [selected, setSelected] = useState<string>('baseline')
  // Seeded with the known vocabulary so cards render before the first
  // fetch lands; GET /api/measurement-kinds and any kind already present
  // in the library (an operator can save under a kind this list never
  // anticipated - see mpp_sdk/curves/record.py) both fold in on top.
  const [seedKinds, setSeedKinds] = useState<string[]>([...MEASUREMENT_KINDS])
  const [records, setRecords] = useState<CurveRecord[]>([])
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    fetchMeasurementKinds()
      .then((fetched) => setSeedKinds((prev) => Array.from(new Set([...prev, ...fetched]))))
      .catch((e) => console.error('fetching measurement kinds failed', e))
  }, [])

  useEffect(() => {
    fetchCurves()
      .then(setRecords)
      .catch((e) => console.error('fetching curves failed', e))
  }, [reloadToken])

  const byKind = useMemo(() => {
    const groups = new Map<string, CurveRecord[]>()
    for (const kind of seedKinds) groups.set(kind, [])
    for (const record of records) {
      if (!groups.has(record.measurement)) groups.set(record.measurement, [])
      groups.get(record.measurement)?.push(record)
    }
    return groups
  }, [seedKinds, records])

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold tracking-tight">Curve Workbench</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every I-V sweep captured off the bench, grouped by what kind of measurement it
            is: a flat baseline, a panel tilted to emulate partial shading, a tilt sweep, or
            (later) a controllable dimmer. Pick a card to see its curves and trigger a new
            capture. This replays the sweep into the MPPT algorithm benchmark so each
            controller's behaviour on the real array can be predicted before it is
            committed to firmware.
          </p>
        </div>
        <ConnectionIndicator status={connectionStatus} />
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from(byKind.keys()).map((kind) => (
          <MeasurementKindCard
            key={kind}
            kind={kind}
            records={byKind.get(kind) ?? []}
            selected={selected === kind}
            onSelect={() => setSelected(kind)}
          />
        ))}
      </section>

      <CurveWorkbench
        key={selected}
        kind={selected}
        records={byKind.get(selected) ?? []}
        connected={connectionStatus === 'connected'}
        onSaved={() => setReloadToken((t) => t + 1)}
      />
    </div>
  )
}
