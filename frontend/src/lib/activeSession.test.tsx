import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActiveSessionProvider } from '@/components/ActiveSessionProvider'
import { CaptureModeContext } from '@/lib/captureMode'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'
import {
  ACTIVE_SESSION_STORAGE_KEY,
  filterToSession,
  parseStoredActiveSession,
  useActiveSession,
  useCaptureSession,
} from './activeSession'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function Probe() {
  const { active, setActive, clear } = useActiveSession()
  const capture = useCaptureSession()
  return (
    <div>
      <span data-testid="active">{active ? `${active.id}|${active.title}` : 'none'}</span>
      <span data-testid="capture">{capture ? capture.id : 'none'}</span>
      <button type="button" onClick={() => setActive('s1', 'Panel A')}>
        set
      </button>
      <button type="button" onClick={clear}>
        clear
      </button>
    </div>
  )
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

describe('ActiveSessionProvider', () => {
  it('starts with no active session', () => {
    render(
      <ActiveSessionProvider>
        <Probe />
      </ActiveSessionProvider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('none')
  })

  it('persists the active session across a remount, and clearing removes it', () => {
    const first = render(
      <ActiveSessionProvider>
        <Probe />
      </ActiveSessionProvider>,
    )
    fireEvent.click(screen.getByText('set'))
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toContain('s1')
    first.unmount()

    const second = render(
      <ActiveSessionProvider>
        <Probe />
      </ActiveSessionProvider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('s1|Panel A')

    fireEvent.click(screen.getByText('clear'))
    expect(screen.getByTestId('active').textContent).toBe('none')
    expect(window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull()
    second.unmount()
  })

  it('ignores a stored value that is not an id/title pair', () => {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, '{"id":42}')
    render(
      <ActiveSessionProvider>
        <Probe />
      </ActiveSessionProvider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('none')
  })

  it('files nothing when rendered without a provider', () => {
    render(<Probe />)
    expect(screen.getByTestId('active').textContent).toBe('none')
  })
})

describe('parseStoredActiveSession', () => {
  it.each([null, '', 'not json', '[]', '{"id":"","title":"x"}', '{"id":"a"}', '{"id":1,"title":"x"}'])(
    'rejects %j',
    (raw) => {
      expect(parseStoredActiveSession(raw)).toBeNull()
    },
  )

  it('accepts an id and a title', () => {
    expect(parseStoredActiveSession('{"id":"a","title":"b"}')).toEqual({ id: 'a', title: 'b' })
  })
})

describe('useCaptureSession (read-only gating)', () => {
  function renderWith(ui: ReactNode) {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, '{"id":"s1","title":"Panel A"}')
    return render(<ActiveSessionProvider>{ui}</ActiveSessionProvider>)
  }

  it('files into the active session normally', () => {
    renderWith(<Probe />)
    expect(screen.getByTestId('capture').textContent).toBe('s1')
  })

  it('files nothing in demo mode, even with an active session remembered', () => {
    renderWith(
      <CaptureModeContext.Provider value={{ mode: 'simulated', setMode: vi.fn() }}>
        <Probe />
      </CaptureModeContext.Provider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('s1|Panel A')
    expect(screen.getByTestId('capture').textContent).toBe('none')
  })

  it('files nothing while viewing an imported session file', () => {
    renderWith(
      <ImportedSessionContext.Provider value={VIEWING}>
        <Probe />
      </ImportedSessionContext.Provider>,
    )
    expect(screen.getByTestId('capture').textContent).toBe('none')
  })
})

describe('filterToSession', () => {
  const items = [
    { id: 'a', session_id: 's1' },
    { id: 'b', session_id: 's2' },
    { id: 'c', session_id: null },
    { id: 'd' }, // an older record with no stamp at all
    { id: 'e', session_id: 'deleted-session' },
  ]

  it('keeps everything under "all"', () => {
    expect(filterToSession(items, 'all', 's1')).toEqual(items)
  })

  it('keeps only what carries the active session under "session"', () => {
    expect(filterToSession(items, 'session', 's1').map((i) => i.id)).toEqual(['a'])
  })

  it('shows everything when there is no active session, whatever the scope', () => {
    expect(filterToSession(items, 'session', null)).toEqual(items)
  })

  it('treats a stamp naming a deleted session as a plain non-match, not an error', () => {
    expect(filterToSession(items, 'session', 's3')).toEqual([])
    expect(filterToSession(items, 'all', 's3').map((i) => i.id)).toContain('e')
  })
})
