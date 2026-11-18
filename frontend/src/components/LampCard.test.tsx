import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LampCard } from './LampCard'
import { CaptureModeContext, type CaptureMode } from '@/lib/captureMode'
import { ApiError } from '@/lib/apiError'
import * as api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  fetchLamp: vi.fn(),
  setLamp: vi.fn(),
  lampOff: vi.fn(),
}))

function status(over: Partial<api.LampStatus> = {}): api.LampStatus {
  return {
    available: true,
    state: 'off',
    power: null,
    alpha_deg: null,
    applied_alpha_deg: null,
    window_left_s: null,
    max_on_s: 30,
    budget_s: 120,
    tripped: false,
    mains: true,
    locked: false,
    timed_out: false,
    link_ok: true,
    max_power: 1,
    error: null,
    ...over,
  }
}

function renderCard(mode: CaptureMode = 'hardware') {
  return render(
    <CaptureModeContext.Provider value={{ mode, setMode: vi.fn() }}>
      <LampCard />
    </CaptureModeContext.Provider>,
  )
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

const onBtn = () => screen.getByRole('button', { name: 'Lamp on' }) as HTMLButtonElement
const offBtn = () => screen.getByRole('button', { name: 'Off' }) as HTMLButtonElement
const stateText = () => screen.getByTestId('lamp-state').textContent

describe('LampCard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    setVisibility('visible')
    vi.mocked(api.fetchLamp).mockResolvedValue(status())
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('reads the status on mount and shows OFF', async () => {
    renderCard()
    await flush()
    expect(api.fetchLamp).toHaveBeenCalledTimes(1)
    expect(stateText()).toBe('OFF')
    expect(onBtn().disabled).toBe(false)
    expect(offBtn().disabled).toBe(false)
  })

  it('shows a running lamp found on mount', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ state: 'on', window_left_s: 12 }))
    renderCard()
    await flush()
    expect(stateText()).toBe('ON')
    expect(screen.getByText('Window left: 12 s')).toBeTruthy()
  })

  it('keeps Off enabled before the first answer', () => {
    vi.mocked(api.fetchLamp).mockReturnValue(new Promise(() => {}))
    renderCard()
    expect(offBtn().disabled).toBe(false)
    expect(onBtn().disabled).toBe(true)
  })

  it('sends power and window on Lamp on, nothing before', async () => {
    vi.mocked(api.setLamp).mockResolvedValue(status({ state: 'on', window_left_s: 45 }))
    renderCard()
    await flush()
    fireEvent.change(screen.getByLabelText(/Power/), { target: { value: '50' } })
    fireEvent.change(screen.getByLabelText(/Window/), { target: { value: '45' } })
    expect(api.setLamp).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Power/).closest('label')?.textContent).toContain('90.0 deg')
    fireEvent.click(onBtn())
    await flush()
    expect(api.setLamp).toHaveBeenCalledWith({ power: 0.5, max_on_s: 45 })
    expect(stateText()).toBe('ON')
  })

  it('defaults to 30 percent and 30 s and clamps the window', async () => {
    vi.mocked(api.setLamp).mockResolvedValue(status({ state: 'on' }))
    renderCard()
    await flush()
    expect((screen.getByLabelText(/Power/) as HTMLInputElement).value).toBe('30')
    fireEvent.change(screen.getByLabelText(/Window/), { target: { value: '999' } })
    expect(screen.getByText(/using 120 s/)).toBeTruthy()
    fireEvent.click(onBtn())
    await flush()
    expect(api.setLamp).toHaveBeenCalledWith({ power: 0.3, max_on_s: 120 })
  })

  it('sends Off and shows the answer', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ state: 'on', window_left_s: 10 }))
    vi.mocked(api.lampOff).mockResolvedValue(status())
    renderCard()
    await flush()
    fireEvent.click(offBtn())
    await flush()
    expect(api.lampOff).toHaveBeenCalledTimes(1)
    expect(stateText()).toBe('OFF')
  })

  it('shows the cap from max_power on the slider', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ max_power: 0.6 }))
    renderCard()
    await flush()
    expect((screen.getByLabelText(/Power/) as HTMLInputElement).max).toBe('60')
    expect(screen.getByText(/Server limit: 60 %/)).toBeTruthy()
  })

  it('shows the tripped text, disables On, keeps Off', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(
      status({ state: 'tripped', tripped: true, budget_s: 40 }),
    )
    renderCard()
    await flush()
    expect(stateText()).toBe('TRIPPED')
    expect(
      screen.getByText(
        'Tripped: the lamp is off to protect the lamp and the panels. Wait 40 s, then press Off and ask again',
      ),
    ).toBeTruthy()
    expect(onBtn().disabled).toBe(true)
    expect(offBtn().disabled).toBe(false)
  })

  it('does not treat budget 0 as blocked when not tripped', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ budget_s: 0 }))
    renderCard()
    await flush()
    expect(onBtn().disabled).toBe(false)
  })

  it('shows Lamp not available with the error and disables On only', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(
      status({ available: false, state: 'unavailable', error: 'no dimmer on this board' }),
    )
    renderCard()
    await flush()
    expect(screen.getByText('Lamp not available: no dimmer on this board')).toBeTruthy()
    expect(stateText()).toBe('NO LINK')
    expect(onBtn().disabled).toBe(true)
    expect(offBtn().disabled).toBe(false)
  })

  it('shows NO LINK when link_ok is false', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ link_ok: false }))
    renderCard()
    await flush()
    expect(stateText()).toBe('NO LINK')
    expect(onBtn().disabled).toBe(true)
  })

  it('shows chips for mains, locked and timed out', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ mains: false, locked: true, timed_out: true }))
    renderCard()
    await flush()
    expect(screen.getByText('No mains')).toBeTruthy()
    expect(screen.getByText('Locked')).toBeTruthy()
    expect(screen.getByText('Timed out')).toBeTruthy()
  })

  it('counts the window down live', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValue(status({ state: 'on', window_left_s: 10, budget_s: 100 }))
    renderCard()
    await flush()
    expect(screen.getByText('Window left: 10 s')).toBeTruthy()
    expect(screen.getByText('Lamp on time left: 100 s')).toBeTruthy()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    // polls return the same snapshot; the local clock moves it on
    vi.mocked(api.fetchLamp).mockReturnValue(new Promise(() => {}))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(screen.getByText(/Window left: [5-8] s/)).toBeTruthy()
  })

  it('shows NO LINK on a failed poll and status unknown after 3, Off stays on', async () => {
    vi.mocked(api.fetchLamp).mockResolvedValueOnce(status({ state: 'on', window_left_s: 20 }))
    renderCard()
    await flush()
    expect(stateText()).toBe('ON')
    vi.mocked(api.fetchLamp).mockRejectedValue(new Error('network'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(stateText()).toBe('NO LINK')
    expect(screen.queryByText(/status unknown/)).toBeNull()
    expect(screen.queryByText(/Window left/)).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByText(/status unknown/)).toBeTruthy()
    expect(onBtn().disabled).toBe(true)
    expect(offBtn().disabled).toBe(false)
  })

  it('stops polling when hidden and resumes when visible', async () => {
    renderCard()
    await flush()
    setVisibility('hidden')
    const n = vi.mocked(api.fetchLamp).mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(api.fetchLamp).toHaveBeenCalledTimes(n)
    setVisibility('visible')
    await flush()
    expect(vi.mocked(api.fetchLamp).mock.calls.length).toBe(n + 1)
  })

  it('shows the server message on 409 and 422 and does not retry', async () => {
    renderCard()
    await flush()
    vi.mocked(api.setLamp).mockRejectedValueOnce(
      new ApiError('POST /api/dimmer: dimmer is tripped', 409, 'dimmer is tripped'),
    )
    fireEvent.click(onBtn())
    await flush()
    expect(screen.getByText('dimmer is tripped')).toBeTruthy()
    vi.mocked(api.setLamp).mockRejectedValueOnce(
      new ApiError('POST /api/dimmer: max_on_s above 120', 422, 'max_on_s above 120'),
    )
    fireEvent.click(onBtn())
    await flush()
    expect(screen.getByText('max_on_s above 120')).toBeTruthy()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(api.setLamp).toHaveBeenCalledTimes(2)
  })

  it('does not send Off on unmount', async () => {
    const { unmount } = renderCard()
    await flush()
    unmount()
    expect(api.lampOff).not.toHaveBeenCalled()
  })

  it('does not poll in Demo mode but keeps Off enabled', async () => {
    renderCard('simulated')
    await flush()
    expect(api.fetchLamp).not.toHaveBeenCalled()
    expect(screen.getByText(/not available in Demo mode/)).toBeTruthy()
    expect(onBtn().disabled).toBe(true)
    expect(offBtn().disabled).toBe(false)
  })
})
