import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ImportedSessionProvider } from './ImportedSessionProvider'
import { buildSessionFile, useImportedSession } from '@/lib/sessionFile'

afterEach(cleanup)

function Probe() {
  const importedSession = useImportedSession()
  return (
    <div>
      <span data-testid="active">{String(importedSession.active)}</span>
      <span data-testid="title">{importedSession.title ?? ''}</span>
      <span data-testid="curve-count">{importedSession.curves.length}</span>
      <button
        onClick={() =>
          importedSession.enter(
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
      <button onClick={importedSession.close}>close</button>
    </div>
  )
}

describe('ImportedSessionProvider', () => {
  it('starts inactive', () => {
    render(
      <ImportedSessionProvider>
        <Probe />
      </ImportedSessionProvider>,
    )
    expect(screen.getByTestId('active').textContent).toBe('false')
  })

  it('activates on enter and exposes the imported session content', () => {
    render(
      <ImportedSessionProvider>
        <Probe />
      </ImportedSessionProvider>,
    )
    fireEvent.click(screen.getByText('enter'))
    expect(screen.getByTestId('active').textContent).toBe('true')
    expect(screen.getByTestId('title').textContent).toBe('A test session')
    expect(screen.getByTestId('curve-count').textContent).toBe('1')
  })

  it('close clears the imported session back to inactive', () => {
    render(
      <ImportedSessionProvider>
        <Probe />
      </ImportedSessionProvider>,
    )
    fireEvent.click(screen.getByText('enter'))
    fireEvent.click(screen.getByText('close'))
    expect(screen.getByTestId('active').textContent).toBe('false')
    expect(screen.getByTestId('curve-count').textContent).toBe('0')
  })

  it('useImportedSession fails safe (inactive) outside a provider, rather than throwing', () => {
    render(<Probe />)
    expect(screen.getByTestId('active').textContent).toBe('false')
  })
})
