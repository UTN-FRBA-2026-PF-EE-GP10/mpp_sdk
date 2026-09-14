// Bundled "golden" fixtures for client demo (sandbox) mode - see
// lib/sandbox.ts. Two real I-V sweeps captured on this bench (so the shape
// is honest), and one synthetic closed-loop run generated over the bright
// sweep (so the run player has something to play with no captured runs at
// hand).
//
// Every fixture here reads as replayed, not measured - `source:
// 'firmware-replay'` is the existing CURVE_SOURCES value for "played back,
// not a live capture", and it's exactly what these are: static points
// played back through the same UI a real sweep or a firmware replay uses.
// ProvenanceBadge already renders that as "Replayed - not measured"; this
// module doesn't invent a second mechanism for the same fact. RunRecord
// has no equivalent field, so the run fixture's label and notes carry that
// information instead - see DEMO_RUN below.

import type { RunDetail, RunSample } from '@/lib/runs'
import type { CurvePoint, CurveRecord } from '@/types'

// Full lamp brightness. Voc/Isc/P_mpp are the bench's own headline
// numbers for this sweep, not recomputed from the 20 sampled points below
// (which round slightly differently) - so a reader comparing this fixture
// against the original measurement sees the same summary either way.
const BRIGHT_POINTS: CurvePoint[] = [
  { v: 19.337, i: 0.006 },
  { v: 18.658, i: 0.086 },
  { v: 17.929, i: 0.171 },
  { v: 17.179, i: 0.256 },
  { v: 16.386, i: 0.341 },
  { v: 15.544, i: 0.425 },
  { v: 14.599, i: 0.509 },
  { v: 14.49, i: 0.519 },
  { v: 14.362, i: 0.528 },
  { v: 14.212, i: 0.537 },
  { v: 14.074, i: 0.546 },
  { v: 13.887, i: 0.555 },
  { v: 13.463, i: 0.564 },
  { v: 9.011, i: 0.573 },
  { v: 4.822, i: 0.581 },
  { v: 2.521, i: 0.589 },
  { v: 1.048, i: 0.598 },
  { v: 0.212, i: 0.607 },
  { v: 0.118, i: 0.608 },
  { v: 0.116, i: 0.607 },
]

// A lower lamp-dimmer setting, same panel and bench.
const DIM_POINTS: CurvePoint[] = [
  { v: 18.62, i: 0.007 },
  { v: 18.29, i: 0.034 },
  { v: 17.87, i: 0.066 },
  { v: 17.41, i: 0.098 },
  { v: 16.89, i: 0.13 },
  { v: 16.27, i: 0.162 },
  { v: 15.42, i: 0.194 },
  { v: 15.28, i: 0.197 },
  { v: 15.09, i: 0.201 },
  { v: 14.97, i: 0.204 },
  { v: 14.77, i: 0.208 },
  { v: 14.5, i: 0.211 },
  { v: 14.17, i: 0.214 },
  { v: 13.45, i: 0.218 },
  { v: 8.75, i: 0.221 },
  { v: 5.95, i: 0.223 },
  { v: 3.83, i: 0.227 },
  { v: 0.44, i: 0.229 },
  { v: 0.05, i: 0.229 },
  { v: 0.04, i: 0.229 },
]

export const DEMO_CURVE_BRIGHT: CurveRecord = {
  id: 'demo-fixture-psf10-bright',
  path: 'demo-fixture/psf10-bright.json',
  captured_at: '2026-06-01T12:00:00Z',
  label: 'Demo curve - full brightness (bundled sample)',
  measurement: 'baseline',
  panels: [
    { id: 'A', tilt_deg: 90 },
    { id: 'B', tilt_deg: 90 },
  ],
  notes:
    'Bundled with the frontend for demo mode - a real sweep captured on this bench at full lamp brightness, not part of your saved curve library.',
  n_points: BRIGHT_POINTS.length,
  source: 'firmware-replay',
  voc: 19.337,
  isc: 0.607,
  p_mpp: 7.707,
  points: BRIGHT_POINTS,
}

export const DEMO_CURVE_DIM: CurveRecord = {
  id: 'demo-fixture-psf10-dim',
  path: 'demo-fixture/psf10-dim.json',
  captured_at: '2026-06-01T12:10:00Z',
  label: 'Demo curve - dimmed (bundled sample)',
  measurement: 'dimmed',
  panels: [
    { id: 'A', tilt_deg: 90 },
    { id: 'B', tilt_deg: 90 },
  ],
  notes:
    'Bundled with the frontend for demo mode - a real sweep captured on this bench at a lower lamp setting, not part of your saved curve library.',
  n_points: DIM_POINTS.length,
  source: 'firmware-replay',
  voc: 18.62,
  isc: 0.229,
  p_mpp: 3.072,
  points: DIM_POINTS,
}

