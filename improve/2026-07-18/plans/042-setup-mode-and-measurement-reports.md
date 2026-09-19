# Plan 042: Setup mode (single/full) and measurement reports in the workbench

> **Executor instructions**: three parts, built by separate agents in this
> order: Part A and Part B in parallel (disjoint files), then Part C on top
> of both. The API contract in Part B is fixed here so Part C can rely on
> it. Read AGENTS.md and `frontend/README.md` first. Frontend: single
> quotes, no semicolons, vendored `src/components/ui/*` in double quotes,
> never run prettier. Comments explain why, plain hyphens, no improve/ plan
> numbers in source comments.

## Status

- **Priority**: P1 - the panel A session (2026-09-19) and the two-panel
  session (the week after) need both.
- **Effort**: L (three PRs).
- **Risk**: LOW - no firmware, no change to how the converter is driven.
- **Category**: feature (operator request).
- **Planned at**: 2026-09-19, after PRs #105/#106.

## Why this matters

Two gaps showed up while planning the first sessions on the real panels:

1. The workbench always assumes two panels (A fixed, B tilted). With one
   panel (the Luxen LN-10P, 10 W, 12 V) the Panel B tilt field is
   meaningless, and the saved curve records a panel B that is not there.
2. A measurement session is more than its curves and runs: the setup, the
   checks done before energizing, the meter readings, what passed, what
   was skipped, the open questions. Today that lives in chat and memory.
   A **measurement report** makes each session a checklist that is
   followed from scratch, filled in as it goes, and read later - with its
   curves and runs attached. The same template is reused for every future
   session.

## Part A: setup mode (frontend only)

A **Single / Full** toggle in the header, left of the theme toggle and the
A/W unit toggle, persisted in `localStorage` (same pattern as the units
and theme providers: a `SetupModeProvider` + `useSetupMode()`, key
`mpp-sdk.setup-mode`, default `full`, wrapped in try/catch).

- **Single**: one panel, A. The capture form shows no Panel B tilt field;
  the saved curve's `panels` is `[{"id": "A", "tilt_deg": 90}]`. The
  **Tilted** kind is unavailable for capture (it needs panel B): hidden
  from the "Capturing under:" row with a one-line note why.
- **Full**: today's behaviour: A fixed at 90, B from 90/70/60/45/30.
- The run form shows a short hint for the load: Single "10 Ohm, 10 W on
  the output (MPP near D = 0.37)", Full "20 Ohm (two 10 Ohm, 10 W in
  series)".
- Switching to Full shows a one-time reminder, dismissible: "Two panels
  reach ~34-44 V: switch the ADC range to `Mid` and recalibrate
  (docs/hardware_v1/calibration.md)".
- Saved curves show their panel count in the pane metadata ("1 panel" /
  "2 panels") from `panels.length`; no schema change.
- Tests (vitest): the toggle persists; Single hides the B tilt field and
  the Tilted kind; a save in Single sends one panel.

## Part B: measurement reports - backend (Python only)

### Data model: `mpp_sdk/reports/` (record.py, library.py, `__init__`)

Same patterns as `mpp_sdk/curves` and `mpp_sdk/runs` (frozen dataclasses,
`to_dict`/`from_dict` with a `schema` version, `library.save/load/load_all/
delete`, files under `default_dir()` = `data/reports/`, overridable with
`MPP_SDK_REPORT_DIR`, git-ignored like curves and runs).

A **report** is a filled-in copy of a **template**:

```json
{
  "schema": 1,
  "id": "20260919T160000Z-panel-a-lamp",
  "title": "Panel A alone under the lamp",
  "template_id": "single-panel-characterization",
  "template_version": 1,
  "setup": "single",
  "created_at": "2026-09-19T16:00:00+00:00",
  "updated_at": "2026-09-19T17:30:00+00:00",
  "fields": {"panel": "Luxen LN-10P, 10 W, 12 V", "light": "", "...": ""},
  "steps": [
    {
      "id": "meter-vout",
      "section": "Before energizing",
      "title": "Meter check of V out",
      "instructions": "At a fixed duty with the load on, compare ...",
      "kind": "check",
      "status": "todo",
      "value": null,
      "unit": null,
      "notes": "",
      "curve_ids": [],
      "run_ids": []
    }
  ],
  "open_questions": [
    {"id": "temperature", "text": "Panel temperature is not measured ...",
     "answer": ""}
  ]
}
```

- `kind`: `check` (done/not), `number` (a value with a `unit`, e.g. a
  meter reading), `text`, `curve` (expects linked curves), `run` (expects
  linked runs).
- `status`: `todo` | `done` | `failed` | `skipped`.
- `curve_ids` / `run_ids`: ids as served by `/api/curves` and `/api/runs`
  (filename stems). A report never copies curve or run data; it links.
