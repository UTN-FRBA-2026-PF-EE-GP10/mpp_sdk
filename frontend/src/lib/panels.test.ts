import { describe, expect, it } from 'vitest'
import {
  composePanelModelLabel,
  formatSnapshotNumber,
  isPanelModelSnapshotField,
  panelModelFieldKeys,
  panelModelSnapshotFields,
  type PanelModelRecord,
} from '@/lib/panels'

function panel(overrides: Partial<PanelModelRecord> = {}): PanelModelRecord {
  return {
    id: 'luxen-ln-10p',
    name: 'Luxen LN-10P',
    manufacturer: 'Luxen',
    model: 'LN-10P',
    p_max_w: 10,
    voc: 23.5,
    isc: 0.57,
    vmp: null,
    imp: null,
    notes: '',
    ...overrides,
  }
}

describe('composePanelModelLabel', () => {
  it('appends the wattage when p_max_w is known', () => {
    expect(composePanelModelLabel(panel())).toBe('Luxen LN-10P, 10 W')
  })

  it('omits the wattage rather than showing "null W"', () => {
    expect(composePanelModelLabel(panel({ p_max_w: null }))).toBe('Luxen LN-10P')
  })
})

describe('formatSnapshotNumber', () => {
  it('formats a known number as a plain string', () => {
    expect(formatSnapshotNumber(23.5)).toBe('23.5')
  })

  it('formats an unset number as an empty string, not "null"', () => {
    expect(formatSnapshotNumber(null)).toBe('')
  })
})

describe('panelModelFieldKeys', () => {
  it('returns the label key plus the four numeric keys', () => {
    expect(panelModelFieldKeys('panel', 'panel_model')).toEqual([
      'panel',
      'panel_model_voc',
      'panel_model_isc',
      'panel_model_vmp',
      'panel_model_imp',
    ])
  })

  it('matches the full-setup prefix convention for panel A/B', () => {
    expect(panelModelFieldKeys('panel_a', 'panel_a_model')).toEqual([
      'panel_a',
      'panel_a_model_voc',
      'panel_a_model_isc',
      'panel_a_model_vmp',
      'panel_a_model_imp',
    ])
  })
})

describe('panelModelSnapshotFields', () => {
  it('snapshots a picked panel model into the exact keys panelModelFieldKeys names', () => {
    const p = panel({ vmp: 19.5, imp: 0.51 })
    const fields = panelModelSnapshotFields('panel', 'panel_model', p)
    expect(fields).toEqual({
      panel: 'Luxen LN-10P, 10 W',
      panel_model_voc: '23.5',
      panel_model_isc: '0.57',
      panel_model_vmp: '19.5',
      panel_model_imp: '0.51',
    })
  })

  it('leaves an unset Vmp/Imp as empty strings, not fabricated zeros', () => {
    const fields = panelModelSnapshotFields('panel', 'panel_model', panel())
    expect(fields.panel_model_vmp).toBe('')
    expect(fields.panel_model_imp).toBe('')
  })
})

describe('isPanelModelSnapshotField', () => {
  it('recognizes the single-setup snapshot keys', () => {
    for (const key of ['panel_model_voc', 'panel_model_isc', 'panel_model_vmp', 'panel_model_imp']) {
      expect(isPanelModelSnapshotField(key)).toBe(true)
    }
  })

  it('recognizes the full-setup A/B snapshot keys', () => {
    expect(isPanelModelSnapshotField('panel_a_model_voc')).toBe(true)
    expect(isPanelModelSnapshotField('panel_b_model_imp')).toBe(true)
  })

  it('does not flag the free-text label field', () => {
    expect(isPanelModelSnapshotField('panel')).toBe(false)
    expect(isPanelModelSnapshotField('panel_a')).toBe(false)
  })

  it('does not flag an unrelated field', () => {
    expect(isPanelModelSnapshotField('operator')).toBe(false)
    expect(isPanelModelSnapshotField('light_source')).toBe(false)
  })
})
