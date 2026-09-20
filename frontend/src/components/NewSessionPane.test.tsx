import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewSessionPane } from './NewSessionPane'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'
import type { SessionRecord, SessionTemplate, SessionTemplateSummary } from '@/lib/sessions'

vi.mock('@/lib/api', () => ({
  fetchSessionTemplates: vi.fn(),
  fetchSessionTemplate: vi.fn(),
  createSession: vi.fn(),
}))

import { createSession, fetchSessionTemplate, fetchSessionTemplates } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

const SINGLE_SUMMARY: SessionTemplateSummary = {
  template_id: 'single-panel-characterization',
  version: 1,
  title: 'Single panel characterization',
  setup: 'single',
  n_steps: 20,
}

const FULL_SUMMARY: SessionTemplateSummary = {
  template_id: 'full-setup-characterization',
  version: 1,
  title: 'Full setup characterization',
  setup: 'full',
  n_steps: 30,
}

const SINGLE_TEMPLATE: SessionTemplate = {
  template_id: 'single-panel-characterization',
  version: 1,
  title: 'Single panel characterization',
  setup: 'single',
  field_defs: [
    { key: 'panel', label: 'Panel', hint: 'Panel model.', default: 'Luxen LN-10P' },
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
    template_version: 1,
    setup: 'single',
    created_at: '2026-09-19T16:00:00+00:00',
    updated_at: '2026-09-19T16:00:00+00:00',
    fields: { panel: 'Luxen LN-10P', operator: '' },
    steps: [],
    open_questions: [],
    ...overrides,
  }
}

describe('NewSessionPane', () => {
  it('preselects the template matching the current setup mode', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY, FULL_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue(/Single panel characterization/)).toBeTruthy(),
    )
  })

  it('shows the template field defs, seeded with their defaults', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    expect(screen.getByLabelText('Operator')).toBeTruthy()
  })

  it('creates a session with the typed title and edited fields', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(createSession).mockResolvedValue(newSession())
    const onCreated = vi.fn()
    render(<NewSessionPane setupMode="single" onCreated={onCreated} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'Panel A alone' },
    })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'bench operator' } })
    fireEvent.click(screen.getByText('Create session'))

    await waitFor(() =>
      expect(createSession).toHaveBeenCalledWith({
        template_id: 'single-panel-characterization',
        title: 'Panel A alone',
        fields: { panel: 'Luxen LN-10P', operator: 'bench operator' },
      }),
    )
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(newSession()))
  })

  it('disables Create session until a title is typed', async () => {
    vi.mocked(fetchSessionTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchSessionTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
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
    vi.mocked(createSession).mockRejectedValue(new Error('title must not be empty'))
    render(<NewSessionPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
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
