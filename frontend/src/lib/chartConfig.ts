// Shared chart.js setup for every I(V)/P(V) plot in the app (the live
// capture trace in LiveChart, and the saved-curve plots in CurveChart) -
// one registration call and one set of axis/colour choices, so the two
// charts can never drift apart by copy-paste.

import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

// Chart series colours - VALIDATED, do not change these by eye.
//
// Checked with a CVD/contrast validator against both this theme's light
// surface (#fcfcfb) and dark surface (#0b0f1a - see index.css): lightness
// band, chroma floor, CVD separation, normal-vision separation floor, and
// contrast all pass for this set. The previous orange/red/green set did
// not - the green MPP marker and red power trace were nearly
// indistinguishable under deuteranopia (dE 3.7, need real separation), and
// orange I(V) vs red P(V) fell below the normal-vision floor (dE 10.4,
// floor is 15). Don't "improve" this back toward red/green without
// re-running that check.
export const CURRENT_COLOR = '#D97706' // amber/gold - I(V), keeps the "sun" association the old orange had
export const POWER_COLOR = '#7C3AED' // violet - P(V)
export const MPP_COLOR = '#0891B2' // cyan - the MPP marker, and the run player's moving operating point

// chart.js draws datasets in reverse of their sorted order, so the lowest
// `order` ends up on top. The MPP marker has to win that: left at the
// default it was drawn underneath both traces and effectively invisible
// where it matters most, right on the knee.
export const MPP_DRAW_ORDER = 0
export const CURRENT_DRAW_ORDER = 1
export const POWER_DRAW_ORDER = 2

// RunChart's layers, same reverse-order rule as above: the operating
// point has to win over its own trail, which has to win over the faded
// reference curve sitting furthest back.
export const OPERATING_POINT_DRAW_ORDER = 0
// MPP_th sits under the operating point (which must stay visible as it
// passes over the peak) and over the trail and the reference curve.
export const MPP_TH_DRAW_ORDER = 0.5
export const TRAIL_DRAW_ORDER = 1
export const REFERENCE_DRAW_ORDER = 2

/** Fades a `#rrggbb` colour to a translucent rgba string, for drawing a
 * curve as static background context rather than live data - the run
 * player's faded reference trace behind the algorithm's own trail. */
export function fadeColor(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// The run player's trail is the operating point's own colour (MPP_COLOR)
// at reduced opacity - a history of the same series, not a fourth
// categorical hue competing with the validated three above.
export const TRAIL_COLOR = fadeColor(MPP_COLOR, 0.5)

// Neutrals - recessive, not categorical, so they must never come from the
// three series colours above. These are literal mirrors of this theme's
// light/dark `--muted-foreground`/`--card` tokens (index.css): a <canvas>
// can't resolve a CSS custom property the way an element's own style can
// (chart.js needs a colour string it can hand straight to the 2D context),
// so there is no `var(...)` to read here. If those tokens move, these
// need to move with them.
const NEUTRAL_TEXT_LIGHT = '#71717a'
const NEUTRAL_TEXT_DARK = '#c7ccd6'
const GRID_LIGHT = '#e4e4e7'
const GRID_DARK = 'rgba(255, 255, 255, 0.12)'
const SURFACE_LIGHT = '#fcfcfb'
const SURFACE_DARK = '#11141f'

/** The run player's faded reference curve - a muted neutral, deliberately
 * not one of the three categorical series colours (it isn't a series,
 * it's background context). */
/** Opacity of the reference curve drawn behind a run's trajectory.
 *
 * Grey rather than a series colour, because it is context and not one of
 * the three validated data series. But it has to stay readable as a
 * curve: the whole question a run answers is whether the operating point
 * sits on it, which cannot be judged against a line too faint to trace.
 * Muted enough to sit behind the trajectory, solid enough to follow. */
export const REFERENCE_ALPHA = 0.55

export function referenceColor(dark: boolean, alpha = REFERENCE_ALPHA): string {
  return fadeColor(dark ? NEUTRAL_TEXT_DARK : NEUTRAL_TEXT_LIGHT, alpha)
}

/** The run player's MPP_th marker: the reference curve's own grey at full
 * strength. It belongs to the reference curve, so it takes that curve's
 * neutral rather than a fourth categorical hue; its diamond shape keeps it
 * apart from the cyan circle of the operating point. */
export function mppThColor(dark: boolean): string {
  return dark ? NEUTRAL_TEXT_DARK : NEUTRAL_TEXT_LIGHT
}

/** The ring drawn around a marker that sits on top of another mark (the
 * MPP dot on the P(V) trace, the run player's operating point on its own
 * trail) - the current theme's surface colour, so the ring separates the
 * marker from whatever is under it instead of hardcoding white, which
 * disappears against the dark theme's card. */
export function markerRingColor(dark: boolean): string {
  return dark ? SURFACE_DARK : SURFACE_LIGHT
}

/** Axis/legend options common to every I(V)/P(V) chart. `currentLabel`
 * and `powerLabel` come from the page's unit setting (see lib/units.tsx);
 * the caller scales its data to match, since chart.js is given plain
 * numbers with `parsing: false`. `dark` comes from the page's theme
 * setting (lib/theme.ts) - chart.js defaults axis/tick/legend text to a
 * dark grey that reads as unreadable on the dark theme's card, so this
 * sets those explicitly rather than trusting the default. */
export function ivChartOptions(
  currentLabel: string,
  powerLabel: string,
  dark: boolean,
): ChartOptions<'line'> {
  const textColor = dark ? NEUTRAL_TEXT_DARK : NEUTRAL_TEXT_LIGHT
  const gridColor = dark ? GRID_DARK : GRID_LIGHT
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    scales: {
      x: {
        type: 'linear',
        min: 0,
        title: { display: true, text: 'Voltage [V]', color: textColor },
        ticks: { color: textColor },
        grid: { color: gridColor },
      },
      y: {
        type: 'linear',
        position: 'left',
        min: 0,
        title: { display: true, text: `Current [${currentLabel}]`, color: textColor },
        ticks: { color: textColor },
        grid: { color: gridColor },
      },
      p: {
        type: 'linear',
        position: 'right',
        min: 0,
        title: { display: true, text: `Power [${powerLabel}]`, color: textColor },
        ticks: { color: textColor },
        grid: { drawOnChartArea: false },
      },
    },
    plugins: {
      legend: { display: true, labels: { color: textColor } },
    },
  }
}
