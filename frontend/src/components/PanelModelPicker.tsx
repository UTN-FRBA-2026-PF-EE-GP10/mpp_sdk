import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { createPanelModel, fetchPanelModels, patchPanelModel } from '@/lib/api'
import type { PanelModelRecord } from '@/lib/panels'
import { readOnlyReasonText, useReadOnly } from '@/lib/sessionFile'

interface FormState {
  name: string
  manufacturer: string
  model: string
  p_max_w: string
  voc: string
  isc: string
  vmp: string
  imp: string
  notes: string
}

const BLANK_FORM: FormState = {
  name: '',
  manufacturer: '',
  model: '',
  p_max_w: '',
  voc: '',
  isc: '',
  vmp: '',
  imp: '',
  notes: '',
}

function toFormState(panel: PanelModelRecord): FormState {
  return {
    name: panel.name,
    manufacturer: panel.manufacturer,
    model: panel.model,
    p_max_w: panel.p_max_w == null ? '' : String(panel.p_max_w),
    voc: panel.voc == null ? '' : String(panel.voc),
    isc: panel.isc == null ? '' : String(panel.isc),
    vmp: panel.vmp == null ? '' : String(panel.vmp),
    imp: panel.imp == null ? '' : String(panel.imp),
    notes: panel.notes,
  }
}

// "" means "leave unset" for a number field - the API takes null/omitted
// for "unknown", never a guessed 0 (see mpp_sdk/panels/record.py).
function numberOrNull(text: string): number | null {
  const trimmed = text.trim()
  return trimmed === '' ? null : Number(trimmed)
}

/**
 * Picks a panel model from the library (`GET /api/panels`) and reports it
 * to the caller via `onPick` - the caller (`NewSessionPane`) is the one
 * that snapshots the picked values into the new session's fields, this
 * component only owns the library side. Also offers a small inline form
 * to add a new panel model or edit the picked one; a save re-fetches the
 * list and re-picks the saved record, so the caller's snapshot always
 * reflects what's now on disk.
 *
 * Gated on `useReadOnly()` itself, not just left to the fact that
 * `NewSessionPane` (its only caller today) already refuses to mount this
 * component while read-only - same defense-in-depth reasoning as
 * `NewSessionPane`'s own doc comment: a control that only exists because
 * an outer branch is correct is one bug away from a live fetch or write
 * happening under a banner that promises otherwise.
 */
export function PanelModelPicker({
  label,
  onPick,
}: {
  label: string
  onPick: (panel: PanelModelRecord) => void
}) {
  const readOnly = useReadOnly()
  const [panels, setPanels] = useState<PanelModelRecord[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(BLANK_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (readOnly.enabled) return
    fetchPanelModels()
      .then((fetched) => {
        setPanels(fetched)
        setLoadError(null)
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [readOnly.enabled])

  // Preselect the first panel model once the list arrives - never fights
  // a later, manual pick (only runs when the fetched list itself changes,
  // same pattern NewSessionPane uses to preselect a template).
  useEffect(() => {
    if (panels === null || panels.length === 0 || selectedId !== '') return
    const first = panels[0]
    setSelectedId(first.id)
    onPick(first)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panels])

  function pick(id: string) {
    if (readOnly.enabled) return // defense in depth
    setSelectedId(id)
    const panel = panels?.find((p) => p.id === id)
    if (panel) onPick(panel)
  }

  function openAddForm() {
    if (readOnly.enabled) return // defense in depth
    setEditingId(null)
    setForm(BLANK_FORM)
    setSaveError(null)
    setFormOpen(true)
  }

  function openEditForm() {
    if (readOnly.enabled) return // defense in depth
    const panel = panels?.find((p) => p.id === selectedId)
    if (!panel) return
    setEditingId(panel.id)
    setForm(toFormState(panel))
    setSaveError(null)
    setFormOpen(true)
  }

  async function handleSave() {
    if (readOnly.enabled || !form.name.trim() || saving) return // defense in depth
    setSaving(true)
    setSaveError(null)
    const input = {
      name: form.name,
      manufacturer: form.manufacturer,
      model: form.model,
      p_max_w: numberOrNull(form.p_max_w),
      voc: numberOrNull(form.voc),
      isc: numberOrNull(form.isc),
      vmp: numberOrNull(form.vmp),
      imp: numberOrNull(form.imp),
      notes: form.notes,
    }
    try {
      const saved = editingId ? await patchPanelModel(editingId, input) : await createPanelModel(input)
      setPanels((prev) => {
        const others = (prev ?? []).filter((p) => p.id !== saved.id)
        return [...others, saved].sort((a, b) => a.name.localeCompare(b.name))
      })
      setSelectedId(saved.id)
      onPick(saved)
      setFormOpen(false)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const readOnlyTitle = readOnly.enabled
    ? readOnlyReasonText(readOnly.reason ?? 'demo', 'Picking a panel model')
    : undefined

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-sm text-muted-foreground">
          {label}
          <select
            value={selectedId}
            onChange={(e) => pick(e.target.value)}
            disabled={readOnly.enabled || !panels || panels.length === 0}
            title={readOnlyTitle}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          >
            {(!panels || panels.length === 0) && <option value="">Loading...</option>}
            {panels?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.p_max_w != null ? `, ${p.p_max_w} W` : ''}
              </option>
            ))}
          </select>
        </label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={openEditForm}
          disabled={readOnly.enabled || !selectedId}
          title={readOnlyTitle}
        >
          Edit
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={openAddForm}
          disabled={readOnly.enabled}
          title={readOnlyTitle}
        >
          Add panel model
        </Button>
      </div>

      {loadError && (
        <p className="text-sm text-destructive">Failed to load panel models: {loadError}</p>
      )}

      {formOpen && !readOnly.enabled && (
        <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-2">
          <p className="text-xs font-medium text-muted-foreground">
            {editingId ? 'Edit panel model' : 'New panel model'}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <TextField label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
            <TextField
              label="Manufacturer"
              value={form.manufacturer}
              onChange={(v) => setForm({ ...form, manufacturer: v })}
            />
            <TextField
              label="Model"
              value={form.model}
              onChange={(v) => setForm({ ...form, model: v })}
            />
            <TextField
              label="Pmax (W)"
              value={form.p_max_w}
              onChange={(v) => setForm({ ...form, p_max_w: v })}
            />
            <TextField label="Voc (V)" value={form.voc} onChange={(v) => setForm({ ...form, voc: v })} />
            <TextField label="Isc (A)" value={form.isc} onChange={(v) => setForm({ ...form, isc: v })} />
            <TextField label="Vmp (V)" value={form.vmp} onChange={(v) => setForm({ ...form, vmp: v })} />
            <TextField label="Imp (A)" value={form.imp} onChange={(v) => setForm({ ...form, imp: v })} />
          </div>
          <TextField label="Notes" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} />
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={handleSave} disabled={saving || !form.name.trim()}>
              {saving ? 'Saving...' : 'Save panel model'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
          </div>
          {saveError && <p className="text-sm text-destructive">Failed to save: {saveError}</p>}
        </div>
      )}
    </div>
  )
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border bg-transparent px-2 py-1 text-sm text-foreground"
      />
    </label>
  )
}
