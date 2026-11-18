import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CurveWorkbench } from './CurveWorkbench'
import { LampCard } from './LampCard'
import { LampProvider } from './LampProvider'
import { RunPane } from './RunPane'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'
import type { LampStatus } from '@/lib/api'
import { SetupModeContext } from '@/lib/setupMode'

// The real api module runs against a mocked fetch: these tests pin the
// request bodies and the server messages, not the module's own helpers.
vi.mock('react-chartjs-2', () => ({ Line: () => null }))

type Handler = (body: unknown) => { status?: number; json?: unknown }

let handlers: Record<string, Handler>
let calls: { key: string; body: unknown }[]

function lampStatus(over: Partial<LampStatus> = {}): LampStatus {
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

const RUN_CONFIG = {
  algorithms: ['P&O'],
  max_duration_s: 600,
  default_duration_s: 10,
  default_initial_duty: 0.5,
  default_v_max: 40,
  default_i_max: 1,
  default_v_out_max: 25,
}

function sweepData(over: Record<string, unknown> = {}) {
  return {
    points: [],
    partial: [],
    active: false,
    link: 'ok',
    seq: 0,
    command_error: null,
    demo_source: false,
    ...over,
  }
}

function liveRun(over: Record<string, unknown> = {}) {
  return {
    status: 'running',
    algorithm: 'P&O',
    label: 'bench run',
    curve_ref: null,
    n_samples: 0,
    downsampled: false,
    samples: [],
    voltage: null,
    current: null,
    duty: null,
    vout: null,
    aborted: false,
    abort_reason: null,
    saved_run_id: null,
    source: 'hardware',
    ...over,
  }
}

beforeEach(() => {
  calls = []
  handlers = {
    'GET /api/dimmer': () => ({ json: lampStatus() }),
    'POST /api/dimmer/off': () => ({ json: lampStatus() }),
    'GET /api/data': () => ({ json: sweepData() }),
    'GET /api/run-config': () => ({ json: RUN_CONFIG }),
    'GET /api/runs/live': () => ({ json: liveRun({ status: 'idle', algorithm: null }) }),
    'POST /api/start-sweep': () => ({ status: 204 }),
    'POST /api/runs/start': () => ({ json: { status: 'started', duration_s: 10 } }),
    'POST /api/runs/stop': () => ({ status: 204 }),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const key = `${method} ${String(url).split('?')[0]}`
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ key, body })
      const h = handlers[key]
      if (!h) return new Response('{}', { status: 404 })
      const out = h(body)
      const status = out.status ?? 200
      return new Response(status === 204 ? null : JSON.stringify(out.json ?? {}), { status })
    }),
  )
  vi.stubGlobal('confirm', () => true)
  window.confirm = () => true
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const count = (key: string) => calls.filter((c) => c.key === key).length
const bodyOf = (key: string) => calls.filter((c) => c.key === key).at(-1)?.body

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeContext.Provider value={{ mode: 'full', setMode: vi.fn() }}>
          <LampProvider>{children}</LampProvider>
        </SetupModeContext.Provider>
      </UnitsProvider>
    </ThemeProvider>
  )
}

function renderSweep() {
  return render(
    <Providers>
      <LampCard />
      <CurveWorkbench kind="baseline" records={[]} connected onSaved={vi.fn()} />
    </Providers>,
  )
}

function renderRun() {
  return render(
    <Providers>
      <LampCard />
      <RunPane curves={[]} connectionStatus="connected" onRunSaved={vi.fn()} />
    </Providers>,
  )
}

const checkbox = () => screen.getByLabelText('Use the lamp for this measurement') as HTMLInputElement

async function lampReady() {
  await waitFor(() => expect(screen.getByTestId('lamp-state').textContent).toBe('OFF'))
}

function startButton(name: string) {
  return screen.getByRole('button', { name }) as HTMLButtonElement
}

