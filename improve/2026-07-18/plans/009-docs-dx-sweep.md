# Plan 009: Docs and tooling sweep after the merge wave

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**, paths split across lines for readability
> (pass them all to one `git diff --stat 6fc47a0..HEAD --` invocation):
>
> ```text
> README.md pyproject.toml .github/workflows/
> harness/compare_cyclic.py examples/ main.py
> firmware/pipico_board/README.md improve/2026-07-18/plans/README.md
> ```
>
> On any change, re-verify the excerpts below before editing; a direct
> contradiction = STOP.
>
> **Refreshed 2026-07-22 (commit `2aa9d35`)** after a follow-up `/improve`
> audit: item 1's "PWM is still the placeholder pin" is now stale (plan
> 002 shipped the real gate PWM) - see the updated item 1 and step 1
> below. Items 9-12 and their steps/scope are new from that audit; items
> 1-8 and their steps are unchanged from the original 2026-07-18 write-up.

## Status

- **Priority**: P3
- **Effort**: S (many small independent items)
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs / dx
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

A large merge wave (harness consolidation, INA229 firmware, final PCB, CI
hardening) left the written record behind the code in several small,
independently fixable spots. Stale docs that are actively wrong are worse
than missing ones - the root README currently under-reports delivered
work, two promised README files don't exist, and the toolchain config
disagrees with itself in three places.

## Current state (verified facts, one per item)

1. `README.md:206` - `- [ ] SpiMcuSource(SignalSource)` unchecked, but
   `mpp_sdk/io/spi_mcu.py` ships it. `README.md:207` - MCU firmware (ADC +
   PWM + SPI-slave) unchecked, but ADC, the real 100 kHz gate PWM (plan
   002), and the PIO SPI-slave are all merged
   (`firmware/pipico_board/src/`) - check it fully now, PWM is no longer a
   placeholder. `README.md:208` - Calibration (ADC scale/offset, INA229
   calibration / INA281 gain, PWM freq, duty limits) unchecked, but ADC
   scale/offset, `SHUNT_CAL`, PWM frequency and `DUTY_MAX` are all
   implemented - check it with a trailing note that only INA281
   gain/shunt remains open. `README.md:215` - CI workflow unchecked, but
   `.github/workflows/ci.yml` does uv sync + ruff + pytest. `README.md:216`
   - `data/` unchecked, but `data/plecs/` exists with a README.
2. No `hardware/README.md`. The folder mixes KiCad SOURCE
   (`*.kicad_sch`, `Proyecto0.1V.kicad_pcb`, `Proyecto0.1V.kicad_pro`,
   `Custom_Library.pretty/`) with GENERATED artifacts (`jlcpcb/gerber/`,
   `jlcpcb/production_files/`, `Proyecto0.1V-schematic.pdf`,
   `Proyecto0.1V-pcb.pdf`). The PDFs were generated with kicad-cli 10.0.1:

   ```sh
   kicad-cli sch export pdf Proyecto0.1V.kicad_sch \
       -o Proyecto0.1V-schematic.pdf
   kicad-cli pcb export pdf Proyecto0.1V.kicad_pcb \
       -o Proyecto0.1V-pcb.pdf \
       -l F.Cu,B.Cu,F.SilkS,B.SilkS,F.Fab,B.Fab,Edge.Cuts \
       --cl Edge.Cuts --mode-multipage --include-border-title
   ```

   Note: `untitled.kicad_sch` IS live source (the AnalogConverters sensing
   sheet, badly named) - say so in the README, do NOT delete or rename it.
3. No `data/README.md`, but `AGENTS.md` ("What not to commit") promises:
   "Measured data lives under `data/` with a `data/README.md` documenting
   the scrub." Only `data/plecs/README.md` exists (generated lookup
   tables, not measured data).
4. `harness/compare_cyclic.py` module docstring presents it as a runnable
   script only, but `compare_noise.py`, `compare_rescan.py` and
   `compare_seeds.py` import its symbols (`make_profile`,
   `plateau_spans`, `segment_stats`, `build_conditions`, `run`,
   `ALGORITHMS`, `BAND`, `RESCAN_PERIOD`, `INITIAL_DUTY`) as a library.
5. `examples/pno_demo.py:9-10` says "This is the same demo as `main.py`" -
   two full copies of the same P&O demo body that will drift. `README.md`
   and `AGENTS.md` call `main.py` the canonical quickstart.
6. `pyproject.toml:35` - `target-version = "py313"  # Bump when ruff
   supports py314 as a target.` while `requires-python = ">=3.14"`.
