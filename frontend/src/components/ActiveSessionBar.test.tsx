import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActiveSessionBar } from './ActiveSessionBar'
import { ActiveSessionNotice } from './ActiveSessionNotice'
import { ActiveSessionProvider } from './ActiveSessionProvider'
import { ACTIVE_SESSION_STORAGE_KEY } from '@/lib/activeSession'
import { CaptureModeContext } from '@/lib/captureMode'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function remember() {
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, '{"id":"s1","title":"Panel A alone"}')
}

const VIEWING: ImportedSessionValue = {
  active: true,
  title: 'A file',
  setup: null,
  session: null,
  curves: [],
  runs: [],
  missing: { curve_ids: [], run_ids: [] },
  enter: () => {},
  close: () => {},
}

describe('ActiveSessionBar', () => {
  it('names the session captures are being filed into', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <ActiveSessionBar />
      </ActiveSessionProvider>,
    )
    expect(screen.getByRole('status').textContent).toContain('Panel A alone')
  })

  it('renders nothing when no session is active', () => {
    render(
      <ActiveSessionProvider>
        <ActiveSessionBar />
      </ActiveSessionProvider>,
    )
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('is dismissable: Stop filing clears the session and what was remembered', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <ActiveSessionBar />
      </ActiveSessionProvider>,
    )
    fireEvent.click(screen.getByText('Stop filing'))
    expect(screen.queryByRole('status')).toBeNull()
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('opens the session on request', () => {
    remember()
    const onOpen = vi.fn()
    render(
      <ActiveSessionProvider>
        <ActiveSessionBar onOpen={onOpen} />
      </ActiveSessionProvider>,
    )
    fireEvent.click(screen.getByText('Open session'))
    expect(onOpen).toHaveBeenCalledWith('s1')
  })

  it('is not shown in demo mode', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
          <ActiveSessionBar />
        </CaptureModeContext.Provider>
      </ActiveSessionProvider>,
    )
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('is not shown while viewing an imported session file', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <ImportedSessionContext.Provider value={VIEWING}>
          <ActiveSessionBar />
        </ImportedSessionContext.Provider>
      </ActiveSessionProvider>,
    )
    expect(screen.queryByRole('status')).toBeNull()
  })
})

describe('ActiveSessionNotice (Measure pane and run form)', () => {
  it('says the next curve or run will be filed into the session', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <ActiveSessionNotice what="curve" />
        <ActiveSessionNotice what="run" />
      </ActiveSessionProvider>,
    )
    const notices = screen.getAllByTestId('active-session-notice')
    expect(notices[0].textContent).toContain('This curve will be filed into session')
    expect(notices[0].textContent).toContain('Panel A alone')
    expect(notices[1].textContent).toContain('This run will be filed into session')
  })

  it('says so plainly when no session is active', () => {
    render(
      <ActiveSessionProvider>
        <ActiveSessionNotice what="curve" />
      </ActiveSessionProvider>,
    )
    expect(screen.getByTestId('active-session-notice').textContent).toContain(
      'Not filed into any session',
    )
  })

  it('renders nothing in demo mode', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
          <ActiveSessionNotice what="run" />
        </CaptureModeContext.Provider>
      </ActiveSessionProvider>,
    )
    expect(screen.queryByTestId('active-session-notice')).toBeNull()
  })

  it('renders nothing while viewing an imported session file', () => {
    remember()
    render(
      <ActiveSessionProvider>
        <ImportedSessionContext.Provider value={VIEWING}>
          <ActiveSessionNotice what="curve" />
        </ImportedSessionContext.Provider>
      </ActiveSessionProvider>,
    )
    expect(screen.queryByTestId('active-session-notice')).toBeNull()
  })
})
