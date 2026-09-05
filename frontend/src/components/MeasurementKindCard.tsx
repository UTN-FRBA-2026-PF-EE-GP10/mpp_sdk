import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getMeasurementKindInfo, type CurveRecord } from '@/types'

export function MeasurementKindCard({
  kind,
  records,
  selected,
  onSelect,
}: {
  kind: string
  records: CurveRecord[]
  selected: boolean
  onSelect: () => void
}) {
  const info = getMeasurementKindInfo(kind)
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'cursor-pointer transition-colors hover:border-primary/60',
        selected && 'border-primary ring-1 ring-primary',
      )}
    >
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>{info.title}</CardTitle>
          <Badge variant={records.length ? 'default' : 'secondary'}>
            {records.length} curve{records.length === 1 ? '' : 's'}
          </Badge>
        </div>
        <CardDescription>{info.description}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        {records.length === 0
          ? 'No curves captured yet.'
          : `Latest: ${records[0].label}`}
      </CardContent>
    </Card>
  )
}
