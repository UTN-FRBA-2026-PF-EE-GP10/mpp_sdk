import { useMemo, useState } from 'react'
import { ConnectionIndicator } from '@/components/ConnectionIndicator'
import { CurveWorkbench } from '@/components/CurveWorkbench'
import { MeasurementKindCard } from '@/components/MeasurementKindCard'
import { useConnectionStatus } from '@/hooks/useConnectionStatus'
import { MOCK_LIBRARY } from '@/lib/mockCurves'
import { MEASUREMENT_KINDS, type MeasurementKind } from '@/types'

export default function App() {
  const connectionStatus = useConnectionStatus()
  const [selected, setSelected] = useState<MeasurementKind>('baseline')

  const byKind = useMemo(() => {
    const groups = new Map<MeasurementKind, typeof MOCK_LIBRARY>()
    for (const kind of MEASUREMENT_KINDS) groups.set(kind, [])
    for (const record of MOCK_LIBRARY) {
      const bucket = groups.get(record.measurement as MeasurementKind) ?? groups.get('other')
      bucket?.push(record)
    }
    return groups
  }, [])

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
        {MEASUREMENT_KINDS.map((kind) => (
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
      />

      <p className="pb-4 text-center text-xs text-muted-foreground">
        Showing mock data - not yet wired to the Pi (
        <a
          className="underline underline-offset-2"
          href="https://github.com/UTN-FRBA-2026-PF-EE-GP10/mpp_sdk"
        >
          mpp-sdk
        </a>
        , plan 023).
      </p>
    </div>
  )
}
