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
import { useMockSweep } from '@/hooks/useMockSweep'
import { MEASUREMENT_KIND_INFO, type CurveRecord, type MeasurementKind } from '@/types'

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function CurveWorkbench({
  kind,
  records,
  connected,
}: {
  kind: MeasurementKind
  records: CurveRecord[]
  connected: boolean
}) {
  const info = MEASUREMENT_KIND_INFO[kind]
  const reference = records[0]
  const { partial, points, active, start } = useMockSweep(
    reference?.voc ?? 21.2,
    reference?.isc ?? 0.2,
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{info.title}</CardTitle>
            <p className="text-sm text-muted-foreground">{info.description}</p>
          </div>
          <Button onClick={start} disabled={!connected || active}>
            {active ? 'Measuring...' : 'Start Measurement'}
          </Button>
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
                : reference
                  ? `reference curve: ${reference.label}`
                  : 'no curve yet - press Start Measurement'}
          </p>
        </div>

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
