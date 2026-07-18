# Implementation Plans - SEPIC bring-up, 2026-07-18

Operator-authored bring-up plans (not an improve-skill audit). Written at
commit `6fc47a0`, right after the INA229 driver was validated on the real
board (battery on the panel input, V/I reading correctly over SPI0).

Context: the 2026-07-06 audit is fully executed - all 8 plans DONE, its
folder removed in this same PR (history: `improve/2026-07-06/` before this
commit; the "findings considered and rejected" list lives there).

In flight, no plan file needed: the MAX31865 PT100 driver is already
implemented on local branch `feat/fw-max31865` (pending on-target bring-up
and PR).

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Firmware: curve-tracer relay + Tracer_pwm foundation | P2 | S | - | TODO |
| 002 | Firmware: SEPIC gate PWM on GPIO15 at 100 kHz | P1 | S-M | - | TODO |
| 003 | Bench: duty sweep into a 10 Ohm load, transfer-ratio check | P1 | M (bench) | 002 flashed | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason).

## Dependency notes

- 001 and 002 are independent firmware changes; they can share one branch
  and PR or land separately.
- 003 is a bench procedure, not a code change: it needs 002 flashed on the
  target and a lab PSU (or battery) + 10 Ohm load. 001 is NOT required for
  003 (the relay stays off; its curve-tracer function comes later).
- The MAX31865 branch touches the same `main.rs` region as 001/002
  (peripheral setup) - land it first or rebase, either order is trivial.

## Carried context (still-live notes from the closed 2026-07-06 audit)

- `SpiMcuSource.read()` returns (0, 0) before the first `write()` -
  revisit during HIL bring-up.
- The PWM placeholder on `PIN_25` updated every 100 ms is exactly what
  plan 002 here replaces.
- `INA_OOR_Alert` (GPIO21) is wired but unused; a follow-up can configure
  DIAG_ALRT limits and wire it to a fast PWM shutdown - natural extension
  of plan 002 once the gate is live.