export const DEMO_CURVES: CurveRecord[] = [DEMO_CURVE_BRIGHT, DEMO_CURVE_DIM]

// --- Synthetic P&O run, generated over DEMO_CURVE_BRIGHT ---------------

/** Samples spent hill-climbing from near Voc down toward the MPP voltage. */
export const PHASE1_SAMPLES = 140
/** Samples spent oscillating in a small cycle once near the MPP. */
export const PHASE2_SAMPLES = 120

const START_V = 19.2 // near Voc (19.337 V) but not sitting exactly on it
const MPP_V = 13.9 // matches DEMO_CURVE_BRIGHT's dense cluster around its real MPP (13.887 V)
const OSCILLATION_VOLTAGES = [13.7, 13.9, 14.1]
const HILL_CLIMB_DECAY = 0.965 // per-step shrink toward MPP_V - a P&O step naturally gets smaller as it nears the peak

// The real control loop runs at 1-2 ms per sample; this fixture is paced
// coarser (10 ms) so a few hundred samples stay a small, readable literal
// instead of a multi-thousand-point file. `t` itself is honest about that
// pacing rather than pretending it's the real rate.
const SAMPLE_PERIOD_S = 0.01

// duty rises as voltage falls - the SEPIC sign convention (see AGENTS.md):
// raising D lowers the panel voltage, so a P&O trajectory that's
// successfully descending toward the MPP is, mechanically, one where duty
// is climbing.
const DUTY_AT_START_V = 0.15
const DUTY_AT_LOW_V = 0.5
const DUTY_LOW_V = 13.7 // the oscillation's lower voltage, where duty peaks

function dutyForVoltage(v: number): number {
  const frac = Math.min(1, Math.max(0, (START_V - v) / (START_V - DUTY_LOW_V)))
  return DUTY_AT_START_V + frac * (DUTY_AT_LOW_V - DUTY_AT_START_V)
}

/** Linear interpolation of current at `v` off a curve's own points
 * (sorted by descending voltage, this bench's sweep direction) - so the
 * synthetic trajectory's current reads off the real measured I-V shape
 * instead of inventing one. Clamps to the curve's own endpoints. */
function interpolateCurrent(points: CurvePoint[], v: number): number {
  if (points.length === 0) return 0
  if (v >= points[0].v) return points[0].i
  const last = points[points.length - 1]
  if (v <= last.v) return last.i
  for (let k = 0; k < points.length - 1; k++) {
    const a = points[k]
    const b = points[k + 1]
    if (v <= a.v && v >= b.v) {
      const frac = a.v === b.v ? 0 : (a.v - v) / (a.v - b.v)
      return a.i + frac * (b.i - a.i)
    }
  }
  return last.i
}

/**
 * Generates a plausible P&O trajectory: a hill-climb from near Voc down to
 * the MPP voltage, then a small three-point oscillation around it, with
 * duty rising as voltage falls (see the SEPIC note above). A pure function
 * of `curvePoints` - which supplies the honest I(V) shape - so it's
 * directly testable rather than a pasted literal.
 */
export function generateDemoRunSamples(curvePoints: CurvePoint[]): RunSample[] {
  const voltages: number[] = []
  for (let k = 0; k < PHASE1_SAMPLES; k++) {
    voltages.push(MPP_V + (START_V - MPP_V) * HILL_CLIMB_DECAY ** k)
  }
  for (let k = 0; k < PHASE2_SAMPLES; k++) {
    voltages.push(OSCILLATION_VOLTAGES[k % OSCILLATION_VOLTAGES.length])
  }

  return voltages.map((v, index) => ({
    t: index * SAMPLE_PERIOD_S,
    v,
    i: interpolateCurrent(curvePoints, v),
    d: dutyForVoltage(v),
  }))
}

export const DEMO_RUN_SAMPLES = generateDemoRunSamples(DEMO_CURVE_BRIGHT.points)

export const DEMO_RUN: RunDetail = {
  id: 'demo-fixture-po-run',
  path: 'demo-fixture/po-run.json',
  captured_at: '2026-06-01T12:05:00Z',
  label: 'Demo run - synthetic P&O trajectory (bundled fixture)',
  algorithm: 'P&O (synthetic demo)',
  n_samples: DEMO_RUN_SAMPLES.length,
  duration_s: DEMO_RUN_SAMPLES[DEMO_RUN_SAMPLES.length - 1].t,
  aborted: false,
  curve_ref: DEMO_CURVE_BRIGHT.path.split('/').pop() ?? null,
  notes:
    'Bundled with the frontend for demo mode - a synthetic trajectory generated by generateDemoRunSamples() over the bundled bright curve, not a captured run. Paced at 10 ms/sample for a small fixture file; the real control loop runs at 1-2 ms.',
  downsampled: false,
  samples: DEMO_RUN_SAMPLES,
}

export const DEMO_RUNS = [DEMO_RUN]
