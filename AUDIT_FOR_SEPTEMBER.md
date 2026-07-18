# AUDIT_FOR_SEPTEMBER.md

A self-contained audit prompt for an LLM agent. Designed to be run **once,
around 2026-09-17** - that is, end of week 20 of the 30-week schedule
defined in `PLAN.md` *Team allocation, schedule, and scope*.

The audit sits four weeks *after* the **HIL-working-by-end-of-week-16**
hard milestone on purpose: hardware assembly started late June / mid July
(see PLAN, milestone 1 status), so by mid September HIL must be done and
the algorithm port (Phase 5b, weeks 17-20 "Algo push") must have begun.
If HIL is still not running in September, *deployed mode* (the thesis's
headline deliverable) is no longer at risk but effectively lost, and the
paper falls back to a simulation-only contribution - the audit's job is
to force that call rather than let it drift.

(The week-6 predecessor of this file, `AUDIT_FOR_JUNE.md`, ran on
2026-06-10: verdict AT RISK on missing fab evidence, resolved the same
day - PCB sent to the manufacturer, all components purchased.)

## How to run

Hand this file to an agent (Claude Code, Cursor, etc.) with a prompt like:

> "Read `AUDIT_FOR_SEPTEMBER.md` and follow the **Audit protocol** section.
> Produce the report described in **Output format**. Read-only - do not
> modify any files in the repo."

The agent should produce a single markdown report; the maintainer reads
it before the next weekly sync and decides what to act on.

## Calibrate the schedule before auditing

Before running the checks below, determine *which week we are in*:

1. The schedule start is **2026-04-30** (week 1 starts there); week 16
   ends **2026-08-20** and week 20 ends **2026-09-17**.
2. Run `git log --reverse --format='%h %ai' | head -1` as a sanity check.
3. If the audit is being run before week 19 or after week 22, say so
   explicitly in the report and adjust expectations.

The protocol below is calibrated for **end of week 20**: the HIL
milestone (week 16) must already be met, and the port must be underway.

## Audit protocol

For each section, gather the listed evidence and answer the question. If
evidence is missing, **say so explicitly** rather than guess. Use
`Read` / `Bash` / `Grep` / `Glob` as needed; do not edit anything.

### 1. HIL milestone (highest priority)

**Question: is Phase 5a done - the full loop (panel -> SEPIC board ->
RP2040 -> SPI -> Pi -> Python algorithm -> duty back) running end to end
on the bench?**

Evidence to gather:

- `mpp_sdk/io/spi_mcu.py`: a working `SpiMcuSource(SignalSource)`, not a
  skeleton (look for the watchdog, the command set, calibration use).
- Firmware HIL mode in `firmware/pipico_board/src/`: ADC sense, hardware PWM, SPI
  slave command set (set duty, read sample, read calibration, soft-stop
  on watchdog timeout).
- Recorded (V, I, D) traces from the real rig (under `data/`), or
  harness output comparing sim vs HIL numbers.
- Commit history: `git log --oneline --since='2026-06-10' -- firmware/
  mpp_sdk/io/ hardware/`.

Severity table:

| Found                                              | Flag     |
| -------------------------------------------------- | -------- |
| No board-level firmware work since June            | CRITICAL |
| Board alive but no closed loop (ADC/PWM only)      | HIGH     |
| Closed loop runs, no calibration / no traces       | MEDIUM   |
| HIL end-to-end with recorded traces                | OK       |

### 2. Hardware bringup

**Question: is the board assembled, calibrated, and is the sense path
validated against a scope?**

Evidence:

- Assembly / bringup notes (a bringup log, calibration constants under
  `data/hardware/`, or progress docs under `entregables/`).
- ADC scale/offset and INA226 calibration recorded anywhere.
- Per the June status: boards were expected assembled and checked by
  mid-July. Anything contradicting that needs a date.

Severity:

| Found                                      | Flag     |
| ------------------------------------------ | -------- |
| Board not assembled                        | CRITICAL |
| Assembled, not calibrated                  | HIGH     |
| Calibrated, sense path not scope-validated | MEDIUM   |
| Calibrated and validated                   | OK       |

### 3. SPI protocol documented

**Question: is the SPI frame format / command set written down
(`data/hardware/spi_protocol.md` or equivalent), matching both the
firmware and `SpiMcuSource`?**

Working code existed in June with no document. Flag **HIGH** if still
undocumented: the algorithm port will harden the accidental format.

### 4. Algorithm port (the week-16 decision, plus week 17-20 progress)

