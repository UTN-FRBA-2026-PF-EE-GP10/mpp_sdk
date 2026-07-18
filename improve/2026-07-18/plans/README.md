# Implementation Plans - SEPIC bring-up + audit, 2026-07-18

Two batches, one index, written at commit `6fc47a0`:

- **001-003**: operator-authored bring-up plans, written right after the
  INA229 driver was validated on the real board (battery on the panel
  input, V/I reading correctly over SPI0).
- **004-009**: output of the 2026-07-18 improve-skill audit (post-merge
  wave: harness consolidation, INA229 firmware, final PCB, CI hardening).
  Plan 002 was amended by the audit (duty input clamp added) rather than
  duplicated.

Context: the 2026-07-06 audit is fully executed - all 8 plans DONE, its
folder removed (history: `improve/2026-07-06/` in git; its "findings
considered and rejected" list lives there).

In flight, no plan file needed: the MAX31865 PT100 driver is implemented
on local branch `feat/fw-max31865` (pending two small audit fixes - 10 Hz
error-log flood on probe fault, sign-dropped print for -1 < T < 0 degC -
then on-target bring-up and PR).

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Firmware: curve-tracer relay + Tracer_pwm foundation | P2 | S | - | TODO |
| 002 | Firmware: SEPIC gate PWM on GPIO15 at 100 kHz (+ duty clamp) | P1 | S-M | - | TODO |
| 003 | Bench: duty sweep into a 10 Ohm load, transfer-ratio check | P1 | M (bench) | 002 flashed | TODO |
| 004 | Firmware: PIO SPI-slave per-frame resync + short-frame recovery | P1 | M | - | TODO |
| 005 | Stable (exponential-Euler) integrator for DynamicSimulatedSource | P1 | S | - | TODO |
| 006 | Commit firmware Cargo.locks, enforce --locked in CI | P1 | S | - | DONE |
| 007 | Characterization tests for harness/common.py | P2 | M | - | TODO |
| 008 | NoisySource cached read (idempotent read()) | P2 | S | 007 | TODO |
| 009 | Docs and tooling sweep after the merge wave | P3 | S | - | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) |
REJECTED (with one-line rationale).

## Parallelization map

Which plans can run at the same time (separate worktrees/branches, one PR
each) without stepping on each other:

**Fully parallel with everything** (disjoint files):

- **005** (`mpp_sdk/io/dynamic.py` + `tests/test_sources.py`)
- **006** (firmware `.gitignore`s + lockfiles + `firmware.yml`)
- **007** (new `tests/test_harness_common.py` only)
- **009** (root README, new hardware/data READMEs, `compare_cyclic`
  docstring, `examples/pno_demo.py`, `pyproject.toml`, two workflows)

**Firmware `main.rs` chain - serialize these** (all touch
`firmware/pipico_board/src/main.rs`; run one at a time or rebase each on
the last):

1. `feat/fw-max31865` branch (already written, lands first)
2. **001** (relay/tracer pin init)
3. **002** (gate PWM + clamp)

**004** touches only `spi_slave_pio.rs` - parallel with the `main.rs`
chain and everything else (tiny rebase risk only if 002's clamp lands in
the same week; the clamp is in `main.rs`, so no real overlap).

**Strictly ordered**:

- **007 before 008** (008's safety net is 007's tests).
- **003 after 002 is flashed** (bench procedure; 004 strongly recommended
  first too - a desyncing link during a live-power sweep is exactly the
  failure 004 removes).

Suggested waves:

- Wave 1 (parallel): 004, 005, 006, 007, 009 + the max31865 branch PR
- Wave 2 (parallel): 001+002 (one firmware branch is fine), 008
- Wave 3 (bench): 003

## Dependency notes

- 001 and 002 are independent changes but share `main.rs`; one branch/PR
  for both is acceptable.
- 003 is a bench procedure, not a code change: it needs 002 flashed on the
  target and a lab PSU (or battery) + 10 Ohm load. 001 is NOT required for
  003 (the relay stays off; its curve-tracer function comes later).
- 008 must not land before 007: it changes the noise-draw timing, and
  007's `test_run_schedule_noise_isolation` is the tripwire proving the
  change is behavior-preserving for the plant.
- 004's fault-injection step needs the Pi + probe; its code step is
  hardware-free.

## Audit trail (2026-07-18 audit)

Findings that became plans: PIO resync (004), Euler instability (005),
missing lockfiles (006), untested common.py (007), NoisySource read
contract (008), docs/DX drift bundle (009), unclamped duty (amended into
002). Full evidence lives in the session that produced this index.

### Findings considered and rejected

- INA229 VBUS sign-extension "bug": the datasheet defines VBUS as
  two's-complement; sign-extend + clamp-negative-to-0 is correct, and bit
  19 would mean >100 V on a 40 V-max design. By design.
- `hardware/untitled.kicad_sch` "stray file": it is the live
  AnalogConverters sensing sheet with a bad filename; renaming requires a
  KiCad project edit for zero functional gain. Documented in plan 009's
  hardware/README.md instead.
- Numpy per-call overhead in the dynamic-source substep loop and
  PvString table-build vectorization: real but low leverage; revisit only
  if harness iteration time becomes a bottleneck (005 reduces the
  pressure by making fewer substeps viable).
- Type-only `isinstance` assertions in algorithm tests: harmless filler,
  not worth a plan.
- `scripts/export_iv_plecs.py` output-format pinning: watch-item until the
  PLECS comparison actually consumes it.
- esp32c3-bpw34 crate has no CI: deliberate for now - it is a standalone
  sensor experiment; 006 commits its lockfile, and a fmt-only CI leg can
  ride along whenever the crate becomes load-bearing.

## Carried context (still-live notes from the closed 2026-07-06 audit)

- `SpiMcuSource.read()` returns (0, 0) before the first `write()` -
  revisit during HIL bring-up.
- The PWM placeholder on `PIN_25` updated every 100 ms is exactly what
  plan 002 replaces.
- `INA_OOR_Alert` (GPIO21) is wired but unused; a follow-up can configure
  DIAG_ALRT limits and wire it to a fast PWM shutdown - natural extension
  of plan 002 once the gate is live.
