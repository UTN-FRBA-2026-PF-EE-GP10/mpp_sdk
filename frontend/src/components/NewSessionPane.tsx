import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { createSession, fetchSessionTemplate, fetchSessionTemplates } from '@/lib/api'
import { readOnlyReasonText, useReadOnly } from '@/lib/sessionFile'
import type { SessionRecord, SessionTemplate, SessionTemplateSummary } from '@/lib/sessions'
import type { SetupMode } from '@/lib/setupMode'

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

        {template && template.field_defs.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {template.field_defs.map((fd) => (
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
