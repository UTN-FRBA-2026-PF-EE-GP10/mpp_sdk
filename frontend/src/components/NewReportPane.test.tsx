import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewReportPane } from './NewReportPane'
import type { ReportRecord, ReportTemplate, ReportTemplateSummary } from '@/lib/reports'

vi.mock('@/lib/api', () => ({
  fetchReportTemplates: vi.fn(),
  fetchReportTemplate: vi.fn(),
  createReport: vi.fn(),
}))

import { createReport, fetchReportTemplate, fetchReportTemplates } from '@/lib/api'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

const SINGLE_SUMMARY: ReportTemplateSummary = {
  template_id: 'single-panel-characterization',
  version: 1,
  title: 'Single panel characterization',
  setup: 'single',
  n_steps: 20,
}

const FULL_SUMMARY: ReportTemplateSummary = {
  template_id: 'full-setup-characterization',
  version: 1,
  title: 'Full setup characterization',
  setup: 'full',
  n_steps: 30,
}

const SINGLE_TEMPLATE: ReportTemplate = {
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

function newReport(overrides: Partial<ReportRecord> = {}): ReportRecord {
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

describe('NewReportPane', () => {
  it('preselects the template matching the current setup mode', async () => {
    vi.mocked(fetchReportTemplates).mockResolvedValue([SINGLE_SUMMARY, FULL_SUMMARY])
    vi.mocked(fetchReportTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewReportPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue(/Single panel characterization/)).toBeTruthy(),
    )
  })

  it('shows the template field defs, seeded with their defaults', async () => {
    vi.mocked(fetchReportTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchReportTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewReportPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    expect(screen.getByLabelText('Operator')).toBeTruthy()
  })

  it('creates a report with the typed title and edited fields', async () => {
    vi.mocked(fetchReportTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchReportTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(createReport).mockResolvedValue(newReport())
    const onCreated = vi.fn()
    render(<NewReportPane setupMode="single" onCreated={onCreated} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'Panel A alone' },
    })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'bench operator' } })
    fireEvent.click(screen.getByText('Create report'))

    await waitFor(() =>
      expect(createReport).toHaveBeenCalledWith({
        template_id: 'single-panel-characterization',
        title: 'Panel A alone',
        fields: { panel: 'Luxen LN-10P', operator: 'bench operator' },
      }),
    )
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(newReport()))
  })

  it('disables Create report until a title is typed', async () => {
    vi.mocked(fetchReportTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchReportTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    render(<NewReportPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    const button = screen.getByText('Create report').closest('button') as HTMLButtonElement
    expect(button.disabled).toBe(true)

    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'A title' },
    })
    expect(button.disabled).toBe(false)
  })

  it('surfaces a create error without crashing', async () => {
    vi.mocked(fetchReportTemplates).mockResolvedValue([SINGLE_SUMMARY])
    vi.mocked(fetchReportTemplate).mockResolvedValue(SINGLE_TEMPLATE)
    vi.mocked(createReport).mockRejectedValue(new Error('title must not be empty'))
    render(<NewReportPane setupMode="single" onCreated={vi.fn()} />)

    await waitFor(() => expect(screen.getByDisplayValue('Luxen LN-10P')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/e.g. Panel A alone/), {
      target: { value: 'A title' },
    })
    fireEvent.click(screen.getByText('Create report'))

    await waitFor(() =>
      expect(screen.getByText(/Failed to create: title must not be empty/)).toBeTruthy(),
    )
  })
})
