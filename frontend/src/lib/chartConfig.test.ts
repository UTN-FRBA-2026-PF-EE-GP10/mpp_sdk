import { describe, expect, it } from 'vitest'
import {
  CURRENT_COLOR,
  fadeColor,
  ivChartOptions,
  markerRingColor,
  MPP_COLOR,
  POWER_COLOR,
  referenceColor,
  TRAIL_COLOR,
} from './chartConfig'

describe('the validated chart palette', () => {
  it('keeps the three series colours distinct from each other', () => {
    expect(new Set([CURRENT_COLOR, POWER_COLOR, MPP_COLOR]).size).toBe(3)
  })

  it('derives the trail from the MPP/operating-point colour, not a fourth hue', () => {
    expect(TRAIL_COLOR).toBe(fadeColor(MPP_COLOR, 0.5))
  })
})

describe('fadeColor', () => {
  it('converts a hex colour to a translucent rgba string', () => {
    expect(fadeColor('#ff0000', 0.5)).toBe('rgba(255, 0, 0, 0.5)')
  })
})

describe('referenceColor', () => {
  it('is a neutral, not one of the three categorical series colours', () => {
    expect(referenceColor(false)).not.toContain(CURRENT_COLOR.slice(1))
    expect(referenceColor(true)).not.toContain(POWER_COLOR.slice(1))
  })

  it('differs between light and dark so it stays visible on either surface', () => {
    expect(referenceColor(false)).not.toBe(referenceColor(true))
  })
})

describe('markerRingColor', () => {
  it('differs between light and dark - the ring must follow the surface, not be hardcoded white', () => {
    expect(markerRingColor(false)).not.toBe(markerRingColor(true))
  })
})

describe('ivChartOptions', () => {
  it('sets legend and axis text colour explicitly, so dark mode is never left to chart.js defaults', () => {
    const light = ivChartOptions('mA', 'mW', false)
    const dark = ivChartOptions('mA', 'mW', true)
    expect(light.plugins?.legend?.labels?.color).toBeTruthy()
    expect(dark.plugins?.legend?.labels?.color).toBeTruthy()
    expect(light.plugins?.legend?.labels?.color).not.toBe(dark.plugins?.legend?.labels?.color)
  })
})
