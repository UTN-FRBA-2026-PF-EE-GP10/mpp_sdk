import { describe, expect, it } from 'vitest'
import { groupRunsByDate, type RunSummary } from './runs'

function run(captured_at: string, label = 'run'): RunSummary {
  return {
    id: `${captured_at}-${label}`,
    path: `/data/runs/${captured_at}-${label}.json`,
    captured_at,
    label,
    algorithm: 'P&O',
    n_samples: 100,
    duration_s: 12.5,
    aborted: false,
    curve_ref: null,
    notes: '',
  }
}

describe('groupRunsByDate', () => {
  it('returns an empty list for no runs', () => {
    expect(groupRunsByDate([])).toEqual([])
  })

  it('groups runs captured on the same day together', () => {
    const groups = groupRunsByDate([
      run('2026-09-12T08:00:00Z', 'a'),
      run('2026-09-12T09:30:00Z', 'b'),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].date).toBe('2026-09-12')
    expect(groups[0].runs.map((r) => r.label)).toEqual(['b', 'a'])
  })

  it('orders dates newest first', () => {
    const groups = groupRunsByDate([
      run('2026-09-10T00:00:00Z', 'oldest'),
      run('2026-09-13T00:00:00Z', 'newest'),
      run('2026-09-12T00:00:00Z', 'middle'),
    ])
    expect(groups.map((g) => g.date)).toEqual(['2026-09-13', '2026-09-12', '2026-09-10'])
  })

  it('orders runs within a date newest first', () => {
    const groups = groupRunsByDate([
      run('2026-09-12T08:00:00Z', 'early'),
      run('2026-09-12T20:00:00Z', 'late'),
      run('2026-09-12T14:00:00Z', 'mid'),
    ])
    expect(groups[0].runs.map((r) => r.label)).toEqual(['late', 'mid', 'early'])
  })
})
