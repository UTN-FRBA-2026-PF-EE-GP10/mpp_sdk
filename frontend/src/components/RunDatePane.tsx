import { useState } from 'react'
import { RunPlayerDialog } from '@/components/RunPlayerDialog'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatCapturedAt, formatSeconds } from '@/lib/format'
import type { RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

/**
 * One date's closed-loop runs, as a table - same click-a-row-to-open
 * pattern as CurveWorkbench's saved-curves table. Opening a row hands off
 * to RunPlayerDialog, the one place a run is played back (App.tsx is the
 * only other thing that could reach it, and doesn't need to - a run only
 * ever surfaces grouped under its date).
 */
export function RunDatePane({
  date,
  runs,
  curves,
  onRunsChanged,
}: {
  date: string
  runs: RunSummary[]
  curves: CurveRecord[]
  onRunsChanged: () => void
}) {
  const [selected, setSelected] = useState<RunSummary | null>(null)

  return (
    <Card>
      <CardHeader>
        <CardTitle>{date}</CardTitle>
        <CardDescription>Closed-loop MPPT runs captured this day.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs recorded for this date yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Algorithm</TableHead>
                  <TableHead>Captured</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead className="text-right">Samples</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow
                    key={r.id}
                    onClick={() => setSelected(r)}
                    tabIndex={0}
                    role="button"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(r)
                      }
                    }}
                    className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    <TableCell className="font-medium">{r.label || 'Untitled run'}</TableCell>
                    <TableCell>{r.algorithm}</TableCell>
                    <TableCell>{formatCapturedAt(r.captured_at)}</TableCell>
                    <TableCell className="text-right">{formatSeconds(r.duration_s)}</TableCell>
                    <TableCell className="text-right">{r.n_samples}</TableCell>
                    <TableCell>
                      {r.curve_ref ? (
                        <span className="text-xs text-muted-foreground">curve saved</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">none</span>
                      )}
                    </TableCell>
                    <TableCell>{r.aborted && <Badge variant="destructive">Aborted</Badge>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <RunPlayerDialog
        run={selected}
        curves={curves}
        onClose={() => setSelected(null)}
        onDeleted={onRunsChanged}
      />
    </Card>
  )
}
