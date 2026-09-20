import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewSessionPane } from './NewSessionPane'
import type { PanelModelRecord } from '@/lib/panels'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'
import type { SessionRecord, SessionTemplate, SessionTemplateSummary } from '@/lib/sessions'

vi.mock('@/lib/api', () => ({
  fetchSessionTemplates: vi.fn(),
  fetchSessionTemplate: vi.fn(),
  createSession: vi.fn(),
  fetchPanelModels: vi.fn(),
  createPanelModel: vi.fn(),
  patchPanelModel: vi.fn(),
}))

import {
  createSession,
  fetchPanelModels,
  fetchSessionTemplate,
  fetchSessionTemplates,
} from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

const LUXEN: PanelModelRecord = {
  id: 'luxen-ln-10p',
  name: 'Luxen LN-10P',
  manufacturer: 'Luxen',
  model: 'LN-10P',
  p_max_w: 10,
  voc: 23.5,
  isc: 0.57,
  vmp: 18.6,
  imp: 0.54,
  notes: '',
}

// No shipped panel model has an unset number any more, so "unknown stays
// unknown" is covered with a synthetic one.
const UNSET: PanelModelRecord = {
  id: 'acme-a-1',
  name: 'Acme A-1',
  manufacturer: '',
  model: '',
  p_max_w: null,
  voc: 21,
  isc: null,
  vmp: null,
  imp: null,
  notes: '',
}

const SINGLE_SUMMARY: SessionTemplateSummary = {
  template_id: 'single-panel-characterization',
  version: 2,
  title: 'Single panel characterization',
  setup: 'single',
  n_steps: 20,
}

const FULL_SUMMARY: SessionTemplateSummary = {
  template_id: 'full-setup-characterization',
  version: 2,
  title: 'Full setup characterization',
  setup: 'full',
  n_steps: 30,
}

// Field shape mirrors mpp_sdk/sessions/templates/single-panel-characterization.json
// after the panel-model picker landed: "panel" plus the four snapshot
// numbers are owned by the picker, not typed by hand.
const SINGLE_TEMPLATE: SessionTemplate = {
  template_id: 'single-panel-characterization',
  version: 2,
  title: 'Single panel characterization',
  setup: 'single',
  field_defs: [
    { key: 'panel', label: 'Panel model', hint: '', default: '' },
    { key: 'panel_model_voc', label: 'Panel model Voc', hint: '', default: '' },
    { key: 'panel_model_isc', label: 'Panel model Isc', hint: '', default: '' },
    { key: 'panel_model_vmp', label: 'Panel model Vmp', hint: '', default: '' },
    { key: 'panel_model_imp', label: 'Panel model Imp', hint: '', default: '' },
    { key: 'operator', label: 'Operator', hint: '', default: '' },
  ],
  steps: [],
  open_questions: [],
}

// Same idea for the full-setup template, with A/B prefixes.
const FULL_TEMPLATE: SessionTemplate = {
  template_id: 'full-setup-characterization',
  version: 2,
  title: 'Full setup characterization',
  setup: 'full',
  field_defs: [
    { key: 'panel_a', label: 'Panel A model', hint: '', default: '' },
    { key: 'panel_a_model_voc', label: 'Panel A model Voc', hint: '', default: '' },
    { key: 'panel_a_model_isc', label: 'Panel A model Isc', hint: '', default: '' },
    { key: 'panel_a_model_vmp', label: 'Panel A model Vmp', hint: '', default: '' },
    { key: 'panel_a_model_imp', label: 'Panel A model Imp', hint: '', default: '' },
    { key: 'panel_b', label: 'Panel B model', hint: '', default: '' },
    { key: 'panel_b_model_voc', label: 'Panel B model Voc', hint: '', default: '' },
    { key: 'panel_b_model_isc', label: 'Panel B model Isc', hint: '', default: '' },
    { key: 'panel_b_model_vmp', label: 'Panel B model Vmp', hint: '', default: '' },
    { key: 'panel_b_model_imp', label: 'Panel B model Imp', hint: '', default: '' },
    { key: 'operator', label: 'Operator', hint: '', default: '' },
  ],
  steps: [],
  open_questions: [],
}

function newSession(overrides: Partial<SessionRecord> = {}): SessionRecord {
  return {
    id: '20260919T160000Z-panel-a',
    title: 'Panel A alone',
    template_id: 'single-panel-characterization',
    template_version: 2,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:00:00+00:00',
    fields: {},
    steps: [],
    open_questions: [],
    ...overrides,
  }
}

