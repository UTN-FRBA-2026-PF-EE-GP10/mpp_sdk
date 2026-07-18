# Plan 009: Docs and tooling sweep after the merge wave

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- README.md pyproject.toml .github/workflows/ harness/compare_cyclic.py examples/ main.py`
> On any change, re-verify the excerpts below before editing; a direct
> contradiction = STOP.

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
   PWM + SPI-slave) unchecked, but INA229 acquisition + PIO SPI-slave are
   merged (`firmware/pipico_board/src/`); PWM is still the placeholder
   pin, so mark this one partially. `README.md:215` - CI workflow
   unchecked, but `.github/workflows/ci.yml` does uv sync + ruff + pytest.
   `README.md:216` - `data/` unchecked, but `data/plecs/` exists with a
   README.
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

**Out of scope** (do NOT touch):

- `firmware/pipico_board/README.md` - the GPIO0-3 rows belong to plan 001
  and the PWM wording to plan 002; touching them here creates conflicts.
- `main.py` body (it stays the canonical demo).
- Any harness logic; any docs/ content pages; entregables content.

## Steps

### Step 1: README roadmap checkboxes

Mark `SpiMcuSource`, CI workflow, and `data/` as `[x]`; for the MCU
firmware line use `[x]` with a trailing note "(gate PWM pin pending - see
improve/2026-07-18/plans/002)". **Verify**: markdownlint clean.

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
