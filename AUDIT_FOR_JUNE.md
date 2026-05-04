# AUDIT_FOR_JUNE.md

A self-contained audit prompt for an LLM agent. Designed to be run **once,
around mid-June 2026** — that is, end of week 6 of the 30-week schedule
defined in `PLAN.md` *Team allocation, schedule, and scope*.

The whole reason this file exists is the **PCB-to-fab-by-end-of-week-6**
hard milestone. If hardware slips here, every later block slips with it,
so this audit is the cheapest insurance we have against silent drift.

## How to run

Hand this file to an agent (Claude Code, Cursor, etc.) with a prompt like:

> "Read `AUDIT_FOR_JUNE.md` and follow the **Audit protocol** section.
> Produce the report described in **Output format**. Read-only — do not
> modify any files in the repo."

The agent should produce a single markdown report; the maintainer reads
it before the next weekly sync and decides what to act on.

## Calibrate the schedule before auditing

Before running the checks below, determine *which week we are in*:

1. Read `PLAN.md` *Schedule* and note the assumed start date (the
   schedule was written on **2026-04-30**, week 1 starts there).
2. Run `git log --reverse --format='%h %ai' | head -1` to find the first
   commit; treat that as a sanity check on the start date.
3. Compute the current week number relative to that start. If the audit
   is being run before week 6 or after week 8, say so explicitly in the
   report and adjust expectations.

The protocol below is calibrated for **end of week 6**. If you are
running it earlier or later, downgrade or upgrade severities accordingly.

## Audit protocol

For each section, gather the listed evidence and answer the question. If
evidence is missing, **say so explicitly** rather than guess. Use
`Read` / `Bash` / `Grep` / `Glob` as needed; do not edit anything.

### 1. Hardware milestone (highest priority)

**Question: is the PCB ordered from fab? If not, when will it be?**

Evidence to gather:

- Look for a `hardware/` directory at the repo root, or a sibling repo
  referenced from `README.md` / `PLAN.md`.
- Search the repo for `*.kicad_pro`, `*.kicad_sch`, `*.kicad_pcb`,
  `gerber`, `BOM`, `JLCPCB`, `PCBWay`, `Eurocircuits`,
  `OSH Park` / `oshpark`.
- Check `git log --since='2026-04-30' --oneline` for hardware-flavoured
  commit messages.
- If `data/hardware/` exists, list its contents.

Severity table:

| Found                                | Flag       |
| ------------------------------------ | ---------- |
| No hardware artefacts at all         | CRITICAL   |
| Schematic only, no layout            | HIGH       |
| Layout in progress, not at fab       | HIGH       |
| Gerbers + BOM produced, not ordered  | MEDIUM     |
| At fab — note expected return date   | OK         |

### 2. Long-lead parts

**Question: are the FETs (GaN or SiC), gate driver, MCU, ADC, and
inductor on order or in hand?**

Evidence:

- A BOM file under `data/hardware/` or in the hardware repo.
- A purchase log, an order README, or order confirmation links.

Severity table:

| Found                                            | Flag    |
| ------------------------------------------------ | ------- |
| No BOM                                           | HIGH    |
| BOM exists but nothing ordered                   | MEDIUM  |
| Ordered — note ETA for any 4+ week-lead parts    | OK      |

### 3. Decision lock-in

**Question: have the MCU (Pi Pico vs ESP32), FET technology (GaN vs
SiC), gate driver, and sense topology (INA226 vs shunt + amp) been
decided and documented?**

Evidence:

- The *Open questions* section of `PLAN.md` — these items should have
  moved to *resolved* by now. Resolution may live in `PLAN.md`,
  `AGENTS.md`, `CHANGELOG.md`, or a dedicated
  `data/hardware/decisions.md`.

Flag any item still in *Open questions* as **HIGH**: layout cannot
finish without these locked.

### 4. SDK progress (Person A track)

**Question: are the planned in-tree models, the pvlib adapter, and the
SPI shim landing on schedule?**

Per the schedule, by end of week 6 we expect:

- Foundation block (weeks 1–4) deliverables in tree:
  - `mpp_sdk/models/lossy.py` → `SingleDiodeWithLosses`
  - `mpp_sdk/models/array.py` → `PanelArray` skeleton
  - `mpp_sdk/models/pvlib_adapter.py` → `PvlibPanelModel` skeleton
- Sim & SPI block (weeks 5–8), in progress:
  - Phase 3 algorithms: P&O variants + Incremental Conductance
  - Comparison-harness scaffold (likely under `mpp_sdk/benchmark/` or
    `examples/benchmark/`)
  - `mpp_sdk/io/spi_mcu.py` → `SpiMcuSource` skeleton