describe('NewSessionPane', () => {
  it('preselects the template matching the current setup mode', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY, FULL_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue(/Single panel characterization/)).toBeTruthy(),
    )
  })

  it('shows the non-panel-model field defs, hiding the ones the picker owns', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Operator')).toBeTruthy())
    // The picker-owned fields never render as free-text inputs.
    expect(screen.queryByLabelText('Panel model Voc')).toBeNull()
    expect(screen.queryByLabelText('Panel model Isc')).toBeNull()
  })

  it('shows one panel model picker in Single setup', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Panel model')).toBeTruthy())
    expect(screen.queryByLabelText('Panel A model')).toBeNull()
    expect(screen.queryByLabelText('Panel B model')).toBeNull()
  })

  it('shows two panel model pickers (A and B) in Full setup', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([FULL_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(FULL_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    render(<NewSessionPane setupMode="full" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Panel A model')).toBeTruthy())
    expect(screen.getByLabelText('Panel B model')).toBeTruthy()
    expect(screen.queryByLabelText('Panel model')).toBeNull()
  })

  it('snapshots the picked panel model into fields on create (Single)', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    vi.mocked(createSession).mockResolvedValue(newSession())
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() =>
      expect((screen.getByLabelText('Panel model') as HTMLSelectElement).value).toBe(
        'luxen-ln-10p',
      ),
    )
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'Panel A alone' },
    })
    fireEvent.click(screen.getByText('Create session'))

    await waitFor(() =>
      expect(createSession).toHaveBeenCalledWith(
        expect.objectContaining({
          template_id: 'single-panel-characterization',
          title: 'Panel A alone',
          fields: expect.objectContaining({
            panel: 'Luxen LN-10P, 10 W',
            panel_model_voc: '23.5',
            panel_model_isc: '0.57',
            panel_model_vmp: '18.6',
            panel_model_imp: '0.54',
          }),
        }),
      ),
    )
  })

  it('snapshots an unset number as an empty string, never 0, NaN, null or undefined', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([UNSET])
    vi.mocked(createSession).mockResolvedValue(newSession())
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() =>
      expect((screen.getByLabelText('Panel model') as HTMLSelectElement).value).toBe('acme-a-1'),
    )
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'Unknown label values' },
    })
    fireEvent.click(screen.getByText('Create session'))

    await waitFor(() => expect(createSession).toHaveBeenCalled())
    const sent = vi.mocked(createSession).mock.calls[0][0].fields ?? {}
    expect(sent).toMatchObject({
      panel: 'Acme A-1',
      panel_model_voc: '21',
      panel_model_isc: '',
      panel_model_vmp: '',
      panel_model_imp: '',
    })
    for (const value of Object.values(sent)) {
      expect(value).not.toMatch(/NaN|undefined|null/)
    }
  })

  it('snapshots both panel model pickers into fields on create (Full)', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([FULL_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(FULL_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    vi.mocked(createSession).mockResolvedValue(newSession({ setup: 'full' }))
    render(<NewSessionPane setupMode="full" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Panel A model')).toBeTruthy())
    // Both pickers auto-pick the one available panel model.
    await waitFor(() => {
      expect((screen.getByLabelText('Panel A model') as HTMLSelectElement).value).toBe(
        'luxen-ln-10p',
      )
      expect((screen.getByLabelText('Panel B model') as HTMLSelectElement).value).toBe(
        'luxen-ln-10p',
      )
    })
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'Both panels' },
    })
    fireEvent.click(screen.getByText('Create session'))

    await waitFor(() =>
      expect(createSession).toHaveBeenCalledWith(
        expect.objectContaining({
          fields: expect.objectContaining({
            panel_a: 'Luxen LN-10P, 10 W',
            panel_a_model_voc: '23.5',
            panel_b: 'Luxen LN-10P, 10 W',
            panel_b_model_voc: '23.5',
          }),
        }),
      ),
    )
  })

  it('disables Create session until a title is typed', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Operator')).toBeTruthy())
    const button = screen.getByText('Create session').closest('button') as HTMLButtonElement
    expect(button.disabled).toBe(true)

    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'A title' },
    })
    expect(button.disabled).toBe(false)
  })

  it('surfaces a create error without crashing', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    vi.mocked(createSession).mockRejectedValue(new Error('title must not be empty'))
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Operator')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'A title' },
    })
    fireEvent.click(screen.getByText('Create session'))

    await waitFor(() =>
      expect(screen.getByText(/Failed to create: title must not be empty/)).toBeTruthy(),
    )
  })
})

// Regression coverage for the write path an adversarial review found: the
// sidebar already hides "New session" while an imported session file is
// active (App.tsx's canCreateSession), and App.tsx's content switch skips
// this pane too - but NewSessionPane must refuse on its own as well, the
// same defense-in-depth every other mutating pane applies, so no future
// bug in either of those outer gates can reopen this write path.
describe('NewSessionPane - read-only gating', () => {
  const ACTIVE_IMPORTED_SESSION: ImportedSessionValue = {
    active: true,
    title: 'An imported session',
    setup: 'single',
    session: null,
    curves: [],
    runs: [],
    missing: { curve_ids: [], run_ids: [] },
    enter: () => {},
    close: () => {},
  }

  it('refuses to render the form, and never fetches templates, while an imported session is active', async () => {
    render(
      <ImportedSessionContext.Provider value={ACTIVE_IMPORTED_SESSION}>
        <NewSessionPane setupMode="single" onCreated={vi.fn()} />
      </ImportedSessionContext.Provider>,
    )

    expect(screen.getByText('New session is unavailable')).toBeTruthy()
    expect(screen.getByText(/unavailable while viewing an imported session/)).toBeTruthy()
    expect(screen.queryByText('Create session')).toBeNull()
    // Give a wrongly-unguarded effect a chance to fire, then confirm it didn't.
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchSessionTemplates).not.toHaveBeenCalled()
  })

  it('never calls createSession even if handleCreate were somehow triggered', () => {
    render(
      <ImportedSessionContext.Provider value={ACTIVE_IMPORTED_SESSION}>
        <NewSessionPane setupMode="single" onCreated={vi.fn()} />
      </ImportedSessionContext.Provider>,
    )
    // No Create session button exists to click in this state at all - the
    // form isn't rendered (see the test above). This only pins that
    // createSession stays uncalled through render.
    expect(createSession).not.toHaveBeenCalled()
  })
})
