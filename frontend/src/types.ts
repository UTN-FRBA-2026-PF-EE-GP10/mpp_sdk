// Mirrors mpp_sdk/curves/record.py's on-disk schema and
// scripts/curve_tracer_server.py's GET /curves / GET /measurement-kinds
// shapes. Kept as one small module so the mA/A and wire-format boundary
// lives in one place.

export const MEASUREMENT_KINDS = ['baseline', 'tilted', 'dimmed', 'other'] as const

export type MeasurementKind = (typeof MEASUREMENT_KINDS)[number]

export interface PanelSetup {
  id: string
  tilt_deg: number
}

// Bench tilt convention: light travels from 180 degrees toward 0 degrees.
// 90 degrees is vertical, facing the light squarely - the untilted
// reference, not zero. Panel A is fixed at 90 and never adjusted. Panel B
// sits on a mount with five fixed detents; lower angles turn it further
// right, away from the light, so it receives less illumination.
export const PANEL_A_TILT_DEG = 90
export const PANEL_B_TILT_OPTIONS_DEG = [90, 70, 60, 45, 30] as const

export interface CurvePoint {
  v: number
  i: number
}

// Matches GET /api/curves's entry shape exactly (curve_tracer_server.py's
// get_curves). `points` is in amps here, same as voc/isc/p_mpp below and
// the on-disk record (mpp_sdk/curves/record.py's CurveRecord.to_dict) -
// GET /api/data's milliamps convention is that route's own, for the
// live-capture UI, and does not apply here. See api.ts for where that
// boundary is actually crossed.
export interface CurveRecord {
  /** Filename stem - stable, URL-safe identifier for DELETE /api/curves/{id}.
   * Distinct from `path`, which is a full filesystem path and never sent
   * back to the server (see curve_tracer_server.py's `_curve_path`). */
  id: string
  path: string
  captured_at: string
  label: string
  measurement: MeasurementKind | (string & {})
  panels: PanelSetup[]
  notes: string
  n_points: number
  /** Where the points came from - see CURVE_SOURCES in
   * mpp_sdk/curves/record.py. Anything but "hardware" means the curve was
   * not measured off a panel and must not be read as data. */
  source: 'hardware' | 'firmware-replay' | 'simulated' | 'unknown' | (string & {})
  /** The bench session this curve was captured in, or null - stamped by
   * the server from the client's "active session" at save time (see
   * lib/activeSession.ts), never editable afterward. A stamp is not
   * ownership: this only drives the Curves list's session filter and the
   * session-file export's "stamped but unlinked" inclusion (see
   * lib/sessionExport.ts) - deleting that session leaves the stamp
   * dangling rather than clearing it. Optional because a session file
   * exported before stamping existed, and the bundled demo curves, have
   * none - read absent as null. */
  session_id?: string | null
  voc: number
  isc: number
  p_mpp: number
  points: CurvePoint[]
}

/** What Remeasure hands off to the Measure section - the old curve's
 * kind, label, notes, and panel setup, so a replacement capture starts
 * prefilled instead of blank. See CurveDashboardPane's `onRemeasure` and
 * App.tsx's `startRemeasure`. */
export interface MeasurePrefill {
  kind: string
  label: string
  notes: string
  panels: PanelSetup[]
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
    description: 'Both panels at 90 degrees, facing the light squarely.',
  },
  tilted: {
    title: 'Tilted',
    description:
      'Panel B off 90 degrees (one capture or a full sweep across its angles), shading it relative to panel A.',
  },
  dimmed: {
    title: 'Dimmed',
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
 * curve, may not be one of the four seeded above. Falls back to the
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