- A `tests/` directory (per `AGENTS.md`: created when the second model
  lands).

Evidence:

- `ls mpp_sdk/models/` and `ls mpp_sdk/io/`.
- `mpp_sdk/__init__.py` re-export list.
- `git log --oneline --since='2026-04-30' -- mpp_sdk/`.

Severity:

| Found                                              | Flag    |
| -------------------------------------------------- | ------- |
| Foundation deliverables missing                    | HIGH    |
| Foundation done, Sim & SPI not started             | MEDIUM  |
| Both in progress, no tests                         | MEDIUM  |
| Both progressing, tests landing                    | OK      |

### 5. Firmware progress (Person C track)

**Question: is the MCU firmware skeleton building? Is loopback HIL
working at least in software (Python `SpiMcuSource` ↔ mock MCU)?**

Evidence:

- A firmware directory: `firmware/`, `mcu/`, or a sibling repo.
  Look for `CMakeLists.txt`, `platformio.ini`, `pico_sdk_import.cmake`,
  `idf_component.yml`, `main.c` / `main.cpp`, MicroPython `main.py`.
- Search firmware sources for `SPI`, `ADC`, `PWM` references.
- A Python loopback test under `tests/` or `examples/` that exercises
  the SPI protocol against either a real device or a mock.

Severity:

| Found                                  | Flag    |
| -------------------------------------- | ------- |
| No firmware directory                  | HIGH    |
| Firmware exists, no SPI work           | MEDIUM  |
| SPI loopback works in software         | OK      |

### 6. Out-of-scope creep

**Question: has anyone started working on items listed in `PLAN.md`
*Out of scope for v1*?**

Grep the repo (code, commit messages, comments) for: `two-diode`,
`fuzzy`, `sliding mode`, `MPC`, `model predictive`, `reinforcement`,
` RL `, `synchronous boost`, `multi-string`, `Wi-Fi telemetry`,
`YAML fixture`.

Severity:

| Found                                          | Flag    |
| ---------------------------------------------- | ------- |
| Substantive code on out-of-scope items         | MEDIUM  |
| Mention in TODOs / comments only               | LOW     |
| Nothing                                        | OK      |

If anything substantive lands here, the recommendation is **always** to
pull the contributor back to in-scope work and note the deferred item
for "future work" in the paper. Out-of-scope is a budget decision, not
a quality decision.

### 7. Top-level health checks

Run these and include the (trimmed) output in the report:

```bash
uv sync 2>&1 | tail -5
uv run python -c "import mpp_sdk; print(mpp_sdk.__version__)"
```

If `tests/` exists:

```bash
uv run pytest --tb=short 2>&1 | tail -20
```

Do **not** run `uv run main.py` — it opens a GUI window.

Severity:

| Result                                  | Flag    |
| --------------------------------------- | ------- |
| `uv sync` or import fails               | HIGH    |
| Tests fail                              | HIGH    |
| Everything green                        | OK      |

## Output format

Produce one markdown report. Keep it under ~500 words. Structure:

```text
# Mid-June audit — week N (YYYY-MM-DD)

## Verdict
ON TRACK | AT RISK | OFF TRACK — one sentence justifying it.

## Milestone status
| Milestone                | Week | On track? | Notes |
| -------------------------|------|-----------|-------|
| PCB to fab               |  6   |  …        |  …    |
| HIL working              | 16   |  …        |  …    |

## Per-track status
A — SDK & integration: 2-3 sentences. Biggest blocker: …
B — hardware: 2-3 sentences. Biggest blocker: …
C — firmware: 2-3 sentences. Biggest blocker: …

## Findings
- [CRITICAL] / [HIGH] / [MEDIUM] / [LOW] short description — what to do.
- …

## Suggested updates to PLAN.md (proposed only, do not edit)
- …
```

## What this audit deliberately does *not* do

- **It does not edit any files.** Read-only by design.
- **It does not make scope decisions.** It surfaces options; the team
  decides at the sync meeting.
- **It does not check correctness of physics or algorithms.** Those are
  the job of `tests/` and the comparison harness, not of a status audit.
- **It does not run the GUI demo.** No `main.py`, no
  `examples/pno_demo.py` (both call `plt.show()` and block).

## Update history

- 2026-04-30 — file created during scaffolding. Intended single run is
  around 2026-06-11 (end of week 6). After that run, either delete this
  file or rename it (e.g. `AUDIT_FOR_OCT.md` for the week-16 HIL
  milestone audit) and revise the protocol for the next checkpoint.
