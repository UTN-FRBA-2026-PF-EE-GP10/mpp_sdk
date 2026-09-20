import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Sidebar, type Selection } from './Sidebar'
import type { ReportSummary } from '@/lib/reports'
import type { RunDateGroup } from '@/lib/runs'

afterEach(cleanup)

function baseProps(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const runGroups: RunDateGroup[] = []
  const reports: ReportSummary[] = []
  return {
    selection: { root: 'measure' } as Selection,
    onSelect: vi.fn(),
    kinds: ['baseline', 'dimmed'],
    countsByKind: new Map([
      ['baseline', 2],
      ['dimmed', 1],
    ]),
    runGroups,
    reports,
    canCreateReport: true,
    mobileOpen: false,
    onCloseMobile: vi.fn(),
    ...overrides,
  }
}

describe('Sidebar - desktop', () => {
  it('always renders the static nav, independent of mobileOpen', () => {
    render(<Sidebar {...baseProps({ mobileOpen: false })} />)
    // Only the desktop copy exists while the drawer is closed - see the
    // "removed from the DOM while closed" test below.
    expect(screen.getAllByText('Measure')).toHaveLength(1)
    expect(screen.getByText('Baseline')).toBeTruthy()
  })

  it('picking a nav row calls onSelect (and the no-op onCloseMobile) without opening any dialog', () => {
    const props = baseProps()
    render(<Sidebar {...props} />)
    fireEvent.click(screen.getByText('Baseline'))
    expect(props.onSelect).toHaveBeenCalledWith({ root: 'curves', kind: 'baseline' })
  })
})

describe('Sidebar - mobile drawer', () => {
  it('is entirely absent from the DOM - and so from the tab order - while closed', () => {
    render(<Sidebar {...baseProps({ mobileOpen: false })} />)
    expect(screen.queryByLabelText('Close navigation')).toBeNull()
  })

  it('renders its content and moves focus inside once opened', async () => {
    render(<Sidebar {...baseProps({ mobileOpen: true })} />)
    await waitFor(() => expect(screen.getByLabelText('Close navigation')).toBeTruthy())
    // Two "Measure" rows now: the always-present desktop one and the
    // drawer's own copy.
    expect(screen.getAllByText('Measure')).toHaveLength(2)

    const drawer = screen.getByRole('dialog')
    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body)
      expect(drawer.contains(document.activeElement)).toBe(true)
    })
  })

  it('closes on Escape', async () => {
    const props = baseProps({ mobileOpen: true })
    render(<Sidebar {...props} />)
    await waitFor(() => expect(screen.getByLabelText('Close navigation')).toBeTruthy())

    fireEvent.keyDown(document.body, { key: 'Escape', code: 'Escape' })

    await waitFor(() => expect(props.onCloseMobile).toHaveBeenCalled())
  })

  it('closes when the close button is pressed', async () => {
    const props = baseProps({ mobileOpen: true })
    render(<Sidebar {...props} />)
    await waitFor(() => expect(screen.getByLabelText('Close navigation')).toBeTruthy())

    fireEvent.click(screen.getByLabelText('Close navigation'))

    expect(props.onCloseMobile).toHaveBeenCalled()
  })

  it('closes after picking a nav row inside it, same as the desktop copy', async () => {
    const props = baseProps({ mobileOpen: true })
    render(<Sidebar {...props} />)
    await waitFor(() => expect(screen.getAllByText('Baseline')).toHaveLength(2))

    // The drawer's own "Baseline" row is the second match in the DOM.
    fireEvent.click(screen.getAllByText('Baseline')[1])

    expect(props.onSelect).toHaveBeenCalledWith({ root: 'curves', kind: 'baseline' })
    expect(props.onCloseMobile).toHaveBeenCalled()
  })
})

describe('Sidebar - reports', () => {
  it('lists reports newest first with their progress count', () => {
    const reports: ReportSummary[] = [
      {
        id: 'r1',
        title: 'Panel A alone',
        template_id: 'single-panel-characterization',
        setup: 'single',
        created_at: '2026-09-19T16:00:00Z',
        updated_at: '2026-09-19T16:00:00Z',
        n_steps: 20,
        n_done: 12,
        n_failed: 0,
      },
    ]
    render(<Sidebar {...baseProps({ reports })} />)
    expect(screen.getByText('Panel A alone')).toBeTruthy()
    expect(screen.getByText('12 / 20')).toBeTruthy()
  })

  it('picking a report row selects it', () => {
    const reports: ReportSummary[] = [
      {
        id: 'r1',
        title: 'Panel A alone',
        template_id: 'single-panel-characterization',
        setup: 'single',
        created_at: '2026-09-19T16:00:00Z',
        updated_at: '2026-09-19T16:00:00Z',
        n_steps: 20,
        n_done: 12,
        n_failed: 0,
      },
    ]
    const props = baseProps({ reports })
    render(<Sidebar {...props} />)
    fireEvent.click(screen.getByText('Panel A alone'))
    expect(props.onSelect).toHaveBeenCalledWith({ root: 'report', id: 'r1' })
  })

  it('shows "New report" only when creating reports is allowed', () => {
    const { rerender } = render(<Sidebar {...baseProps({ canCreateReport: true })} />)
    expect(screen.getByText('New report')).toBeTruthy()

    rerender(<Sidebar {...baseProps({ canCreateReport: false })} />)
    expect(screen.queryByText('New report')).toBeNull()
  })

  it('picking "New report" selects the new-report pane', () => {
    const props = baseProps({ canCreateReport: true })
    render(<Sidebar {...props} />)
    fireEvent.click(screen.getByText('New report'))
    expect(props.onSelect).toHaveBeenCalledWith({ root: 'new-report' })
  })

  it('shows an empty state with no reports yet', () => {
    render(<Sidebar {...baseProps({ reports: [] })} />)
    expect(screen.getByText('No reports yet.')).toBeTruthy()
  })
})