- `fields`: free key/value strings for the setup (panel, light source,
  distance, load resistor, ADC range, firmware commit, operator notes).
  The template defines which keys exist and their labels.

### Templates: `mpp_sdk/reports/templates/*.json` (in the repo)

A template is a report without values: `template_id`, `version`, `title`,
`setup`, `field_defs` (key, label, hint), `steps` (id, section, title,
instructions, kind, unit, pass criteria in the instructions), and
`open_questions`. Ship two:

1. **`single-panel-characterization`** (Single) - the panel A session. Its
   steps are the checklist in this plan's appendix.
2. **`full-setup-characterization`** (Full) - the two-panel session:
   the same safety and link sections, then ADC range `Mid` +
   recalibration, bypass-diode check, light check, baseline, one curve
   per B tilt (70/60/45/30), P&O / Scan&Track / PSO on the most tilted
   two-peak curve, the seed test near the lower peak.

Both carry the open question on **temperature**: "Panel temperature is not
measured (no PT100 fitted; the MAX31865 is off). Voc falls with
temperature, so curves taken at different times are not strictly
comparable. How to record it: a contact thermometer on the panel back, an
IR thermometer, or a fitted PT100?"

### API (added to `scripts/curve_tracer_server.py`)

| Method and path | Body / result |
|---|---|
| `GET /api/report-templates` | `[{template_id, version, title, setup, n_steps}]` |
| `GET /api/report-templates/{template_id}` | the full template |
| `GET /api/reports` | `[{id, title, template_id, setup, created_at, updated_at, n_steps, n_done, n_failed}]`, newest first |
| `POST /api/reports` | `{"template_id", "title", "fields"?}` -> the new report (200) |
| `GET /api/reports/{id}` | the full report |
| `PATCH /api/reports/{id}` | partial update: `{"title"?, "fields"?, "steps"?: [{id, status?, value?, notes?, curve_ids?, run_ids?}], "open_questions"?: [{id, answer}]}` -> the updated report |
| `DELETE /api/reports/{id}` | 204 |

Rules: ids validated with the same regex/containment pattern as
`_curve_path`/`_run_path` (never a path from the request); step ids in a
PATCH must exist in the report (400 otherwise); `status` must be one of
the four; string sizes bounded (title 200, notes 5000, field values 500,
at most 100 linked ids per step); `updated_at` set by the server; writes
go through a temp file + `os.replace` so a crash never leaves a half
file. Linked curve/run ids are stored as given (they may be deleted
later - the frontend says so). Reports are written in Demo mode never
(the frontend blocks it; the server needs no special case). Tests for
every route and rule, in `tests/test_curve_tracer_server.py` and a new
`tests/test_reports.py` for the library.

## Part C: measurement reports - frontend

- Sidebar: a **Reports** section (between Runs and the rest), listing
  reports newest first with a progress count ("12 / 20").
- **New report**: pick a template (the setup mode preselects the matching
  one), a title, then the setup fields.
- **Report view** (the main pane), read top to bottom like a document:
  - Header: title, template, setup, created/updated, progress bar.
  - Setup fields as a small editable table.
  - Sections with their steps. Each step: a status control
    (todo/done/failed/skipped), the instructions, the value input for
    `number` steps (with unit), notes, and for `curve`/`run` steps the
    linked items: small curve charts (reuse `CurveChart`) with Voc/Isc/MPP,
    runs with algorithm, duration, held power and P/MPP_th, each opening
    the existing curve dialog / run player. A picker links items from the
    library; a shortcut links "the most recent curve" / "the most recent
    run".
  - Open questions with an answer box.
  - A missing linked item (deleted) shows as such, never crashes.
