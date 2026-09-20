import { useEffect, useState } from 'react'
import { PanelModelPicker } from '@/components/PanelModelPicker'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { createSession, fetchSessionTemplate, fetchSessionTemplates } from '@/lib/api'
import { panelModelFieldKeys, panelModelSnapshotFields, type PanelModelRecord } from '@/lib/panels'
import { readOnlyReasonText, useReadOnly } from '@/lib/sessionFile'
import type { SessionRecord, SessionTemplate, SessionTemplateSummary } from '@/lib/sessions'
import type { SetupMode } from '@/lib/setupMode'

// Which panel-model picker(s) a template's setup gets, and the field keys
// each one owns (see lib/panels.ts's panelModelFieldKeys) - one picker in
// Single, two (A and B, matching the bench position convention) in Full.
// "panel A"/"panel B" here means the bench position, unrelated to which
// picker instance renders first.
const SINGLE_PANEL_SLOTS = [{ label: 'Panel model', labelKey: 'panel', prefix: 'panel_model' }]
const FULL_PANEL_SLOTS = [
  { label: 'Panel A model', labelKey: 'panel_a', prefix: 'panel_a_model' },
  { label: 'Panel B model', labelKey: 'panel_b', prefix: 'panel_b_model' },
]

function panelSlotsFor(setup: string): typeof SINGLE_PANEL_SLOTS {
  return setup === 'full' ? FULL_PANEL_SLOTS : SINGLE_PANEL_SLOTS
}

// The generic field_defs table below renders every setup field except the
// ones a PanelModelPicker above it already owns (see panelSlotsFor) - a
// picked panel model's label and Voc/Isc/Vmp/Imp are set by picking, not
// by typing into this table.
function visibleFieldDefs(template: SessionTemplate) {
  const hidden = new Set(
    panelSlotsFor(template.setup).flatMap((slot) => panelModelFieldKeys(slot.labelKey, slot.prefix)),
  )
  return template.field_defs.filter((fd) => !hidden.has(fd.key))
}

/**
 * Picks a template, names the session, fills in its setup fields, and
 * creates it - the one place `POST /api/sessions` is called. Preselects
 * the template matching the current setup mode (Single/Full), so an
 * operator on the panel-A bench doesn't have to hunt for the right one.
 *
 * Gated on `useReadOnly()` itself, not just by the caller hiding the
 * sidebar's "New session" row (App.tsx's `canCreateSession`) or the
 * content switch skipping this pane while an imported session is active:
 * the same defense-in-depth every other mutating pane in this app
 * applies (see CurveCategoryPane/RunDatePane's own `readOnly.enabled`
 * checks) - a control that only ever exists because of an outer branch
 * being correct is one bug away from a live write happening under a
 * banner that promises otherwise.
 */
export function NewSessionPane({
  setupMode,
  onCreated,
}: {
  setupMode: SetupMode
  onCreated: (session: SessionRecord) => void
}) {
  const readOnly = useReadOnly()
  const [templates, setTemplates] = useState<SessionTemplateSummary[] | null>(null)
  const [templatesError, setTemplatesError] = useState<string | null>(null)
  const [templateId, setTemplateId] = useState('')
  const [template, setTemplate] = useState<SessionTemplate | null>(null)
  const [templateError, setTemplateError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    if (readOnly.enabled) return
    fetchSessionTemplates()
      .then(setTemplates)
      .catch((e) => setTemplatesError(e instanceof Error ? e.message : String(e)))
  }, [readOnly.enabled])

  // Preselect the template matching the current bench setup, once the
  // list arrives - never fights a later, manual pick (only runs when the
  // fetched list itself changes).
  useEffect(() => {
    if (templates === null || templateId !== '') return
    const match = templates.find((t) => t.setup === setupMode) ?? templates[0]
    if (match) setTemplateId(match.template_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates])

  useEffect(() => {
    if (readOnly.enabled || templateId === '') {
      setTemplate(null)
      return
    }
    setTemplateError(null)
    fetchSessionTemplate(templateId)
      .then((t) => {
        setTemplate(t)
        setFields(Object.fromEntries(t.field_defs.map((fd) => [fd.key, fd.default])))
      })
      .catch((e) => setTemplateError(e instanceof Error ? e.message : String(e)))
  }, [readOnly.enabled, templateId])

  async function handleCreate() {
    if (readOnly.enabled || !title.trim() || templateId === '' || creating) return // defense in depth
    setCreating(true)
    setCreateError(null)
    try {
      const session = await createSession({ template_id: templateId, title, fields })
      onCreated(session)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  if (readOnly.enabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>New session is unavailable</CardTitle>
          <CardDescription>
            {readOnlyReasonText(readOnly.reason ?? 'demo', 'Creating a session')}
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>New session</CardTitle>
        <p className="text-sm text-muted-foreground">
          A filled-in copy of a checklist template, tracked from setup to teardown.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {templatesError && (
          <p className="text-sm text-destructive">Failed to load templates: {templatesError}</p>
        )}

        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Template
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            disabled={!templates || templates.length === 0}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          >
            {(!templates || templates.length === 0) && <option value="">Loading...</option>}
            {templates?.map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.title} ({t.setup}, {t.n_steps} steps)
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Title
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Panel A alone under the lamp"
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
          />
        </label>

        {templateError && (
          <p className="text-sm text-destructive">Failed to load template: {templateError}</p>
        )}

        {template && (
          <div className="flex flex-col gap-2">
            {panelSlotsFor(template.setup).map((slot) => (
              <PanelModelPicker
                key={slot.labelKey}
                label={slot.label}
                onPick={(panel: PanelModelRecord) =>
                  setFields((prev) => ({
                    ...prev,
                    ...panelModelSnapshotFields(slot.labelKey, slot.prefix, panel),
                  }))
                }
              />
            ))}
          </div>
        )}

        {template && visibleFieldDefs(template).length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {visibleFieldDefs(template).map((fd) => (
              <label key={fd.key} className="flex flex-col gap-1 text-sm text-muted-foreground">
                {fd.label}
                <input
                  type="text"
                  value={fields[fd.key] ?? ''}
                  onChange={(e) => setFields((prev) => ({ ...prev, [fd.key]: e.target.value }))}
                  placeholder={fd.hint || undefined}
                  className="rounded-md border bg-transparent px-2 py-1.5 text-sm text-foreground"
                />
                {fd.hint && <span className="text-xs">{fd.hint}</span>}
              </label>
            ))}
          </div>
        )}

        <Button
          onClick={handleCreate}
          disabled={creating || !title.trim() || templateId === ''}
          className="self-start"
        >
          {creating ? 'Creating...' : 'Create session'}
        </Button>
        {createError && <p className="text-sm text-destructive">Failed to create: {createError}</p>}
      </CardContent>
    </Card>
  )
}
