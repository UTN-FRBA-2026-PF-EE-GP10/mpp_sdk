import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CaptureModeContext } from '@/lib/captureMode'
import { SessionContext, type SessionValue, useReadOnly } from '@/lib/session'

afterEach(cleanup)

function Probe() {
  const readOnly = useReadOnly()
  return (
    <div>
      <span data-testid="enabled">{String(readOnly.enabled)}</span>
      <span data-testid="reason">{readOnly.reason ?? ''}</span>
    </div>
  )
}

const INACTIVE_SESSION: SessionValue = {
  active: false,
  title: null,
  setup: null,
  report: null,
  curves: [],
  runs: [],
  missing: { curve_ids: [], run_ids: [] },
  enter: () => {},
  close: () => {},
}

const ACTIVE_SESSION: SessionValue = { ...INACTIVE_SESSION, active: true, title: 'A session' }

describe('useReadOnly', () => {
  it('is off with neither demo mode nor a session active', () => {
    render(<Probe />)
    expect(screen.getByTestId('enabled').textContent).toBe('false')
  })

  it('is on with reason "demo" in demo (sandbox) mode', () => {
    render(
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        <Probe />
      </CaptureModeContext.Provider>,
    )
    expect(screen.getByTestId('enabled').textContent).toBe('true')
    expect(screen.getByTestId('reason').textContent).toBe('demo')
  })

  it('is on with reason "view" while a session is active', () => {
    render(
      <SessionContext.Provider value={ACTIVE_SESSION}>
        <Probe />
      </SessionContext.Provider>,
    )
    expect(screen.getByTestId('enabled').textContent).toBe('true')
    expect(screen.getByTestId('reason').textContent).toBe('view')
  })

  it('prefers "view" when both demo mode and a session are active', () => {
    render(
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        <SessionContext.Provider value={ACTIVE_SESSION}>
          <Probe />
        </SessionContext.Provider>
      </CaptureModeContext.Provider>,
    )
    expect(screen.getByTestId('reason').textContent).toBe('view')
  })
})
