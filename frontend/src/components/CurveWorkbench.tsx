import { useState } from 'react'
import { LiveChart } from '@/components/LiveChart'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLiveSweep } from '@/hooks/useLiveSweep'
import { saveCurve } from '@/lib/api'
import { getMeasurementKindInfo, type CurveRecord, type PanelSetup } from '@/types'

const DEFAULT_PANELS: PanelSetup[] = [
  { id: 'A', tilt_deg: 0 },
  { id: 'B', tilt_deg: 0 },
]

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function SaveCurveForm({
  kind,
  hasCapture,
  onSaved,
}: {
  kind: string
  hasCapture: boolean
  onSaved: () => void
}) {
  const [label, setLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [panels, setPanels] = useState<PanelSetup[]>(DEFAULT_PANELS)
  const [status, setStatus] = useState<string>('')
  const [saving, setSaving] = useState(false)

  function updateTilt(index: number, tilt_deg: number) {
    setPanels((prev) => prev.map((p, i) => (i === index ? { ...p, tilt_deg } : p)))
  }

  async function handleSave() {
    setSaving(true)
    setStatus('')
    try {
      const result = await saveCurve({ label, measurement: kind, panels, notes })
      setStatus(`saved: ${result.path}`)
      setLabel('')
      setNotes('')
      onSaved()
    } catch (e) {
      setStatus(`save failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap gap-3">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="label, e.g. 'both flat, midday sun'"
          className="min-w-[220px] flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm"
        />
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="notes (optional)"
          className="min-w-[160px] flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {panels.map((p, i) => (
          <label key={p.id} className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Panel {p.id} tilt
            <input
              type="number"
              value={p.tilt_deg}
              onChange={(e) => updateTilt(i, Number(e.target.value))}
              className="w-16 rounded-md border bg-transparent px-2 py-1 text-sm"
            />
            °
          </label>
        ))}
        <Button
          size="sm"
          onClick={handleSave}
          disabled={!hasCapture || saving || !label.trim()}
          className="ml-auto"
        >
          {saving ? 'Saving...' : 'Save curve'}
        </Button>
      </div>
      {status && <p className="text-xs text-muted-foreground">{status}</p>}
    </div>
  )
}

export function CurveWorkbench({
  kind,
  records,
  connected,
  onSaved,
}: {
  kind: string
  records: CurveRecord[]
  connected: boolean
  onSaved: () => void
}) {
  const info = getMeasurementKindInfo(kind)
  const { partial, points, active, start, releaseRelay } = useLiveSweep()
  // Deliberately excludes `active`: POST /api/save-curve persists the
  // cache's last *completed* sweep (see curve_tracer_server.py's
  // post_save_curve), not whatever `partial` is currently drawing. Allowing
  // Save while a new sweep is in flight would silently save the previous
  // sweep's points under the label/panels meant for the one in progress.
  const hasCapture = !active && points.length > 0

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{info.title}</CardTitle>
            <p className="text-sm text-muted-foreground">{info.description}</p>
          </div>
          <div className="flex gap-2">
            <Button onClick={start} disabled={!connected || active}>
              {active ? 'Measuring...' : 'Start Measurement'}
            </Button>
            <Button variant="outline" onClick={releaseRelay} disabled={!connected}>
              Release Relay
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div>
          <LiveChart partial={partial} points={points} active={active} />
          <p className="mt-1 text-center text-xs text-muted-foreground">
            {active
              ? `capturing... ${partial.length} point${partial.length === 1 ? '' : 's'}`
              : points.length
                ? `last capture: ${points.length} points`
                : 'no curve yet - press Start Measurement'}
          </p>
        </div>

        <SaveCurveForm kind={kind} hasCapture={hasCapture} onSaved={onSaved} />

        <Separator />

        <div>
          <h3 className="mb-2 text-sm font-medium text-foreground">
            Saved curves ({records.length})
          </h3>
          {records.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing saved under &ldquo;{kind}&rdquo; yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Captured</TableHead>
                    <TableHead>Panels</TableHead>
                    <TableHead className="text-right">Voc</TableHead>
                    <TableHead className="text-right">Isc</TableHead>
                    <TableHead className="text-right">P_mpp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {records.map((r) => (
                    <TableRow key={r.path}>
                      <TableCell className="font-medium">{r.label}</TableCell>
                      <TableCell>{formatTime(r.captured_at)}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {r.panels.map((p) => (
                            <Badge key={p.id} variant="outline">
                              {p.id}: {p.tilt_deg}°
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">{r.voc.toFixed(2)} V</TableCell>
                      <TableCell className="text-right">{(r.isc * 1000).toFixed(1)} mA</TableCell>
                      <TableCell className="text-right">
                        {(r.p_mpp * 1000).toFixed(1)} mW
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
