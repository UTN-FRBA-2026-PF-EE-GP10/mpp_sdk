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

// Matches GET /api/curves's entry shape exactly (curve_tracer_server.py's
// get_curves). The library-list endpoint reports a point *count*, not
// the points themselves, and does not echo back notes - both live only
// in the on-disk record and the save-curve request body (see
// SaveCurveInput).
export interface CurveRecord {
  path: string
  captured_at: string
  label: string
  measurement: MeasurementKind | (string & {})
  panels: PanelSetup[]
  n_points: number
  voc: number
  isc: number
  p_mpp: number
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'demo'

/** True for any status where a sweep can actually be triggered or drawn:
 * 'connected' (real Pi) and 'demo' (simulated source) both qualify. Kept
 * in one place, so a future status only needs updating here, not at
 * every call site that cares about "is this live enough to use". */
export function isLiveConnection(status: ConnectionStatus): boolean {
  return status === 'connected' || status === 'demo'
}

const MEASUREMENT_KIND_INFO: Record<MeasurementKind, { title: string; description: string }> = {
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

/**
 * Measurement kinds are operator-defined free text on the backend (see
 * `mpp_sdk/curves/record.py`'s `MEASUREMENT_KINDS` docstring - "not an
 * enum"). So a kind from `GET /api/measurement-kinds`, or in a saved
 * curve, may not be one of the five seeded above. Falls back to the
 * kind's own name instead of throwing or hiding the card.
 */
export function getMeasurementKindInfo(kind: string): { title: string; description: string } {
  return (
    MEASUREMENT_KIND_INFO[kind as MeasurementKind] ?? {
      title: kind,
      description: 'Custom measurement kind.',
    }
  )
}
