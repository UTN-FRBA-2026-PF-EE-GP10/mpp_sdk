import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PanelModelPicker } from './PanelModelPicker'
import type { PanelModelRecord } from '@/lib/panels'
import { ImportedSessionContext, type ImportedSessionValue } from '@/lib/sessionFile'

vi.mock('@/lib/api', () => ({
  fetchPanelModels: vi.fn(),
  createPanelModel: vi.fn(),
  patchPanelModel: vi.fn(),
}))

import { createPanelModel, fetchPanelModels, patchPanelModel } from '@/lib/api'

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

const HISSUMA: PanelModelRecord = {
  id: 'hissuma-psf10mono',
  name: 'Hissuma PSF10MONO',
  manufacturer: 'Hissuma',
  model: 'PSF10MONO',
  p_max_w: 10,
  voc: 17,
  isc: 0.79,
  vmp: 14,
  imp: 0.72,
  notes: '',
}

describe('PanelModelPicker', () => {
  it('preselects the first panel model (alphabetically first from the API) and reports it', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([HISSUMA, LUXEN])
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(HISSUMA))
  })

  it('reports the newly picked panel model on a manual selection', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([HISSUMA, LUXEN])
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(HISSUMA))
    fireEvent.change(screen.getByLabelText('Panel model'), { target: { value: 'luxen-ln-10p' } })

    await waitFor(() => expect(onPick).toHaveBeenLastCalledWith(LUXEN))
  })

  it('creates a new panel model from the inline add form and picks it', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    const created: PanelModelRecord = {
      id: 'acme-a-1',
      name: 'Acme A-1',
      manufacturer: '',
      model: '',
      p_max_w: 20,
      voc: null,
      isc: null,
      vmp: null,
      imp: null,
      notes: '',
    }
    vi.mocked(createPanelModel).mockResolvedValue(created)
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(LUXEN))
    fireEvent.click(screen.getByText('Add panel model'))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme A-1' } })
    fireEvent.change(screen.getByLabelText('Pmax (W)'), { target: { value: '20' } })
    fireEvent.click(screen.getByText('Save panel model'))

    await waitFor(() =>
      expect(createPanelModel).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Acme A-1', p_max_w: 20 }),
      ),
    )
    await waitFor(() => expect(onPick).toHaveBeenLastCalledWith(created))
  })

  it('sends an unset numeric field as null, not an empty string or zero', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    vi.mocked(createPanelModel).mockResolvedValue(LUXEN)
    render(<PanelModelPicker label="Panel model" onPick={vi.fn()} />)

    await waitFor(() => expect(fetchPanelModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Add panel model'))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Bare panel' } })
    fireEvent.click(screen.getByText('Save panel model'))

    await waitFor(() =>
      expect(createPanelModel).toHaveBeenCalledWith(expect.objectContaining({ voc: null })),
    )
  })

  it('edits the selected panel model via PATCH, prefilled with its current values', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    const edited: PanelModelRecord = { ...LUXEN, voc: 23.9 }
    vi.mocked(patchPanelModel).mockResolvedValue(edited)
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(LUXEN))
    fireEvent.click(screen.getByText('Edit'))
    expect(screen.getByDisplayValue('23.5')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Voc (V)'), { target: { value: '23.9' } })
    fireEvent.click(screen.getByText('Save panel model'))

    await waitFor(() =>
      expect(patchPanelModel).toHaveBeenCalledWith(
        'luxen-ln-10p',
        expect.objectContaining({ voc: 23.9 }),
      ),
    )
    await waitFor(() => expect(onPick).toHaveBeenLastCalledWith(edited))
  })

  it('lists a panel model with an unset wattage by name alone, never "null W"', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([UNSET])
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(UNSET))
    const select = screen.getByLabelText('Panel model') as HTMLSelectElement
    expect(select.options[0].textContent).toBe('Acme A-1')
  })

  it('edits a panel model with unset numbers: blank boxes, and saving untouched keeps them unset', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([UNSET])
    vi.mocked(patchPanelModel).mockResolvedValue(UNSET)
    const onPick = vi.fn()
    render(<PanelModelPicker label="Panel model" onPick={onPick} />)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(UNSET))
    fireEvent.click(screen.getByText('Edit'))
    for (const label of ['Pmax (W)', 'Isc (A)', 'Vmp (V)', 'Imp (A)']) {
      expect((screen.getByLabelText(label) as HTMLInputElement).value).toBe('')
    }
    fireEvent.click(screen.getByText('Save panel model'))

    await waitFor(() =>
      expect(patchPanelModel).toHaveBeenCalledWith(
        'acme-a-1',
        expect.objectContaining({ p_max_w: null, isc: null, vmp: null, imp: null, voc: 21 }),
      ),
    )
  })

  it('surfaces a save error without crashing', async () => {
    vi.mocked(fetchPanelModels).mockResolvedValue([LUXEN])
    vi.mocked(createPanelModel).mockRejectedValue(new Error('name must not be empty'))
    render(<PanelModelPicker label="Panel model" onPick={vi.fn()} />)

    await waitFor(() => expect(fetchPanelModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Add panel model'))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'x' } })
    fireEvent.click(screen.getByText('Save panel model'))

    await waitFor(() =>
      expect(screen.getByText(/Failed to save: name must not be empty/)).toBeTruthy(),
    )
  })
})

// Same defense-in-depth story as NewSessionPane's own "read-only gating"
// tests: this component's only caller (NewSessionPane) already refuses to
// mount it at all while an imported session is active, but PanelModelPicker
// must refuse on its own too, so a future bug in that outer gate can't
// reopen this fetch/write path.
describe('PanelModelPicker - read-only gating', () => {
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

  function renderReadOnly(onPick = vi.fn()) {
    return render(
      <ImportedSessionContext.Provider value={ACTIVE_IMPORTED_SESSION}>
        <PanelModelPicker label="Panel model" onPick={onPick} />
      </ImportedSessionContext.Provider>,
    )
  }

  it('never fetches the panel model list while viewing an imported session', async () => {
    renderReadOnly()
    // Give a wrongly-unguarded effect a chance to fire, then confirm it didn't.
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchPanelModels).not.toHaveBeenCalled()
  })

  it('disables the picker, Edit and Add panel model controls', () => {
    renderReadOnly()
    expect((screen.getByLabelText('Panel model') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByText('Edit').closest('button') as HTMLButtonElement).disabled).toBe(true)
    expect(
      (screen.getByText('Add panel model').closest('button') as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('never opens the inline add/edit form even if a click somehow reached it', () => {
    renderReadOnly()
    fireEvent.click(screen.getByText('Add panel model'))
    expect(screen.queryByText('New panel model')).toBeNull()
    expect(screen.queryByLabelText('Name')).toBeNull()
  })
})
