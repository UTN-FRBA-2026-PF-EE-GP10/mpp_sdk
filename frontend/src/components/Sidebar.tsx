import { ChevronDown, ChevronRight, History, LineChart, X } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Dialog, DialogBackdrop, DialogPanel, DialogPortal, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { RunDateGroup } from '@/lib/runs'
import { getMeasurementKindInfo } from '@/types'

export type Selection =
  | { root: 'measure' }
  | { root: 'curves'; kind: string }
  | { root: 'runs'; date: string }

function NavRow({
  label,
  selected,
  indent,
  onClick,
  trailing,
}: {
  label: string
  selected: boolean
  indent?: boolean
  onClick: () => void
  trailing?: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? 'page' : undefined}
      className={cn(
        'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
        indent && 'pl-8',
        selected
          ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
      )}
    >
      <span
        className={cn(
          'size-2 shrink-0 rounded-full border',
          selected ? 'border-primary bg-primary' : 'border-muted-foreground/50',
        )}
        aria-hidden="true"
      />
      <span className="flex-1 truncate">{label}</span>
      {trailing}
    </button>
  )
}

function SectionHeader({
  label,
  expanded,
  onToggle,
  icon,
}: {
  label: string
  expanded: boolean
  onToggle: () => void
  icon: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className="mt-2 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-sidebar-foreground hover:bg-sidebar-accent/60"
    >
      {expanded ? (
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      ) : (
        <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
      )}
      {icon}
      <span className="flex-1">{label}</span>
    </button>
  )
}

/**
 * The nav content shared by both renderings of the sidebar below: the
 * static desktop `<aside>` and the mobile modal drawer. One definition so
 * the two can never drift - a kind added to the desktop list is a kind
 * added to the drawer, for free.
 */
function SidebarNav({
  selection,
  choose,
  kinds,
  countsByKind,
  runGroups,
  curvesOpen,
  setCurvesOpen,
  runsOpen,
  setRunsOpen,
}: {
  selection: Selection
  choose: (selection: Selection) => void
  kinds: string[]
  countsByKind: Map<string, number>
  runGroups: RunDateGroup[]
  curvesOpen: boolean
  setCurvesOpen: (updater: (v: boolean) => boolean) => void
  runsOpen: boolean
  setRunsOpen: (updater: (v: boolean) => boolean) => void
}) {
  return (
    <>
      <NavRow
        label="Measure"
        selected={selection.root === 'measure'}
        onClick={() => choose({ root: 'measure' })}
      />

      <SectionHeader
        label="Curves"
        expanded={curvesOpen}
        onToggle={() => setCurvesOpen((v) => !v)}
        icon={<LineChart className="size-4 shrink-0 text-muted-foreground" />}
      />
      {curvesOpen && (
        <div className="flex flex-col gap-1">
          {kinds.map((kind) => {
            const info = getMeasurementKindInfo(kind)
            const count = countsByKind.get(kind) ?? 0
            return (
              <NavRow
                key={kind}
                label={info.title}
                indent
                selected={selection.root === 'curves' && selection.kind === kind}
                onClick={() => choose({ root: 'curves', kind })}
                trailing={<span className="text-xs text-muted-foreground">{count}</span>}
              />
            )
          })}
        </div>
      )}

      <SectionHeader
        label="Runs"
        expanded={runsOpen}
        onToggle={() => setRunsOpen((v) => !v)}
        icon={<History className="size-4 shrink-0 text-muted-foreground" />}
      />
      {runsOpen && (
        <div className="flex flex-col gap-1">
          {runGroups.length === 0 ? (
            <p className="px-3 py-1.5 pl-8 text-xs text-muted-foreground">No runs recorded yet.</p>
          ) : (
            runGroups.map((group) => (
              <NavRow
                key={group.date}
                label={group.date}
                indent
                selected={selection.root === 'runs' && selection.date === group.date}
                onClick={() => choose({ root: 'runs', date: group.date })}
                trailing={<span className="text-xs text-muted-foreground">{group.runs.length}</span>}
              />
            ))
          )}
        </div>
      )}
    </>
  )
}

export function Sidebar({
  selection,
  onSelect,
  kinds,
  countsByKind,
  runGroups,
  mobileOpen,
  onCloseMobile,
}: {
  selection: Selection
  onSelect: (selection: Selection) => void
  kinds: string[]
  countsByKind: Map<string, number>
  runGroups: RunDateGroup[]
  mobileOpen: boolean
  onCloseMobile: () => void
}) {
  const [curvesOpen, setCurvesOpen] = useState(true)
  const [runsOpen, setRunsOpen] = useState(true)

  // Closing the drawer on every pick (desktop's onCloseMobile is a no-op
  // since it's already closed there) keeps mobile behaving like a normal
  // nav drawer without a separate desktop/mobile select handler.
  function choose(next: Selection) {
    onSelect(next)
    onCloseMobile()
  }

  const navProps = {
    selection,
    choose,
    kinds,
    countsByKind,
    runGroups,
    curvesOpen,
    setCurvesOpen,
    runsOpen,
    setRunsOpen,
  }

  return (
    <>
      {/* Desktop: a plain static column, never a dialog - always present
          in the layout and the tab order at md and up. This must keep
          working exactly as before; only the mobile rendering below
          changes. */}
      <aside className="hidden w-64 flex-col gap-1 overflow-y-auto border-r bg-sidebar p-3 text-sidebar-foreground md:flex">
        <SidebarNav {...navProps} />
      </aside>

      {/* Mobile: a real modal dialog rather than a transform-hidden
          <aside>. That gets four things for free that the old hand-rolled
          version was missing: the drawer is removed from the DOM (so out
          of the tab order) while closed instead of merely translated
          off-screen; Escape closes it; focus is trapped inside and moves
          into it on open; and the backdrop is portalled to <body>, so it
          sits above the header's controls (hamburger, toggles,
          capture-mode menu) instead of starting below them. */}
      <Dialog
        open={mobileOpen}
        onOpenChange={(open) => {
          if (!open) onCloseMobile()
        }}
      >
        <DialogPortal>
          <DialogBackdrop className="md:hidden" />
          <DialogPanel className="left-0 w-72 overflow-y-auto border-r p-3 md:hidden">
            <DialogTitle className="sr-only">Navigate</DialogTitle>
            <div className="mb-1 flex items-center justify-between">
              <span
                className="px-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
                aria-hidden="true"
              >
                Navigate
              </span>
              <button
                type="button"
                onClick={onCloseMobile}
                aria-label="Close navigation"
                className="rounded-md p-1.5 hover:bg-sidebar-accent"
              >
                <X className="size-4" />
              </button>
            </div>
            <SidebarNav {...navProps} />
          </DialogPanel>
        </DialogPortal>
      </Dialog>
    </>
  )
}
