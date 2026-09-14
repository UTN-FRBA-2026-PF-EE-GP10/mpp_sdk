// Builds a downloadable file from a CurveRecord already in hand (fetched
// via GET /api/curves) - no server round trip, so no download endpoint
// and no file-path input to validate against traversal.

import type { CurveRecord } from '@/types'

/** Collapses anything that isn't a-z/0-9 into a single hyphen and trims
 * the ends, so an operator's free-text label makes a safe filename
 * fragment on every OS a browser might save to. */
export function sanitizeFilenamePart(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'curve'
}

/** `<slug-of-label>_<capture-timestamp>`, with the timestamp's colons and
 * dots stripped so the result is also a valid filename on Windows. */
export function curveFilenameBase(record: Pick<CurveRecord, 'label' | 'captured_at'>): string {
  const stamp = record.captured_at.replace(/[:.]/g, '-')
  return `${sanitizeFilenamePart(record.label)}_${stamp}`
}

/** One row per point, header included. States units explicitly: unlike
 * GET /api/data, GET /api/curves (and so this export) reports current in
 * amps, not milliamps - see api.ts. */
export function curveToCsv(record: Pick<CurveRecord, 'points'>): string {
  const header = 'voltage (V),current (A)'
  const rows = record.points.map((p) => `${p.v},${p.i}`)
  return [header, ...rows].join('\n')
}

/** The record exactly as GET /api/curves served it, so the download
 * round-trips. */
export function curveToJson(record: CurveRecord): string {
  return JSON.stringify(record, null, 2)
}

/** Triggers a browser download of `record` with no server involvement:
 * builds the file from data already fetched, offers it via a Blob object
 * URL, and revokes that URL once the click has been dispatched. */
export function downloadCurve(record: CurveRecord, format: 'json' | 'csv'): void {
  const base = curveFilenameBase(record)
  const [content, mime, extension] =
    format === 'json'
      ? [curveToJson(record), 'application/json', 'json']
      : [curveToCsv(record), 'text/csv', 'csv']
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = `${base}.${extension}`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
