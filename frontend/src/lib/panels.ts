// Shapes for panel models, mirroring mpp_sdk/panels/record.py and the
// GET/POST/PATCH/DELETE /api/panels routes in scripts/curve_tracer_server.py.
// Same split as lib/sessions.ts: wire types and pure helpers live here,
// api.ts is the one place that crosses the wire.
//
// A panel model is the module's specification (Voc/Isc/Vmp/Imp/Pmax as
// printed on the label) - not "panel A"/"panel B", which stay the bench
// position in mpp_sdk/curves (types.ts's PanelSetup). Called "panel model"
// throughout the UI to keep the two apart.

export interface PanelModelRecord {
  id: string
  name: string
  manufacturer: string
  model: string
  /** `null` means genuinely unknown, not zero - see mpp_sdk/panels/record.py. */
  p_max_w: number | null
  voc: number | null
  isc: number | null
  vmp: number | null
  imp: number | null
  notes: string
}

export interface CreatePanelModelInput {
  name: string
  manufacturer?: string
  model?: string
  p_max_w?: number | null
  voc?: number | null
  isc?: number | null
  vmp?: number | null
  imp?: number | null
  notes?: string
}

export type PatchPanelModelInput = Partial<CreatePanelModelInput>

/** "Luxen LN-10P, 10 W" - the free-text summary a picked panel model
 * snapshots into a session's own "panel"/"panel_a"/"panel_b" field. Omits
 * a null p_max_w rather than showing "null W". */
export function composePanelModelLabel(panel: PanelModelRecord): string {
  return panel.p_max_w == null ? panel.name : `${panel.name}, ${panel.p_max_w} W`
}

/** "12.3" or "" for a null value - the snapshot fields are plain text
 * (SessionRecord.fields is Record<string, string>), and "" is what an
 * unset upstream number becomes rather than the string "null". */
export function formatSnapshotNumber(value: number | null): string {
  return value == null ? '' : String(value)
}

/** The field keys a picked panel model occupies in a session's `fields`:
 * `labelKey` ("panel" in Single, "panel_a"/"panel_b" in Full) holds the
 * free-text summary, and `${prefix}_voc`/`_isc`/`_vmp`/`_imp`
 * ("panel_model" in Single, "panel_a_model"/"panel_b_model" in Full) hold
 * the snapshotted numbers - see mpp_sdk/sessions/templates/*.json's
 * field_defs for the exact keys this must match. Exposed on its own
 * (not just folded into `panelModelSnapshotFields` below) so a caller can
 * compute which keys a picker owns before any panel model is picked -
 * NewSessionPane uses this to hide them from its generic field_defs list. */
export function panelModelFieldKeys(labelKey: string, prefix: string): string[] {
  return [labelKey, `${prefix}_voc`, `${prefix}_isc`, `${prefix}_vmp`, `${prefix}_imp`]
}

/** The snapshot field values a picked panel model writes into a session's
 * `fields` - see `panelModelFieldKeys` for the keys these values land on. */
export function panelModelSnapshotFields(
  labelKey: string,
  prefix: string,
  panel: PanelModelRecord,
): Record<string, string> {
  const [label, voc, isc, vmp, imp] = panelModelFieldKeys(labelKey, prefix)
  return {
    [label]: composePanelModelLabel(panel),
    [voc]: formatSnapshotNumber(panel.voc),
    [isc]: formatSnapshotNumber(panel.isc),
    [vmp]: formatSnapshotNumber(panel.vmp),
    [imp]: formatSnapshotNumber(panel.imp),
  }
}

// A session field holding a snapshotted panel-model number is read-only
// in the workbench regardless of the session's own edit/view mode -
// editing it by hand would silently disagree with the panel model it was
// copied from. Recognized purely by key shape (matches
// "..._model_{voc,isc,vmp,imp}", e.g. "panel_model_voc" or
// "panel_a_model_vmp") so SessionView never needs the template itself -
// same reasoning as humanizeKey below not needing it either.
const PANEL_MODEL_SNAPSHOT_KEY_RE = /_model_(voc|isc|vmp|imp)$/

export function isPanelModelSnapshotField(key: string): boolean {
  return PANEL_MODEL_SNAPSHOT_KEY_RE.test(key)
}
