// Mirrors mpp_sdk/curves/record.py's on-disk schema and
// scripts/curve_tracer_server.py's GET /curves / GET /measurement-kinds
// shapes. Kept as one small module so the mA/A and wire-format boundary
// lives in one place.

export const MEASUREMENT_KINDS = [
  'baseline',
  'partial-shade',
  'tilt-sweep',
  'dimmer',
  'other',
] as const

export type MeasurementKind = (typeof MEASUREMENT_KINDS)[number]

export interface PanelSetup {
  id: string
  tilt_deg: number
}

export interface CurvePoint {
  v: number
  i: number
}

export interface CurveRecord {
  path: string
  captured_at: string
  label: string
  measurement: MeasurementKind | (string & {})
  panels: PanelSetup[]
  notes: string
  points: CurvePoint[]
  voc: number
  isc: number
  p_mpp: number
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export const MEASUREMENT_KIND_INFO: Record<MeasurementKind, { title: string; description: string }> = {
  baseline: {
    title: 'Baseline',
    description: 'All panels at the same tilt, uniform illumination.',
  },
  'partial-shade': {
    title: 'Partial shade',
    description: 'One panel tilted or shaded relative to the other, to emulate partial shading.',
  },
  'tilt-sweep': {
    title: 'Tilt sweep',
    description: "A series of curves varying one panel's tilt angle.",
  },
  dimmer: {
    title: 'Dimmer',
    description: 'Varying illumination under a controllable lamp dimmer.',
  },
  other: {
    title: 'Other',
    description: "Anything that doesn't fit the kinds above.",
  },
}
