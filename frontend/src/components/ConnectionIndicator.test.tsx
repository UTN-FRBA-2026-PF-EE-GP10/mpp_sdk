import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ConnectionIndicator } from './ConnectionIndicator'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import type { ConnectionStatus } from '@/types'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function renderIndicator(status: ConnectionStatus) {
  return render(
    <CaptureModeProvider>
      <ConnectionIndicator status={status} />
    </CaptureModeProvider>,
  )
}

describe('ConnectionIndicator', () => {
  it('is a real, focusable button, not a passive pill', () => {
    renderIndicator('connected')
    expect(screen.getByRole('button').tagName).toBe('BUTTON')
  })

  it('shows "Pi connected" once connected, in the default hardware mode', () => {
    renderIndicator('connected')
    expect(screen.getByText('Pi connected')).toBeTruthy()
  })

  it('still tells the truth about a server-side --demo source in hardware mode', () => {
    renderIndicator('demo')
    expect(screen.getByText('Demo mode - simulated')).toBeTruthy()
  })

  it('reports the real link status when nothing is connected yet', () => {
    renderIndicator('connecting')
    expect(screen.getByText('Connecting...')).toBeTruthy()
  })

  it('describes what clicking does in its accessible name', () => {
    renderIndicator('connected')
    expect(screen.getByRole('button', { name: /capture mode: pi connected/i })).toBeTruthy()
  })

  it('opens a menu naming all three modes on click', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    expect(await screen.findByText('Demo with Pi')).toBeTruthy()
    expect(screen.getByText('Demo')).toBeTruthy()
  })

  it('makes "Demo with Pi" impossible to select when there is no live link', async () => {
    renderIndicator('disconnected')
    fireEvent.click(screen.getByRole('button'))
    const label = await screen.findByText('Demo with Pi')
    const item = label.closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')

    // Clicking a disabled radio item must not change anything - the
    // indicator still reports the real (disconnected) status.
    fireEvent.click(label)
    expect(screen.getByText('Disconnected')).toBeTruthy()
  })

  it('leaves "Demo with Pi" selectable once connected', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    const label = await screen.findByText('Demo with Pi')
    const item = label.closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).not.toBe('true')
  })

  it('switches to Demo (fully offline) on selection, overriding the live status entirely', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    const demoItem = await screen.findByText('Demo')
    fireEvent.click(demoItem)

    // Scoped to the trigger itself: selecting closes the menu (closeOnClick),
    // but scoping avoids any ambiguity with the menu's own item text either way.
    const trigger = screen.getByRole('button', { name: /capture mode/i })
    expect(within(trigger).getByText('Demo')).toBeTruthy()
    expect(within(trigger).queryByText('Pi connected')).toBeNull()
  })
})
