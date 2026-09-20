// Builds a downloadable file from a session already in hand (GET
// /api/sessions/{id}, plus the curves/runs it links) - no server round
// trip, same reasoning as curveExport.ts. Two different downloads live
// here: a readable Markdown/JSON summary of the session record alone
// (sessionToMarkdown/sessionToJson - useful pasted into a lab notebook or
// a PR description), and a full session *file* bundle (sessionExportFile)
// that also carries every curve/run the session's steps link, for someone
// else to open read-only (see lib/sessionFile.ts).

import { sanitizeFilenamePart } from '@/lib/curveExport'
import { buildSessionFile, downloadSessionFile, type SessionFile, type SessionMissing } from '@/lib/sessionFile'
import { curveMetrics, curveStepStats, runMetrics, runStepStats, type Stats } from '@/lib/sessionStats'
import { findCurveForRun } from '@/lib/runPlayback'
import { groupStepsBySection, humanizeKey, type SessionRecord, type SessionStep } from '@/lib/sessions'
import type { RunDetail, RunSummary } from '@/lib/runs'
import type { CurveRecord } from '@/types'

export function sessionFilenameBase(session: Pick<SessionRecord, 'title' | 'created_at'>): string {
  const stamp = session.created_at.replace(/[:.]/g, '-')
  return `${sanitizeFilenamePart(session.title)}_${stamp}`
}

export function sessionToJson(session: SessionRecord): string {
  return JSON.stringify(session, null, 2)
}

function fmt(n: number): string {
  return Number.isFinite(n) ? n.toFixed(3) : String(n)
}

function statsLine(label: string, unit: string, stats: Stats | null): string {
  if (stats === null) return `- ${label}: -`
  if (stats.n === 1) return `- ${label}: ${fmt(stats.median)} ${unit} (n = 1)`
  return (
    `- ${label}: median ${fmt(stats.median)} ${unit}, mean ${fmt(stats.mean)} ${unit}, ` +
    `std ${stats.std !== null ? fmt(stats.std) : '-'} ${unit}, ` +
    `min ${fmt(stats.min)} ${unit}, max ${fmt(stats.max)} ${unit} (n = ${stats.n})`
  )
}

function curveLine(id: string, curves: CurveRecord[]): string {
  const record = curves.find((c) => c.id === id)
  if (!record) return `  - ${id}: missing (deleted)`
  const m = curveMetrics(record)
  if (!m) return `  - ${record.label || id}: no points recorded`
  return (
    `  - ${record.label || id}: Voc ${fmt(m.voc)} V, Isc ${fmt(m.isc)} A, ` +
    `Vmp ${fmt(m.vmp)} V, Imp ${fmt(m.imp)} A, P_mpp ${fmt(m.pMpp)} W`
  )
}

function runLine(id: string, runs: RunSummary[], curves: CurveRecord[], detail: RunDetail | undefined): string {
  const summary = runs.find((r) => r.id === id)
  if (!summary) return `  - ${id}: missing (deleted)`
  const base = `${summary.label || id} (${summary.algorithm}, ${summary.duration_s.toFixed(1)} s)`
  if (!detail) return `  - ${base}`
  const reference = findCurveForRun(curves, detail.curve_ref)
  const mppTh = reference ? curveMetrics(reference) : null
  const m = runMetrics(detail.samples, mppTh ? { v: mppTh.vmp, i: mppTh.imp } : null)
  if (!m) return `  - ${base}`
  const ratio = m.pOverMppTh !== null ? `${(m.pOverMppTh * 100).toFixed(1)} %` : '-'
  const converge = m.timeToConvergeS !== null ? `${m.timeToConvergeS.toFixed(2)} s` : 'never'
  return `  - ${base}: held ${fmt(m.heldPower)} W, P/MPP_th ${ratio}, converged in ${converge}`
}

function stepMarkdown(
  step: SessionStep,
  curves: CurveRecord[],
  runs: RunSummary[],
  runDetails: Record<string, RunDetail>,
): string[] {
  const lines: string[] = []
  lines.push(`#### ${step.title} (${step.status})`)
  if (step.instructions) lines.push(step.instructions)
  if (step.kind === 'number' || step.kind === 'text') {
    lines.push(`Value: ${step.value ?? '-'}${step.unit ? ` ${step.unit}` : ''}`)
  }
  if (step.kind === 'curve' && step.curve_ids.length > 0) {
    lines.push(`Linked curves (${step.curve_ids.length} / ${step.repeats} repeats):`)
    for (const id of step.curve_ids) lines.push(curveLine(id, curves))
    const found = step.curve_ids.map((id) => curves.find((c) => c.id === id)).filter((c): c is CurveRecord => !!c)
    const stats = curveStepStats(found)
    lines.push('Statistics:')
    lines.push(statsLine('Voc', 'V', stats.voc))
    lines.push(statsLine('Isc', 'A', stats.isc))
    lines.push(statsLine('Vmp', 'V', stats.vmp))
    lines.push(statsLine('Imp', 'A', stats.imp))
    lines.push(statsLine('P_mpp', 'W', stats.pMpp))
  }
  if (step.kind === 'run' && step.run_ids.length > 0) {
    lines.push(`Linked runs (${step.run_ids.length} / ${step.repeats} repeats):`)
    for (const id of step.run_ids) lines.push(runLine(id, runs, curves, runDetails[id]))
    const metrics = step.run_ids
      .map((id) => {
        const detail = runDetails[id]
        if (!detail) return null
        const reference = findCurveForRun(curves, detail.curve_ref)
        const mppTh = reference ? curveMetrics(reference) : null
        return runMetrics(detail.samples, mppTh ? { v: mppTh.vmp, i: mppTh.imp } : null)
      })
      .filter((m): m is NonNullable<typeof m> => m !== null)
    const stats = runStepStats(metrics)
    lines.push('Statistics:')
    lines.push(statsLine('Held power', 'W', stats.heldPower))
    lines.push(
      stats.pOverMppTh === null
        ? '- P / MPP_th: -'
        : statsLine('P / MPP_th', '', stats.pOverMppTh),
    )
    lines.push(statsLine('Time to converge', 's', stats.timeToConvergeS))
  }
  if (step.notes) lines.push(`Notes: ${step.notes}`)
  return lines
}