describe('lamp option on a sweep', () => {
  it('sends no body when the option is off', async () => {
    renderSweep()
    await lampReady()
    fireEvent.click(startButton('Start Measurement'))
    await waitFor(() => expect(count('POST /api/start-sweep')).toBe(1))
    expect(bodyOf('POST /api/start-sweep')).toBeUndefined()
    expect(checkbox().checked).toBe(false)
  })

  it('sends the card power and the warm-up, with the option on', async () => {
    renderSweep()
    await lampReady()
    fireEvent.click(checkbox())
    fireEvent.click(startButton('Start Measurement'))
    await waitFor(() => expect(count('POST /api/start-sweep')).toBe(1))
    expect(bodyOf('POST /api/start-sweep')).toEqual({ lamp: { power: 0.3, warmup_s: 3 } })
  })

  it('follows the card slider until the option has its own value, and clamps the warm-up', async () => {
    renderSweep()
    await lampReady()
    fireEvent.change(screen.getAllByRole('slider')[0], { target: { value: '55' } })
    fireEvent.click(checkbox())
    fireEvent.change(screen.getByLabelText('Warm-up (s)'), { target: { value: '99' } })
    fireEvent.click(startButton('Start Measurement'))
    await waitFor(() => expect(count('POST /api/start-sweep')).toBe(1))
    expect(bodyOf('POST /api/start-sweep')).toEqual({ lamp: { power: 0.55, warmup_s: 30 } })
  })

  it('says the lamp stays on until the sweep ends', async () => {
    renderSweep()
    await lampReady()
    fireEvent.click(checkbox())
    expect(screen.getByText(/until the sweep ends/)).toBeTruthy()
  })

  it.each([
    [422, 'warm-up plus the measurement would exceed 110 s'],
    [409, 'dimmer tripped, wait 42 s'],
    [503, 'no confirmed dimmer link'],
  ])('shows the server message for %i and does not retry', async (status, detail) => {
    handlers['POST /api/start-sweep'] = () => ({ status, json: { detail } })
    renderSweep()
    await lampReady()
    fireEvent.click(checkbox())
    fireEvent.click(startButton('Start Measurement'))
    await waitFor(() => expect(screen.getByText(new RegExp(detail))).toBeTruthy())
    await new Promise((r) => setTimeout(r, 50))
    expect(count('POST /api/start-sweep')).toBe(1)
  })

  it('disables the option with the reason when the lamp is not available', async () => {
    handlers['GET /api/dimmer'] = () => ({ json: lampStatus({ available: false, error: 'no dimmer' }) })
    renderSweep()
    await waitFor(() => expect(screen.getByText(/The lamp is not available: no dimmer/)).toBeTruthy())
    expect(checkbox().disabled).toBe(true)
  })

  it('disables the option with the reason when the lamp is tripped', async () => {
    handlers['GET /api/dimmer'] = () => ({
      json: lampStatus({ state: 'tripped', tripped: true, budget_s: 40 }),
    })
    renderSweep()
    await waitFor(() => expect(screen.getByText(/The lamp is tripped/)).toBeTruthy())
    expect(checkbox().disabled).toBe(true)
    expect(startButton('Off').disabled).toBe(false)
  })

  it('shows the warm-up countdown, then the measuring text', async () => {
    handlers['GET /api/data'] = () => ({
      json: sweepData({ active: true, lamp_phase: 'warming', lamp_warmup_left_s: 2.4 }),
    })
    renderSweep()
    await waitFor(() => expect(screen.getByText('Warming up the lamp, 3 s')).toBeTruthy())
    handlers['GET /api/data'] = () => ({ json: sweepData({ active: true, lamp_phase: 'measuring' }) })
    await waitFor(() => expect(screen.getByText('Lamp on for the measurement')).toBeTruthy(), {
      timeout: 3000,
    })
  })

  it('treats an unknown phase as none', async () => {
    handlers['GET /api/data'] = () => ({ json: sweepData({ lamp_phase: 'bogus' }) })
    renderSweep()
    await lampReady()
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText(/Warming up|Lamp on for/)).toBeNull()
  })

  it('polls the lamp once for the card and the option together', async () => {
    renderSweep()
    await lampReady()
    fireEvent.click(checkbox())
    expect(count('GET /api/dimmer')).toBe(1)
  })
})

