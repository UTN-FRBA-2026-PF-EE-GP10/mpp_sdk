# Plan 006: Fix sensing-chain documentation drift (INA226 vs INA229, 4-byte vs 12-byte frame)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6af6609..HEAD -- docs/general_information.md firmware/README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (coordinate with plan 005, which edits
  firmware/README.md too - land this before or rebase after)
- **Category**: docs
- **Planned at**: commit `6af6609`, 2026-07-06

## Why this matters

Two docs describe hardware that does not match the board or the code, and
both are exactly the docs someone doing the sensing work (plan 005) will
read first. Stale docs are worse than missing ones: they cost debugging time
against the wrong chip and the wrong protocol.

## Current state

Two confirmed drifts:

1. `docs/general_information.md:40` says the RP2040 "reads voltage and
   current (INA226 + op-amps)". The KiCad schematic
   (`hardware/untitled.kicad_sch`) contains **no INA226**: the digital power
   monitor is an **INA229** (SPI, 20-bit, datasheet
   <https://www.ti.com/lit/ds/symlink/ina229.pdf>) and the analog sense
   amplifier is an **INA281** feeding the RP2040 ADC (`ADC_Input_Curr`,
   GPIO28). There is also a MAX31865 PT100 front end for temperature.
2. `firmware/README.md`, section "Frame protocol", documents a **4-byte**
   SPI frame. The code uses **12 bytes**: `firmware/src/spi_slave_pio.rs:36`
   (`pub const FRAME_LEN: usize = 12;`) and the Pi side agrees
   (`mpp_sdk/io/spi_mcu.py:38`, `_FRAME_LEN = 12`, docstring lines 21-24
   show the 12-byte layout). The byte layout in the README table (DUTY_H,
   DUTY_L / V_H, V_L, I_H, I_L) is correct; only the length and the "4
   bytes" wording are stale.

Also check while in there (verify, then fix or leave):

- `grep -rn "INA226" docs/ README.md PLAN.md mkdocs.yml` for any other
  mention. Do NOT edit anything under `entregables/` (frozen deliverables,
  point-in-time documents) even if it says INA226.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Find all mentions | `grep -rn "INA226\|4 bytes\|4-byte" docs/ firmware/README.md README.md PLAN.md` | list to work through |
| Markdown lint | `uvx markdownlint-cli2 "docs/**/*.md" "firmware/README.md"` (or the repo's pre-commit hook) | exit 0 |
| Docs build | `uv run --group docs mkdocs build --strict` | exit 0 |

## Scope

**In scope**:

- `docs/general_information.md`
- `firmware/README.md`
- Other `docs/*.md`, `README.md`, `PLAN.md` lines surfaced by the grep, if
  clearly the same drift

**Out of scope** (do NOT touch):

- Anything under `entregables/` - delivered documents are historical record.
- `hardware/` schematics - they are the source of truth, not the drift.
- Code files; `mpp_sdk/io/spi_mcu.py`'s docstring is already correct.

## Git workflow

- Branch: `docs/sensing-chain-drift`
- Single-line conventional commit, e.g.
  `docs: correct sensing ICs (INA229/INA281) and 12-byte SPI frame`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Correct the sensing-chain description

In `docs/general_information.md:40`, replace "(INA226 + op-amps)" with a
description matching the schematic, e.g.: "(INA229 power monitor over SPI,
plus an INA281 sense amplifier into the on-chip ADC as an analog
cross-check)". Keep the sentence style of the surrounding bullet list.

**Verify**: `grep -n "INA226" docs/general_information.md` -> no matches.

### Step 2: Correct the frame-protocol section

In `firmware/README.md`, change the "Frame protocol" heading text "(4
bytes, ...)" to "(12 bytes, ...)" and extend the byte table to show bytes
0-3 as today plus "bytes 4-11: 0x00 padding", matching
`spi_slave_pio.rs:100-108` and `mpp_sdk/io/spi_mcu.py:21-24`.

**Verify**: `grep -n "4 bytes" firmware/README.md` -> no matches;
`grep -n "12" firmware/README.md` shows the updated heading.

### Step 3: Sweep remaining mentions and build the docs

Work through the grep list from "Commands"; fix only clear instances of the
same two drifts. Then run the markdown lint and `mkdocs build --strict`.

**Verify**: both commands exit 0.

## Test plan

Docs-only; the verification greps and the strict mkdocs build are the test.

## Done criteria

- [ ] No "INA226" outside `entregables/` and git history
- [ ] `firmware/README.md` frame section says 12 bytes and matches the code
- [ ] `uv run --group docs mkdocs build --strict` exit 0
- [ ] Only documentation files modified (`git status`)
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- The schematic and this plan disagree (e.g. you find an INA226 symbol
  after all) - the audit's reading of the s-expressions would be wrong;
  report before editing.
- A drifted mention appears in a file under `entregables/` only - that is
  expected; leave it and note it.

## Maintenance notes

- Plan 005 adds a "Sensing" section to `firmware/README.md` (R_shunt, CS
  mapping, mV/mA wire units); whichever lands second rebases trivially.
- When the MAX31865 driver lands, extend the same sensing description with
  the PT100 temperature path.
