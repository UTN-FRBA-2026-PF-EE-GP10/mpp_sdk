import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CaptureModeContext } from '@/lib/captureMode'
import { ImportedSessionContext, type ImportedSessionValue, useReadOnly } from '@/lib/sessionFile'

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

const INACTIVE_IMPORTED_SESSION: ImportedSessionValue = {
  active: false,
  title: null,
  setup: null,
  session: null,
  curves: [],
  runs: [],
  missing: { curve_ids: [], run_ids: [] },
  enter: () => {},
  close: () => {},
}

const ACTIVE_IMPORTED_SESSION: ImportedSessionValue = {
  ...INACTIVE_IMPORTED_SESSION,
  active: true,
  title: 'A session',
}

describe('useReadOnly', () => {
  it('is off with neither demo mode nor an imported session active', () => {
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

  it('is on with reason "view" while an imported session is active', () => {
    render(
      <ImportedSessionContext.Provider value={ACTIVE_IMPORTED_SESSION}>
        <Probe />
      </ImportedSessionContext.Provider>,
    )
    expect(screen.getByTestId('enabled').textContent).toBe('true')
    expect(screen.getByTestId('reason').textContent).toBe('view')
  })

  it('prefers "view" when both demo mode and an imported session are active', () => {
    render(
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        <ImportedSessionContext.Provider value={ACTIVE_IMPORTED_SESSION}>
          <Probe />
        </ImportedSessionContext.Provider>
      </CaptureModeContext.Provider>,
    )
    expect(screen.getByTestId('reason').textContent).toBe('view')
  })
})