**Question: was the port candidate picked against the explicit budget
(<= 16 KB flash, <= 4 KB RAM, <= 1 ms per step on the RP2040), and has
the port to Rust firmware begun?**

Per *Top risks* in `PLAN.md` the candidate decision was due **by week
16**; the "Algo push" block (weeks 17-20) begins the port itself.

Evidence:

- Implementation-cost metrics in the harness (state size, per-step
  compute) - a TODO item as of June.
- A documented candidate choice (PLAN, TODO, or `entregables/`).
- Port code in `firmware/pipico_board/src/` beyond the SPI proxy, and/or
  cross-validation against the Python reference on recorded traces.
- If the own model-informed candidate-scan algorithm shipped, whether it
  is in the comparison.

Flag **CRITICAL** if no candidate exists by week 20 (it was due week
16); **HIGH** if the candidate exists but no port work has started.

### 5. SDK progress (Person A track)

**Question: did the simulation track deliver the items queued in June?**

Expected by week 16 (all were in `TODO.md` *Next* / *Backlog* in June;
TODO.md has since been retired - the open backlog now lives in `PLAN.md`
*Roadmap*, the findings in `docs/`):

- `NoisySource` + noise-robustness numbers.
- `rescan_period` sweep (the trigger-policy figure).
- Seed statistics for PSO (mean +/- std).
- Sim + HIL numbers side by side in the harness (block 13-16
  deliverable).

Severity: all four present OK; missing sim+HIL numbers MEDIUM (depends
on hardware); missing the pure-sim items HIGH (nothing blocked them).

### 6. Out-of-scope creep

Grep code, commit messages and comments for: `two-diode`,
`sliding mode`, `MPC`, `model predictive`, `reinforcement`, ` RL `,
`synchronous boost`, `multi-string`, `Wi-Fi telemetry`, `YAML fixture`.

Substantive code on these: MEDIUM. Mentions in TODOs / comments: LOW.
The recommendation is always to pull the contributor back to in-scope
work; out-of-scope is a budget decision, not a quality decision.

### 7. Top-level health checks

Run these and include the (trimmed) output in the report:

```bash
uv sync 2>&1 | tail -5
uv run python -c "import mpp_sdk; print(mpp_sdk.__version__)"
uv run pytest --tb=short -q 2>&1 | tail -5
cd firmware && cargo build --release 2>&1 | tail -5
```

Do **not** run `uv run main.py` or the `examples/` demos - they open GUI
windows. The harness scripts (`harness/compare_*.py`) are headless and
safe to run.

Severity: build / import / test failures HIGH; everything green OK.

## Output format

Produce one markdown report. Keep it under ~500 words. Structure:

```text
# Mid-September audit - week N (YYYY-MM-DD)

## Verdict
ON TRACK | AT RISK | OFF TRACK - one sentence justifying it.

## Milestone status
| Milestone                  | Week  | On track? | Notes |
| ---------------------------|-------|-----------|-------|
| HIL end-to-end (Phase 5a)  |  16   |  ...      |  ...  |
| Port candidate picked      |  16   |  ...      |  ...  |
| Port begun (Algo push)     | 17-20 |  ...      |  ...  |
| Deployed mode (Phase 5b)   |  24   |  ...      |  ...  |

## Per-track status
A - SDK & integration: 2-3 sentences. Biggest blocker: ...
B - hardware: 2-3 sentences. Biggest blocker: ...
C - firmware: 2-3 sentences. Biggest blocker: ...

## Findings
- [CRITICAL] / [HIGH] / [MEDIUM] / [LOW] short description - what to do.
- ...

## Suggested updates to PLAN.md (proposed only, do not edit)
- ...
```

## What this audit deliberately does *not* do

- **It does not edit any files.** Read-only by design.
- **It does not make scope decisions.** It surfaces options; the team
  decides at the sync meeting.
- **It does not check correctness of physics or algorithms.** Those are
  the job of `tests/` and the comparison harness, not of a status audit.
- **It does not run the GUI demos.** No `main.py`, no `examples/`.

## Update history

- 2026-04-30 - created as `AUDIT_FOR_JUNE.md` during scaffolding for the
  week-6 PCB-to-fab checkpoint.
- 2026-06-10 - week-6 audit executed. Verdict AT RISK (no fab evidence in
  repo); resolved same day: PCB at manufacturer, components bought,
  assembly + checks ~2 weeks, board-level firmware from late June / mid
  July. File renamed and protocol revised for the September checkpoint
  (week 20: HIL must be done, port underway), per the maintainer's call.