describe('lamp option on a run', () => {
  async function ready() {
    renderRun()
    await lampReady()
    await waitFor(() => expect(screen.getByText('P&O')).toBeTruthy())
  }

  it('sends no lamp field when the option is off', async () => {
    await ready()
    fireEvent.click(startButton('Start run'))
    await waitFor(() => expect(count('POST /api/runs/start')).toBe(1))
    expect(bodyOf('POST /api/runs/start')).not.toHaveProperty('lamp')
  })

  it('sends the lamp object with the option on', async () => {
    await ready()
    fireEvent.click(checkbox())
    expect(screen.getByText(/13 s \(3 s warm-up plus the run\)/)).toBeTruthy()
    fireEvent.click(startButton('Start run'))
    await waitFor(() => expect(count('POST /api/runs/start')).toBe(1))
    expect(bodyOf('POST /api/runs/start')).toMatchObject({ lamp: { power: 0.3, warmup_s: 3 } })
  })

  it('disables Start with the reason when warm-up plus duration is over 110 s', async () => {
    await ready()
    fireEvent.click(checkbox())
    fireEvent.change(screen.getByLabelText('Duration (s)'), { target: { value: '108' } })
    const start = startButton('Start run')
    expect(start.getAttribute('aria-disabled')).toBe('true')
    expect(screen.getByText(/on for 111 s .* limit is 110 s/)).toBeTruthy()
    fireEvent.click(start)
    expect(count('POST /api/runs/start')).toBe(0)
    fireEvent.change(screen.getByLabelText('Duration (s)'), { target: { value: '107' } })
    expect(startButton('Start run').getAttribute('aria-disabled')).not.toBe('true')
  })

  it('does not block a long run when the option is off', async () => {
    await ready()
    fireEvent.change(screen.getByLabelText('Duration (s)'), { target: { value: '300' } })
    expect(startButton('Start run').getAttribute('aria-disabled')).not.toBe('true')
  })

  it.each([
    [422, 'warm-up plus the measurement would exceed 110 s'],
    [409, 'dimmer tripped, wait 42 s'],
    [503, 'no confirmed dimmer link'],
  ])('shows the server message for %i and does not retry', async (status, detail) => {
    handlers['POST /api/runs/start'] = () => ({ status, json: { detail } })
    await ready()
    fireEvent.click(checkbox())
    fireEvent.click(startButton('Start run'))
    await waitFor(() => expect(screen.getByText(`Failed to start: ${detail}`)).toBeTruthy())
    await new Promise((r) => setTimeout(r, 50))
    expect(count('POST /api/runs/start')).toBe(1)
  })

  it('disables the option when the lamp is not available', async () => {
    handlers['GET /api/dimmer'] = () => ({ json: lampStatus({ link_ok: false }) })
    renderRun()
    await waitFor(() => expect(screen.getByText(/The lamp is not available/)).toBeTruthy())
    expect(checkbox().disabled).toBe(true)
  })

  it('shows the warm-up text and Stop cancels the run during warm-up', async () => {
    handlers['GET /api/runs/live'] = () => ({
      json: liveRun({ lamp_phase: 'warming', lamp_warmup_left_s: 1.2 }),
    })
    renderRun()
    await waitFor(() => expect(screen.getByText('Warming up the lamp, 2 s')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Stop run' }))
    await waitFor(() => expect(count('POST /api/runs/stop')).toBe(1))
    // The lamp card keeps its own Off, always enabled.
    expect(startButton('Off').disabled).toBe(false)
  })

  it('shows the measuring text', async () => {
    handlers['GET /api/runs/live'] = () => ({ json: liveRun({ lamp_phase: 'measuring' }) })
    renderRun()
    await waitFor(() => expect(screen.getByText('Lamp on for the measurement')).toBeTruthy())
  })
})