7. `.github/workflows/ci.yml:20,36` use `astral-sh/setup-uv@v6`;
   `.github/workflows/entregables.yml:42` uses `@v5`.
8. `.github/workflows/docs.yml:30,48` install docs deps via
   `pip install mkdocs-material pymdown-extensions`, bypassing the
   `docs` dependency group declared in `pyproject.toml`.
9. `firmware/pipico_board/README.md`'s GPIO table lists GPIO4 as
   "General purpose", but 4x WS2812 NeoPixels are now physically wired
   there in series (per plan 013's own "Current state" section) - this is
   a fact about the board today, independent of whether plan 013's driver
   code has landed. Anyone wiring/debugging from the README alone could
   wrongly assume GPIO4 is free.
10. `.github/workflows/firmware.yml` has no `cargo clippy` step anywhere
    (only `cargo fmt --check` and `cargo build --release --locked`), and
    no README mentions it as an expected local practice either - clippy
    is simply absent end-to-end for code driving a live power stage.
11. Neither `README.md` nor `AGENTS.md` contains the string
    `pipico_board` or links to `firmware/pipico_board/README.md`, which is
    where the actual build/flash/calibration instructions live - a
    contributor working from the root docs has no discoverable path to
    them.
12. `improve/2026-07-18/plans/README.md:3` still opens with "Two batches,
    one index, written at commit `6fc47a0`" describing only plans 001-009,
    but the status table and dependency notes now run through plan 014
    (added across later PRs) with no wave/parallelization guidance for
    010-014.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint/format | `uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Tests | `uv run pytest -q` | all pass |
| Markdown lint | `uvx markdownlint-cli2 "**/*.md" "#node_modules"` (or rely on pre-commit) | exit 0 |
| Quickstart smoke | `timeout 10 uv run main.py` (headless: expect matplotlib window attempt or clean start) | starts without ImportError |
| Ruff support check | `uv run ruff check --target-version py314 - < /dev/null` | exit 0 = supported |

## Scope

**In scope**:

- `README.md` (roadmap checkboxes only)
- `hardware/README.md` (create)
- `data/README.md` (create)
- `harness/compare_cyclic.py` (docstring only)
- `examples/pno_demo.py` (reduce to a shim)
- `pyproject.toml` (ruff target-version only)
- `.github/workflows/entregables.yml` (setup-uv version only)
- `.github/workflows/docs.yml` (dependency install lines only)
- `firmware/pipico_board/README.md` (GPIO4 row only, item 9)
- `.github/workflows/firmware.yml` (add a clippy step, item 10)
- `AGENTS.md` (one cross-reference sentence, item 11)
- `improve/2026-07-18/plans/README.md` (opening framing paragraph only,
  item 12 - not the status table or dependency notes, those are kept
  current by whichever plan lands most recently)

**Out of scope** (do NOT touch):

- `firmware/pipico_board/README.md`'s GPIO0-3 rows or PWM wording - both
  plans 001 and 002 are DONE and already keep that content current; this
  plan's item 9 touches only the GPIO4 row, nothing else in that file.
- `main.py` body (it stays the canonical demo).
- Any harness logic; any docs/ content pages; entregables content.

## Steps

### Step 1: README roadmap checkboxes

Mark `SpiMcuSource`, MCU firmware, CI workflow, and `data/` as `[x]` (MCU
firmware is now fully shipped, no trailing note needed). Mark Calibration
as `[x]` with a trailing note "(INA281 gain/shunt still open - see
improve/2026-07-18/plans/010)". **Verify**: markdownlint clean.

### Step 2: hardware/README.md

Short file: source vs generated table (facts in Current state item 2),
the two regeneration commands, the `untitled.kicad_sch` naming note, and
"regenerate the PDFs and jlcpcb outputs after any schematic/layout
change". **Verify**: markdownlint clean.

### Step 3: data/README.md

State: `data/plecs/` = generated simulation references (link its README);
measured bench data will land in `data/bench/` as CSV; before committing
any measured file, scrub location/serial metadata per `AGENTS.md` "What
not to commit" (exiftool for binaries, header review for CSVs).
**Verify**: markdownlint clean.

### Step 4: compare_cyclic docstring

Add a paragraph: "Consumed as a library by compare_noise.py,
compare_rescan.py and compare_seeds.py (profile machinery and the
ALGORITHMS/BAND/RESCAN_PERIOD constants) - renaming or re-signaturing
public symbols here breaks them." **Verify**: `uv run pytest -q` still
passes (docstring-only change).

### Step 5: Deduplicate the P&O demo

Replace `examples/pno_demo.py`'s body with a thin shim that runs the
canonical demo, keeping the file (AGENTS.md points demos at `examples/`):

```python
"""P&O quickstart - canonical body lives in main.py. Run either one."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "main.py"), run_name="__main__")
```

**Verify**: `timeout 10 uv run examples/pno_demo.py` starts the same demo
(window opens or headless backend message - no traceback).

### Step 6: Tooling alignment

- `pyproject.toml`: run the ruff support check command; if py314 is
  accepted, set `target-version = "py314"` and drop the stale comment; if
  NOT accepted, leave it and note in the status row.
- `entregables.yml`: `setup-uv@v5` -> `@v6`.
- `docs.yml`: replace both `pip install mkdocs-material pymdown-extensions`
  lines with uv-group installs (`uv sync --group docs` after a setup-uv
  step, then `uv run mkdocs ...` for the build/deploy commands that
  follow) - read the two jobs and keep their build/deploy commands
  otherwise intact. First confirm `pyproject.toml`'s `docs` group actually
  contains mkdocs-material and pymdown-extensions; if it does not, add the
  missing package to the group rather than keeping the pip line.

**Verify**: `uv run ruff check . && uv run ruff format --check .` exit 0;
`uv run pytest -q` passes.

### Step 7: GPIO4 README row

Change `firmware/pipico_board/README.md`'s GPIO4 row's "Function / Notes"
column from "General purpose" to something like "4x WS2812 NeoPixels
wired in series (driver not yet implemented, see plan 013)". Touch only
that one row. **Verify**: markdownlint clean; `grep -c "General purpose"
firmware/pipico_board/README.md` drops by exactly 1.

### Step 8: Firmware CI clippy step

Add a `cargo clippy --all-targets -- -D warnings` step to
`.github/workflows/firmware.yml` alongside the existing `fmt --check` and
`build` steps. First run `cargo clippy --all-targets` locally in
`firmware/pipico_board/` (and `firmware/esp32c3-bpw34/` if it builds
cleanly enough to lint) - if it surfaces more than a handful of
pre-existing warnings, land the CI step without `-D warnings` first (warn
only) and note in this plan's status that tightening to deny is a
follow-up, rather than trying to fix a pile of unrelated lints in a
docs/DX plan. **Verify**: CI step present and green (or intentionally
warn-only, documented).

### Step 9: Cross-reference the firmware README

Add one sentence to `README.md`'s Hardware section and one to
`AGENTS.md`'s Hardware target section pointing at
`firmware/pipico_board/README.md` for build/flash/calibration
instructions. **Verify**: markdownlint clean.

### Step 10: Refresh the plans index framing

Update `improve/2026-07-18/plans/README.md`'s opening paragraph (currently
"Two batches, one index, written at commit `6fc47a0`" describing only
001-009) to acknowledge the later additions (010-014) without rewriting
the whole file - a sentence or two is enough. Do not touch the status
table or dependency notes sections; those are kept current by whichever
plan lands most recently, not by this one. **Verify**: markdownlint clean.

## Test plan

No new tests - this is docs/config. The gates are markdownlint, ruff,
pytest, and the two smoke commands above. CI on the PR exercises the
workflow edits (docs.yml runs on docs changes; entregables.yml on
entregables changes - if neither triggers on this PR, state that in the
report and rely on the next natural trigger).

## Done criteria

- [ ] All four README/data/hardware doc items in place; markdownlint clean
- [ ] `examples/pno_demo.py` is a shim; both quickstart entry points run
- [ ] Ruff target matches the runtime (or documented as unsupported)
- [ ] One `setup-uv` version across workflows; docs.yml uses the uv group
- [ ] GPIO4 README row updated (item 9)
- [ ] Firmware CI has a clippy step, warn-only or deny documented (item 10)
- [ ] Root docs cross-reference the firmware README (item 11)
- [ ] Plans index opening paragraph refreshed, table/notes untouched (item 12)
- [ ] `uv run pytest -q` exits 0
- [ ] No out-of-scope files modified
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- `pyproject.toml` has no `docs` dependency group at all (recon said it
  exists at lines 26-30) - re-check before inventing one.
- Ruff rejects py314 AND emits errors under py313 on current code.
- Any Current-state fact above contradicts the live file.

## Maintenance notes

- When plan 002 lands the real gate PWM, revisit the README.md MCU
  checkbox note added in step 1.
- When measured bench data first lands (plan 003's CSV), data/README.md's
  scrub section becomes load-bearing - review it then.