/**
 * A readable Markdown summary of the session: every step, its value/notes,
 * linked items' key numbers, and the per-step repeat statistics (same
 * numbers SessionView shows inline).
 */
export function sessionToMarkdown(
  session: SessionRecord,
  curves: CurveRecord[],
  runs: RunSummary[],
  runDetails: Record<string, RunDetail> = {},
): string {
  const lines: string[] = []
  lines.push(`# ${session.title}`)
  lines.push('')
  lines.push(`Template: ${session.template_id} (setup: ${session.setup})`)
  lines.push(`Created: ${session.created_at}`)
  lines.push(`Updated: ${session.updated_at}`)
  lines.push(`Progress: ${session.steps.filter((s) => s.status === 'done').length} / ${session.steps.length}`)
  lines.push('')
  lines.push('## Setup')
  lines.push('')
  for (const [key, value] of Object.entries(session.fields)) {
    lines.push(`- ${humanizeKey(key)}: ${value || '-'}`)
  }
  lines.push('')

  for (const group of groupStepsBySection(session.steps)) {
    lines.push(`## ${group.section}`)
    lines.push('')
    for (const step of group.steps) {
      lines.push(...stepMarkdown(step, curves, runs, runDetails))
      lines.push('')
    }
  }

  if (session.open_questions.length > 0) {
    lines.push('## Open questions')
    lines.push('')
    for (const q of session.open_questions) {
      lines.push(`- ${q.text}`)
      lines.push(`  Answer: ${q.answer || '-'}`)
    }
    lines.push('')
  }

  return lines.join('\n')
}

function triggerDownload(content: string, mime: string, filename: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function downloadSessionJson(session: SessionRecord): void {
  triggerDownload(sessionToJson(session), 'application/json', `${sessionFilenameBase(session)}.json`)
}

export function downloadSessionMarkdown(
  session: SessionRecord,
  curves: CurveRecord[],
  runs: RunSummary[],
  runDetails: Record<string, RunDetail> = {},
): void {
  triggerDownload(
    sessionToMarkdown(session, curves, runs, runDetails),
    'text/markdown',
    `${sessionFilenameBase(session)}.md`,
  )
}

/**
 * Builds a session *file* (lib/sessionFile.ts) from a session already in
 * hand: the session record itself, plus every curve and run its steps
 * link, deduplicated by id. `curves` is the full, already-loaded curve
 * library (always available in full - see SessionView's own doc comment),
 * so a linked id resolves straight from it; `runDetails` is keyed by run
 * id and expected to already carry full samples for every linked run
 * SessionPane could fetch (see its own effect) - a linked id absent from
 * both `curves` and `runDetails` is either deleted from the library or
 * still loading, and either way is named in the file's `missing` rather
 * than silently dropped.
 */
export function sessionExportFile(
  session: SessionRecord,
  curves: CurveRecord[],
  runDetails: Record<string, RunDetail>,
): SessionFile {
  const curveIds = new Set<string>()
  const runIds = new Set<string>()
  for (const step of session.steps) {
    for (const id of step.curve_ids) curveIds.add(id)
    for (const id of step.run_ids) runIds.add(id)
  }

  const foundCurves: CurveRecord[] = []
  const missingCurveIds: string[] = []
  for (const id of curveIds) {
    const record = curves.find((c) => c.id === id)
    if (record) foundCurves.push(record)
    else missingCurveIds.push(id)
  }

  const foundRuns: RunDetail[] = []
  const missingRunIds: string[] = []
  for (const id of runIds) {
    const detail = runDetails[id]
    if (detail) foundRuns.push(detail)
    else missingRunIds.push(id)
  }

  const missing: SessionMissing = { curve_ids: missingCurveIds, run_ids: missingRunIds }
  return buildSessionFile({
    title: session.title,
    setup: session.setup,
    curves: foundCurves,
    runs: foundRuns,
    session,
    missing,
  })
}

export function downloadSessionExportFile(
  session: SessionRecord,
  curves: CurveRecord[],
  runDetails: Record<string, RunDetail>,
): void {
  downloadSessionFile(sessionExportFile(session, curves, runDetails))
}
