import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { SessionProvider } from './SessionProvider'
import { buildSessionFile, useSession } from '@/lib/session'

afterEach(cleanup)

function Probe() {
  const session = useSession()
  return (
    <div>
      <span data-testid="active">{String(session.active)}</span>
      <span data-testid="title">{session.title ?? ''}</span>
      <span data-testid="curve-count">{session.curves.length}</span>
      <button
        onClick={() =>
          session.enter(
            buildSessionFile({
              title: 'A test session',
              setup: 'single',
              curves: [
                {
                  id: 'c1',
                  path: '/data/curves/c1.json',
                  captured_at: '2026-09-19T16:00:00Z',
                  label: 'Curve 1',
                  measurement: 'baseline',
                  panels: [],
                  notes: '',
                  n_points: 0,
                  source: 'hardware',
                  voc: 0,
                  isc: 0,
                  p_mpp: 0,
                  points: [],
                },
              ],
              runs: [],
            }),
          )
        }
      >
        enter
      </button>
      <button onClick={session.close}>close</button>
    </div>
  )
}

describe('SessionProvider', () => {
  it('starts inactive', () => {
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('false')
  })

  it('activates on enter and exposes the session content', () => {
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    fireEvent.click(screen.getByText('enter'))
    expect(screen.getByTestId('active').textContent).toBe('true')
    expect(screen.getByTestId('title').textContent).toBe('A test session')
    expect(screen.getByTestId('curve-count').textContent).toBe('1')
  })

  it('close clears the session back to inactive', () => {
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    fireEvent.click(screen.getByText('enter'))
    fireEvent.click(screen.getByText('close'))
    expect(screen.getByTestId('active').textContent).toBe('false')
    expect(screen.getByTestId('curve-count').textContent).toBe('0')
  })

  it('useSession fails safe (inactive) outside a provider, rather than throwing', () => {
    render(<Probe />)
    expect(screen.getByTestId('active').textContent).toBe('false')
  })
})