- Edits save with `PATCH` (debounced), with a visible saved/failed state.
- **Readable**: a print stylesheet so the browser's Print gives a clean
  document; **Download** as JSON and as Markdown (a readable summary with
  every step, value, note and linked item's key numbers).
- Demo mode: one bundled fixture report, read-only, like the demo curves.
- Tests (vitest) for the view, status/value edits sending the right PATCH,
  linking, the missing-item case, and demo read-only.

## Done criteria

- [ ] Three PRs, each adversarially reviewed and merged with CI green.
- [ ] On the Pi: Single mode, a new report from the single-panel template,
      a curve and a run linked, printed to PDF and readable.

## Appendix: the single-panel checklist (template content)

**Setup fields**: panel (default "Luxen LN-10P, 10 W, 12 V"; Voc, Isc,
Vmp, Imp from its label), light source and setting, distance, load
resistor (10 Ohm, 10 W), ADC range (`Low`), supply used for checks,
firmware commit, operator.

### Before energizing

- [ ] Panel label values recorded (number steps: Voc, Isc, Vmp, Imp).
- [ ] Firmware: `MppTracker`, `ADC_DIVIDER_RANGE = Low`,
   `MAX31865_ENABLED = false`; boot log shows the range and `T=n/a`.
- [ ] Load on the output: 10 Ohm, 10 W on J4.
- [ ] Q3 heatsink fitted, or runs kept short. Someone able to cut power.
- [ ] Workbench in **Single** mode; pill **PICO connected**.

### Link and limits

- [ ] Run config shows v_max 40 V, i_max 1 A, v_out_max 25 V.
- [ ] With nothing running, the link reads "waiting for sweep".

### Light and curve

- [ ] Light check: one sweep; Isc below 700 mA (number step, A). If not,
   reduce the light.
- [ ] Baseline curve saved (curve step): Voc, Isc, P at MPP recorded.
- [ ] Curve shape: one knee, points dense near it, not noisy (check).

### Runs (curve as reference, 10 s, starting duty 0.5)

- [ ] P&O run (run step): converged? held power as % of MPP_th (number, %).
- [ ] Samples per second from the P&O run (number): needed to set the
      link-down threshold.
- [ ] V out during the run (number, V) against the meter (number, V).
- [ ] InCond, Fuzzy, Scan&Track, PSO runs (run steps, one each).
- [ ] Seed test: P&O from starting duty 0.85 (run step): still converges on
      one peak?
- [ ] Stop test: a run stopped halfway aborts `stopped`, duty to 0 (run).
- [ ] Link-down test: SPI cable out mid-run aborts `link-down`, duty to 0
      (run).
- [ ] Q3 temperature after the runs (text: by hand or probe).

### After

- [ ] Curves and runs downloaded; report downloaded as Markdown.

**Open questions**: temperature (above); any unexpected behaviour.

## Addendum (2026-09-19): repeats, sessions, UX pass

### Repeated measurements (Part B and Part C)

A result from one sweep or one run is one sample. To get its spread, a
`curve` or `run` step asks for **N repeats** and links N items.

- Template and report steps carry `repeats` (integer 1-20, default 1;
  only `curve` and `run` steps may be above 1). It comes from the template
  and a PATCH cannot change it. More links than `repeats` are allowed.
- Shipped templates: the baseline curve, each tilt curve and every
  algorithm run ask for 3. The stop and link-down tests stay at 1.
- The report view (Part C) computes the statistics in the browser, over
  the linked items of one step. A session file (Part D) opened with no
  server then shows the same numbers.
  - Curves: Voc, Isc, Vmp, Imp, P at the MPP.
  - Runs: held power, P / MPP_th, time to converge.
  - For each: n, median, mean, standard deviation (n - 1), min, max.
    With n = 1, show the value alone, with no deviation.
  - A step shows "2 / 3 repeats" until it has enough links.
- The Markdown download has the same table.

### Part D: session files and view mode (frontend)

A **session file** holds a report and every curve and run linked to it,
or a set of chosen curves and runs, in one JSON file. Other people open
it in the workbench to look at it. No board or saved library is needed.

```json
{
  "format": "mpp-sdk-session",
  "schema": 1,
  "exported_at": "2026-09-19T18:00:00+00:00",
  "title": "Panel A alone under the lamp",
  "setup": "single",
  "report": null,
  "curves": [{"id": "<id as in /api/curves>", "record": {"...": "as served"}}],
  "runs": [{"id": "<id as in /api/runs>", "record": {"...": "full samples"}}],
  "missing": {"curve_ids": [], "run_ids": []}
}
```

- **Export**: from the sidebar selection (curves and runs chosen in
  select mode), and from a report (Part C: the report and all of its
  linked items). The browser builds the file from the existing API. Runs
  are fetched with all their samples. Linked items that no longer exist
  go in `missing`. The file name is `<title>.mppsession.json`.
- **Import**: an **Open session** control, and dropping a file on the
  page. The file is checked before use: `format`, `schema`, a size limit
  (50 MB), and every record parsed the same way API data is. A bad file
  gives a clear message and no view change.
- **View mode**: the workbench shows only the session's content,
  read-only, in the same views (curve dashboard, curve dialog, runs, run
  player, and the report once Part C exists). Capture, run start, delete,
  rename, remeasure and report edits are off. A header badge shows
  "Viewing: <title>" and a **Close** button returns to the normal mode.
  Nothing is written to the server. It works when no server answers, the
  same way demo (sandbox) mode does.
- Tests (vitest): a round trip from export to import; rejection of bad
  files; view mode is read-only; Close restores the previous mode.

### UX pass (frontend, in parallel)

A usability review of the current workbench, done by an agent that then
makes small, independent fixes. Each fix gets its own commit: clearer
labels and empty states, error messages that say what to do,
consistent units and number formats, keyboard and focus order,
accessible names, and mobile width. The review does not change the
sidebar structure or the header: Parts C and D change those.
