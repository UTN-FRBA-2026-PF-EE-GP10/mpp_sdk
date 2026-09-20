import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConnectionIndicator } from './ConnectionIndicator'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import type { ConnectionStatus } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchLiveSweep: vi.fn(),
}))

import { fetchLiveSweep } from '@/lib/api'
import type { LiveSweepState } from '@/lib/api'

function mockLiveSweep(overrides: Partial<LiveSweepState>): LiveSweepState {
  return {
    points: [],
    partial: [],
    active: false,
    link: 'ok',
    seq: 0,
    commandError: null,
    demoSource: false,
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  vi.resetAllMocks()
})

function renderIndicator(status: ConnectionStatus) {
  return render(
    <CaptureModeProvider>
      <ConnectionIndicator status={status} />
    </CaptureModeProvider>,
  )
}

function renderIndicatorInSimulatedMode(status: ConnectionStatus) {
  return render(
    <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
      <ConnectionIndicator status={status} />
    </CaptureModeContext.Provider>,
  )
}

describe('ConnectionIndicator', () => {
  it('is a real, focusable button, not a passive pill', () => {
    renderIndicator('connected')
    expect(screen.getByRole('button').tagName).toBe('BUTTON')
  })

  it('shows "PICO connected" once connected, in the default hardware mode', () => {
    renderIndicator('connected')
    expect(screen.getByText('PICO connected')).toBeTruthy()
  })

  it('still tells the truth about a server-side --demo source in hardware mode', () => {
    renderIndicator('demo')
    expect(screen.getByText('Simulated board')).toBeTruthy()
  })

  it('reports the real link status when nothing is connected yet', () => {
    renderIndicator('connecting')
    expect(screen.getByText('Checking PICO...')).toBeTruthy()
  })

  it('describes what clicking does in its accessible name', () => {
    renderIndicator('connected')
    expect(screen.getByRole('button', { name: /capture mode: pico connected/i })).toBeTruthy()
  })

  it('opens a menu naming all three modes on click', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    expect(await screen.findByText('Replay on the board')).toBeTruthy()
    expect(screen.getByText('Demo')).toBeTruthy()
  })

  it('makes "Replay on the board" impossible to select when there is no live link', async () => {
    renderIndicator('disconnected')
    fireEvent.click(screen.getByRole('button'))
    const label = await screen.findByText('Replay on the board')
    const item = label.closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')

    // Clicking a disabled radio item must not change anything - the
    // indicator still reports the real (disconnected) status.
    fireEvent.click(label)
    expect(screen.getByText('PICO not connected')).toBeTruthy()
  })

  it('leaves "Replay on the board" selectable once connected', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    const label = await screen.findByText('Replay on the board')
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
    expect(within(trigger).queryByText('PICO connected')).toBeNull()
  })

  it('never touches the network outside demo mode - the passed-in status is trusted as-is', async () => {
    renderIndicator('connected')
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Replay on the board')
    expect(fetchLiveSweep).not.toHaveBeenCalled()
  })
})

describe('ConnectionIndicator raw link readout', () => {
  it('shows the raw link text in the menu as a debug readout', async () => {
    render(
      <CaptureModeProvider>
        <ConnectionIndicator status="connected" link="waiting for sweep" />
      </CaptureModeProvider>,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(await screen.findByText('waiting for sweep')).toBeTruthy()
  })

  it('shows nothing when no raw link is available yet', async () => {
    render(
      <CaptureModeProvider>
        <ConnectionIndicator status="connecting" />
      </CaptureModeProvider>,
    )
    fireEvent.click(screen.getByRole('button'))
    await screen.findByText('Replay on the board')
    expect(screen.queryByText(/Raw link:/)).toBeNull()
  })
})

describe('ConnectionIndicator in demo (simulated) mode', () => {
  it('has no live `status` to go on, so "Replay on the board" starts unselectable until checked', async () => {
    vi.mocked(fetchLiveSweep).mockReturnValue(new Promise(() => {}))
    renderIndicatorInSimulatedMode('connected') // a stale/leftover status - must not be trusted
    fireEvent.click(screen.getByRole('button'))

    const item = (await screen.findByText('Replay on the board')).closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')
    expect(fetchLiveSweep).toHaveBeenCalledTimes(1)
  })

  it('makes "Replay on the board" selectable once a fresh one-shot check succeeds', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockLiveSweep({ link: 'ok' }))
    renderIndicatorInSimulatedMode('disconnected')
    fireEvent.click(screen.getByRole('button'))

    await waitFor(async () => {
      const item = (await screen.findByText('Replay on the board')).closest('[role="menuitemradio"]')
      expect(item?.getAttribute('aria-disabled')).not.toBe('true')
    })
  })

  it('keeps "Replay on the board" unselectable when the one-shot check fails', async () => {
    vi.mocked(fetchLiveSweep).mockRejectedValue(new Error('no link'))
    renderIndicatorInSimulatedMode('connected')
    fireEvent.click(screen.getByRole('button'))

    await waitFor(() => expect(fetchLiveSweep).toHaveBeenCalled())
    const item = (await screen.findByText('Replay on the board')).closest('[role="menuitemradio"]')
    expect(item?.getAttribute('aria-disabled')).toBe('true')
  })

  it('re-checks every time the menu is (re-)opened, not just once', async () => {
    vi.mocked(fetchLiveSweep).mockResolvedValue(mockLiveSweep({ link: 'ok' }))
    renderIndicatorInSimulatedMode('disconnected')

    fireEvent.click(screen.getByRole('button')) // open
    await waitFor(() => expect(fetchLiveSweep).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button')) // close
    fireEvent.click(screen.getByRole('button')) // open again

    await waitFor(() => expect(fetchLiveSweep).toHaveBeenCalledTimes(2))
  })
})
