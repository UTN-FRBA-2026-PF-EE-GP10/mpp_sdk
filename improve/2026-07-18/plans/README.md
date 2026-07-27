# Implementation Plans - SEPIC bring-up + audit, 2026-07-18

Originally two batches, written at commit `6fc47a0`:

- **001-003**: operator-authored bring-up plans, written right after the
  INA229 driver was validated on the real board (battery on the panel
  input, V/I reading correctly over SPI0).
- **004-009**: output of the 2026-07-18 improve-skill audit (post-merge
  wave: harness consolidation, INA229 firmware, final PCB, CI hardening).
  Plan 002 was amended by the audit (duty input clamp added) rather than
  duplicated.

Plans 010-015 (through commit `92e437e`) came from later work and a
follow-up 2026-07-22 audit: on-chip ADC, `power_supply` mode, NeoPixel
packet heartbeat, and the SPI frame checksum/telemetry expansion. Finished
plans' files are removed once DONE (see the status table below for what's
left) - this index and the status table are the durable record.

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
| 008 | NoisySource cached read (idempotent read()) | P2 | S | 007 | DONE (plan file removed, see PR history) |
| 009 | Docs and tooling sweep after the merge wave | P3 | S | - | DONE (plan file removed, see PR history) |
| 010 | Firmware: read on-chip ADC (ADC_PWR/ADC_VOUT/ADC_Input_Curr) | P2 | M | - | IN PROGRESS (PWR/VOUT calibrated + on-target checked, ~9% error accepted; Input_Curr needs INA281 gain/shunt) |
| 011 | Firmware: `power_supply` mode vs `mpp_tracker` mode | P2 | M | 002, 010 | DONE (feed-forward + proportional-trim ClosedLoop confirmed on-target; MppTracker regression-checked unaffected; plan file removed, see PR history) |
| 012 | Docs: CCM/DCM behavior and `power_supply` mode rationale | P3 | S | 011 (mode note only; CCM/DCM part is independent) | DONE (plan file removed, see PR history) |
| 013 | Firmware: NeoPixel packet-receive heartbeat (GPIO4) | P3 | S-M | - | DONE (on-target confirmed at 200 kHz - 1 MHz caused NeoPixel-crosstalk MISO corruption, see plan file) |
| 014 | Firmware: CRC/checksum + Vout/Temp fields on the SPI frame | P1 | S-M | - | DONE (on-target fault injection confirmed; plan file removed, see PR #51) |
| 015 | SDK: harden `SpiMcuSource` (scale defaults, teardown, read()-before-write(), tests) | P1 | S-M | - | DONE (plan file removed, see PR #51) |
| 016 | Firmware: curve-tracer sweep engine (RP2040 port, bench-only, no Pi transport yet) | P2 | L | - | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) |
REJECTED (with one-line rationale).

## Remaining backlog

Everything above is DONE except:

- **003** (bench duty sweep, P1): needs 002 flashed on the target plus a
  lab PSU (or battery) + 10 Ohm load. Bench procedure, not a code change.
- **010** (INA281 gain/shunt, P2): IN PROGRESS, `ADC_Input_Curr` still
  uncalibrated.
- **016** (curve-tracer sweep engine, P2): no dependency; the SPI-frame
  byte-budget numbers in its "Current state" reflect 014's final,
  merged design (3 spare MISO bytes, 9 spare MOSI).

**011 is DONE** (not an open item, and not a teammate hand-off - it landed
in this session, merged as PR #50: feed-forward + proportional-trim
`ClosedLoop`, `MppTracker` regression-checked unaffected). Any further
`power_supply`-mode work beyond what plan 011 scoped would be a new plan,
not a reopening of 011.

Execution-order/parallelization detail for the now-DONE plans (001-009,
011-015) is historical - see git history on this file rather than
maintaining it here.

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
correctness gaps (015, bundled rather than split - now DONE, plan file
removed, see PR #51). Findings folded into the existing plan 009 rather than
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
