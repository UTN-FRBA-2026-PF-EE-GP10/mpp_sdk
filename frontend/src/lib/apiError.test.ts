import { describe, expect, it } from 'vitest'
import { ApiError, isSessionNotFound } from './apiError'

describe('isSessionNotFound', () => {
  it('is true for the 404 the server sends for a session id that names no session', () => {
    expect(isSessionNotFound(new ApiError('POST /x: session not found', 404, 'session not found'))).toBe(
      true,
    )
  })

  it('is false for another 404, such as a missing reference curve', () => {
    expect(isSessionNotFound(new ApiError('POST /x: curve not found', 404, 'curve not found'))).toBe(false)
  })

  it('is false for a non-404 status and for errors that are not from the server', () => {
    expect(isSessionNotFound(new ApiError('POST /x: session not found', 500, 'session not found'))).toBe(
      false,
    )
    expect(isSessionNotFound(new Error('session not found'))).toBe(false)
    expect(isSessionNotFound(null)).toBe(false)
  })
})
