import { describe, expect, it } from 'vitest'
import { abortReasonMessage } from './liveRun'

describe('abortReasonMessage', () => {
  it('explains overvoltage', () => {
    expect(abortReasonMessage('overvoltage')).toMatch(/v_max/)
  })

  it('explains overcurrent', () => {
    expect(abortReasonMessage('overcurrent')).toMatch(/i_max/)
  })

  it('explains link-down', () => {
    expect(abortReasonMessage('link-down')).toMatch(/link to the board was lost/)
  })

  it('explains an operator-requested stop', () => {
    expect(abortReasonMessage('stopped')).toMatch(/stopped by the operator/)
  })

  it('falls back to the raw reason for an unrecognised value', () => {
    expect(abortReasonMessage('completed; failed to save: disk full')).toBe(
      'completed; failed to save: disk full',
    )
  })

  it('reads as unknown, not unaborted, when the reason is missing', () => {
    expect(abortReasonMessage(null)).toMatch(/no reason was recorded/)
  })
})

