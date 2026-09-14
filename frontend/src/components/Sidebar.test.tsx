import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Sidebar, type Selection } from './Sidebar'
import type { RunDateGroup } from '@/lib/runs'

afterEach(cleanup)

function baseProps(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const runGroups: RunDateGroup[] = []
  return {
    selection: { root: 'measure' } as Selection,
    onSelect: vi.fn(),
    kinds: ['baseline', 'dimmed'],
    countsByKind: new Map([
      ['baseline', 2],
      ['dimmed', 1],
    ]),
    runGroups,
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
