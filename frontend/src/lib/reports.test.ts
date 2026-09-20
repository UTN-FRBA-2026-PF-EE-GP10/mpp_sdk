import { describe, expect, it } from 'vitest'
import {
  groupStepsBySection,
  humanizeKey,
  isEmptyPatch,
  mergeReportPatch,
  progressLabel,
  type ReportStep,
} from '@/lib/reports'

function step(overrides: Partial<ReportStep> = {}): ReportStep {
  return {
    id: 's1',
    section: 'Before energizing',
    title: 'Step',
    instructions: '',
    kind: 'check',
    status: 'todo',
    value: null,
    unit: null,
    notes: '',
    curve_ids: [],
    run_ids: [],
    repeats: 1,
    ...overrides,
  }
}

describe('groupStepsBySection', () => {
  it('preserves first-seen section order and step order within a section', () => {
    const steps = [
      step({ id: 'a', section: 'Before' }),
      step({ id: 'b', section: 'After' }),
      step({ id: 'c', section: 'Before' }),
    ]
    const groups = groupStepsBySection(steps)
    expect(groups.map((g) => g.section)).toEqual(['Before', 'After'])
    expect(groups[0].steps.map((s) => s.id)).toEqual(['a', 'c'])
    expect(groups[1].steps.map((s) => s.id)).toEqual(['b'])
  })

  it('returns an empty list for no steps', () => {
    expect(groupStepsBySection([])).toEqual([])
  })
})

describe('mergeReportPatch', () => {
  it('merges fields key by key', () => {
    const merged = mergeReportPatch({ fields: { a: '1' } }, { fields: { b: '2' } })
    expect(merged.fields).toEqual({ a: '1', b: '2' })
  })

  it('later field values win', () => {
    const merged = mergeReportPatch({ fields: { a: '1' } }, { fields: { a: '2' } })
    expect(merged.fields).toEqual({ a: '2' })
  })

  it('merges steps by id, keeping distinct steps and merging same-id partials', () => {
    const merged = mergeReportPatch(
      { steps: [{ id: 's1', notes: 'first note' }] },
      { steps: [{ id: 's1', status: 'done' }, { id: 's2', value: 3 }] },
    )
    expect(merged.steps).toEqual([
      { id: 's1', notes: 'first note', status: 'done' },
      { id: 's2', value: 3 },
    ])
  })

  it('merges open questions by id, later answer winning', () => {
    const merged = mergeReportPatch(
      { open_questions: [{ id: 'q1', answer: 'first' }] },
      { open_questions: [{ id: 'q1', answer: 'second' }] },
    )
    expect(merged.open_questions).toEqual([{ id: 'q1', answer: 'second' }])
  })

  it('a later title replaces an earlier one', () => {
    const merged = mergeReportPatch({ title: 'old' }, { title: 'new' })
    expect(merged.title).toBe('new')
  })
})

describe('isEmptyPatch', () => {
  it('is true for a patch with nothing set', () => {
    expect(isEmptyPatch({})).toBe(true)
  })

  it('is false once any field is set', () => {
    expect(isEmptyPatch({ title: 'x' })).toBe(false)
    expect(isEmptyPatch({ fields: {} })).toBe(false)
    expect(isEmptyPatch({ steps: [] })).toBe(false)
    expect(isEmptyPatch({ open_questions: [] })).toBe(false)
  })
})

describe('progressLabel', () => {
  it('formats as "done / total"', () => {
    expect(progressLabel({ n_done: 12, n_steps: 20 })).toBe('12 / 20')
    expect(progressLabel({ n_done: 0, n_steps: 0 })).toBe('0 / 0')
  })
})

describe('humanizeKey', () => {
  it('replaces underscores and hyphens with spaces and capitalizes the first letter', () => {
    expect(humanizeKey('light_source')).toBe('Light source')
    expect(humanizeKey('load-resistor')).toBe('Load resistor')
    expect(humanizeKey('panel')).toBe('Panel')
  })
})
