import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PicoConfigPane } from './PicoConfigPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import { CaptureModeContext, type CaptureMode } from '@/lib/captureMode'
import * as api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  fetchPicoConfig: vi.fn(),
  sendPicoConfig: vi.fn(),
  resetPicoCutoff: vi.fn(),
}))

const mockConfigData: api.PicoConfigResponse = {
  config: {
    vin_range: 'low',
    vout_range: 'low',
    ron_mohm: 6,
    max31865: false,
    i_max_ma: 1000,
    v_max_mv: 40000,
    psu_enabled: false,
    psu_open_loop: false,
    psu_vout_target_mv: 5000,
    psu_fixed_duty: 0.5,
  },
  defaults: {
    vin_range: 'low',
    vout_range: 'low',
    ron_mohm: 6,
    max31865: false,
    i_max_ma: 1000,
    v_max_mv: 40000,
    psu_enabled: false,
    psu_open_loop: false,
    psu_vout_target_mv: 5000,
    psu_fixed_duty: 0.5,
  },
  last_applied_at: null,
  last_error: null,
}

function renderPane(mode: CaptureMode = 'hardware', connected: boolean = true) {
  return render(
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeContext.Provider value={{ mode, setMode: vi.fn() }}>
          <PicoConfigPane connected={connected} />
        </CaptureModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>,
  )
}

describe('PicoConfigPane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchPicoConfig).mockResolvedValue(mockConfigData)
    vi.mocked(api.sendPicoConfig).mockResolvedValue({
      status: 'ok',
      applied: mockConfigData.config,
    })
    vi.mocked(api.resetPicoCutoff).mockResolvedValue(undefined)
  })

  afterEach(cleanup)

  it('renders hardware settings and fetches current config on mount', async () => {
    renderPane('hardware')
    await waitFor(() => {
      expect(api.fetchPicoConfig).toHaveBeenCalled()
    })

    expect(screen.getByText('Pico Dynamic Configuration')).toBeTruthy()
    expect(screen.getByText('ADC Voltage Dividers')).toBeTruthy()
    expect(screen.getByText('Power Stage & Sensors')).toBeTruthy()
    expect(screen.getByText('Hardware Safety Cutoffs')).toBeTruthy()
    expect(screen.getByText('Bench Power Supply Mode')).toBeTruthy()
  })

  it('allows selecting and deselecting all configs for batch sending', async () => {
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    const deselectBtn = screen.getByRole('button', { name: /^Deselect All$/i })
    fireEvent.click(deselectBtn)

    // Select All
    const selectAllBtn = screen.getByRole('button', { name: /^Select All$/i })
    fireEvent.click(selectAllBtn)

    expect(screen.getByRole('button', { name: /Send Selected \(9\)/i })).toBeTruthy()
  })

  it('resets form fields to default values when Reset to Defaults is clicked', async () => {
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    // Change Ron input
    const ronInput = screen.getByLabelText(/On-resistance/i)
    fireEvent.change(ronInput, { target: { value: '15' } })
    expect((ronInput as HTMLInputElement).value).toBe('15')

    // Click Reset to Defaults
    const resetBtn = screen.getByRole('button', { name: /Reset to Defaults/i })
    fireEvent.click(resetBtn)

    expect((ronInput as HTMLInputElement).value).toBe('6')
    expect(screen.getByText(/Form inputs reset to default values/i)).toBeTruthy()
  })

  it('sends selected configs in batch when Send Selected is clicked', async () => {
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    const sendSelectedBtn = screen.getByRole('button', { name: /Send.*Selected/i })
    fireEvent.click(sendSelectedBtn)

    await waitFor(() => {
      expect(api.sendPicoConfig).toHaveBeenCalled()
    })
  })

  it('sends a single field immediately when its individual Send button is clicked', async () => {
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    // Click Send Ron button
    const sendRonBtn = screen.getByRole('button', { name: /Send Ron/i })
    fireEvent.click(sendRonBtn)

    await waitFor(() => {
      expect(api.sendPicoConfig).toHaveBeenCalledWith({ ron_mohm: 6 })
    })
  })

  it('triggers cutoff reset when Reset Cutoff is clicked', async () => {
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    const resetCutoffBtn = screen.getByRole('button', { name: /Reset Cutoff/i })
    fireEvent.click(resetCutoffBtn)

    await waitFor(() => {
      expect(api.resetPicoCutoff).toHaveBeenCalled()
    })
    expect(
      screen.getByText(/Hardware cutoff reset signal dispatched/i),
    ).toBeTruthy()
  })

  it('displays error feedback when sendPicoConfig rejects', async () => {
    vi.mocked(api.sendPicoConfig).mockRejectedValueOnce(new Error('SPI link busy'))
    renderPane('hardware')
    await waitFor(() => expect(api.fetchPicoConfig).toHaveBeenCalled())

    const sendRonBtn = screen.getByRole('button', { name: /Send Ron/i })
    fireEvent.click(sendRonBtn)

    await waitFor(() => {
      expect(screen.getByText('SPI link busy')).toBeTruthy()
    })
  })
})
