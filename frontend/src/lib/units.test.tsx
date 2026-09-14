import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { UnitsProvider } from '@/components/UnitsProvider'
import { useUnits } from './units'

afterEach(() => {
  cleanup()
  // The provider persists the mode, so without this a flip in one test
  // becomes the starting mode of the next one.
  window.localStorage.clear()
})

/** Exercises the hook the way a real consumer does - reading formatted
 * values and flipping the mode through a control - rather than capturing
 * the hook's return value out of render. */
function Probe() {
  const { mode, setMode, factor, formatCurrent, formatPower } = useUnits()
  return (
    <div>
      <span data-testid="current">{formatCurrent(0.229)}</span>
      <span data-testid="small-current">{formatCurrent(0.006)}</span>
      <span data-testid="power">{formatPower(3.0722)}</span>
      <span data-testid="factor">{factor}</span>
      <button type="button" onClick={() => setMode(mode === 'milli' ? 'base' : 'milli')}>
        flip
      </button>
    </div>
  )
}

function renderProbe() {
  render(
    <UnitsProvider>
      <Probe />
    </UnitsProvider>,
  )
}

const text = (id: string) => screen.getByTestId(id).textContent

describe('useUnits', () => {
  it('defaults to milli units, which suit the lamp-lit bench', () => {
    renderProbe()
    expect(text('current')).toBe('229.0 mA')
    expect(text('power')).toBe('3072.2 mW')
    expect(text('factor')).toBe('1000')
  })

  it('switches current and power together', () => {
    renderProbe()
    fireEvent.click(screen.getByText('flip'))
    expect(text('current')).toBe('0.229 A')
    expect(text('power')).toBe('3.072 W')
    expect(text('factor')).toBe('1')
  })

  it('keeps a small current readable in base units', () => {
    // 6 mA is a real first-point reading off this bench. At two decimals
    // it would round to 0.01 A and read as noise.
    renderProbe()
    fireEvent.click(screen.getByText('flip'))
    expect(text('small-current')).toBe('0.006 A')
  })

  it('throws outside a provider rather than silently ignoring the toggle', () => {
    expect(() => render(<Probe />)).toThrow(/UnitsProvider/)
  })
})
