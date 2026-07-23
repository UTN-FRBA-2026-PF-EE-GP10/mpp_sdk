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

MAX31865 (PT100 driver, `feat/fw-max31865`): implemented and correct, but
disabled (commented out of `main.rs`) - on-target bring-up found the bench
probe is a PT1000, incompatible with the board's fixed 400 Ohm reference
resistor. Needs a PT100 probe or a reference-resistor swap before
re-enabling; no plan file, tracked via the PR that disabled it.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Firmware: curve-tracer relay + Tracer_pwm foundation | P2 | S | - | DONE |
| 002 | Firmware: SEPIC gate PWM on GPIO15 at 100 kHz (+ duty clamp) | P1 | S-M | - | DONE (95% clamp boundary untested, pick up in 003) |
| 003 | Bench: duty sweep into a 10 Ohm load, transfer-ratio check | P1 | M (bench) | 002 flashed | TODO |
| 004 | Firmware: PIO SPI-slave frame-timeout recovery + 1 MHz speed fix | P1 | M | - | DONE |
| 005 | Stable (exponential-Euler) integrator for DynamicSimulatedSource | P1 | S | - | DONE |
| 006 | Commit firmware Cargo.locks, enforce --locked in CI | P1 | S | - | DONE |
| 007 | Characterization tests for harness/common.py | P2 | M | - | DONE |
| 008 | NoisySource cached read (idempotent read()) | P2 | S | 007 | TODO |
| 009 | Docs and tooling sweep after the merge wave | P3 | S | - | TODO |
| 010 | Firmware: read on-chip ADC (ADC_PWR/ADC_VOUT/ADC_Input_Curr) | P2 | M | - | IN PROGRESS (PWR/VOUT calibrated + on-target checked, ~9% error accepted; Input_Curr needs INA281 gain/shunt) |
| 011 | Firmware: `power_supply` mode vs `mpp_tracker` mode | P2 | M | 002, 010 | DONE |
| 012 | Docs: CCM/DCM behavior and `power_supply` mode rationale | P3 | S | 011 (mode note only; CCM/DCM part is independent) | DONE |
| 013 | Firmware: NeoPixel packet-receive heartbeat (GPIO4) | P3 | S-M | - | DONE (on-target confirmed at 200 kHz - 1 MHz caused NeoPixel-crosstalk MISO corruption, see plan file) |
| 014 | Firmware: CRC/checksum on the SPI frame | P1 | S-M | - | TODO |
| 015 | SDK: harden `SpiMcuSource` (scale defaults, teardown, read()-before-write(), tests) | P1 | S-M | - | TODO |

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
- **011 after 002 and 010** (needs the real GPIO15 gate PWM and the
  calibrated `MEAS_ADC_VOUT_MV` feedback signal). **011 has a STOP
  condition on an explicit operator decision** (does the link-lost
  watchdog still force duty to 0 in `power_supply` mode, or should the
  local regulator run standalone) - do not implement the controller before
  that is answered.
- **012's CCM/DCM section is independent** (bench data already exists);
  its `power_supply` mode section needs 011 merged first - mark that part
  BLOCKED rather than guessing if executed before 011 lands.
- **013 is DONE** (merged) - 011 and 014 no longer need to serialize
  against it, just rebase onto current `main`. It also changed the
  bench-validated SPI clock speed to **200 kHz** (down from 1 MHz - the
  actively-switching NeoPixels crosstalk the SPI1 MISO line at 1 MHz, see
  013's Progress note); any future work touching SPI speed constants
  should use 200 kHz, not the older 1 MHz figure.
- **014 has no hard dependency**, but ranks P1 (not P3 like 011/012):
  a corrupted-but-complete SPI frame is applied to the live gate today
  with zero detection - found during on-target testing, not theoretical.
  Touches `spi_slave_pio.rs`, so rebase onto current `main` (past 013)
  before starting.
- **015 has no hard dependency** and is fully parallel with everything
  else (`mpp_sdk/io/spi_mcu.py` + a new test file only, no firmware
  files touched). Ranks P1 like 014: its headline issue (default V/I
  scale factors off by ~3300x from what the firmware actually sends) is
  a confirmed, evidence-backed drift, not theoretical.

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

- `SpiMcuSource.read()` returns (0, 0) before the first `write()` - now
  tracked by plan 015 (no longer just a loose note).
- The PWM placeholder on `PIN_25` note is resolved: plan 002 (DONE)
  replaced it with the real GPIO15 gate PWM.
- `INA_OOR_Alert` (GPIO21) is wired but unused; a follow-up can configure
  DIAG_ALRT limits and wire it to a fast PWM shutdown - natural extension
  of plan 002 now that the gate is live.

## Audit trail (2026-07-22 follow-up audit)

Post-merge-wave `/improve` re-audit at commit `2aa9d35`, after plans
001-002/004-007 landed and 010 progressed. Findings that became new plans:
`SpiMcuSource`'s V/I scale-factor drift + missing tests + two smaller
correctness gaps (015, bundled - see its own file for why bundled rather
than split). Findings folded into the existing plan 009 rather than
duplicated: GPIO4's NeoPixel wiring undocumented, no firmware CI clippy
step, no root-docs pointer to the firmware README, and this index's own
stale opening framing (009's new items 9-12). One direct fix applied
immediately, no plan needed: `divider_to_actual_mv`'s (`main.rs`) u16
saturation on overflow (was silently wrapping on the `Full` ADC divider
range above ~65.5 V - currently dormant since `Low` is the active range,
but cheap enough to just fix). One stale git worktree
(`plan/009-docs-dx-sweep`, fully merged, zero unique commits) removed
directly.

### Findings considered and rejected (2026-07-22)

- A suspected torn-read race where `spi_pio_task` could read a mismatched
  `(V, I)` pair mid-update from `sensors_task` (two separate `Atomic*`
  statics, two separate stores/loads): not reachable. Both the writer's
  two stores and the reader's two loads are back-to-back with no
  `.await` between them, and this firmware runs a single cooperative
  executor on one core (confirmed: no `InterruptExecutor`, no
  `spawn_core1` anywhere, despite the `executor-interrupt` Cargo feature
  being enabled) - embassy's executor only switches tasks at yield
  points, so this specific interleaving can't happen. Not a finding.
