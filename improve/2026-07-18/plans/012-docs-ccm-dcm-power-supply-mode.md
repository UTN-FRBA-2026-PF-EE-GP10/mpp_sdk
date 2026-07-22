# Plan 012: Docs - CCM/DCM behavior and `power_supply` mode

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.

## Why

Two related pieces of real, bench-confirmed converter behavior have no
home in the project's docs yet:

1. **Continuous vs discontinuous conduction mode (CCM/DCM)**: during plan
   002's bring-up, the same commanded duty (D=0.5, `Vin=3.3V`) produced
   wildly different `Vout` depending on load alone - ~7 V open-circuit,
   ~6 V into 10 kOhm, ~3.3 V (matching the ideal `D/(1-D)` ratio) into
   10 Ohm. This is textbook CCM/DCM behavior, not a bug, but nothing in
   `docs/` explains it - a future reader (or the thesis writeup) hitting
   the same surprise has no reference to point at.
2. **`power_supply` mode** (plan 011, firmware-local closed-loop Vout
   regulation for bench characterization, vs `mpp_tracker` mode's
   Pi-driven open-loop duty): plan 011 scopes the *practical* bench-usage
   docs into `firmware/pipico_board/README.md`, but the project-level
   *why this mode exists* belongs in the higher-level SDK docs alongside
   the other architecture rationale, not just the firmware operator
   manual.

## Current state

- `docs/rationale.md`'s "Why SEPIC" section (currently just: SEPIC chosen
  because panel MPP voltage can sit above or below load voltage without a
  topology change) has no mention of CCM/DCM.
- `docs/general_information.md`'s "The physical system" section describes
  the SEPIC/RP2040/Pi block diagram but not converter operating regimes.
- Neither file mentions firmware operating modes at all - that concept
  does not exist yet (it is plan 011's job to build it).

## Scope

**In**:

- `docs/rationale.md` - add a CCM/DCM subsection under or near "Why
  SEPIC", using the plan 002 bench numbers above as the concrete
  illustration (real measured data beats a generic textbook explanation).
- `docs/rationale.md` and/or `docs/general_information.md` - a short
  "Firmware operating modes" note explaining `mpp_tracker` vs
  `power_supply` mode at the *why* level (bench characterization utility
  vs the real MPPT path), cross-referencing `firmware/pipico_board/README.md`
  for the operational details (setpoint const, watchdog behavior, etc.)
  rather than duplicating them.

**Out**: the firmware README's own mode documentation (plan 011's scope,
already covers the operational/bench-usage details); any new
diagrams/plots (text-only, matching the existing docs' style) unless
trivial.

## Dependency

- The **CCM/DCM subsection has no dependency** - the bench data already
  exists (this plan's "Why" section above), write it now.
- The **`power_supply` mode note depends on plan 011 landing** (the mode,
  its setpoint const, and the operator's watchdog-interaction decision
  must exist before this plan can accurately describe them). If plan 011
  is not yet merged when this plan is executed, do the CCM/DCM part now
  and leave the mode note as a follow-up (BLOCKED, not skipped) rather
  than guessing at plan 011's eventual design.

## Steps

1. Write the CCM/DCM subsection in `docs/rationale.md`, using the plan
   002 bench numbers (D=0.5, `Vin=3.3V`: ~7 V open-circuit / ~6 V at
   10 kOhm / ~3.3 V at 10 Ohm) as the illustration. Keep it short - a
   paragraph or two, not a controls-theory treatise; link to a real
   reference if one is already cited elsewhere in the docs for SEPIC
   theory, otherwise state the qualitative mechanism (light load can't
   keep the inductor current from hitting zero each switching cycle,
   which breaks the `D/(1-D)` derivation's assumption) without deriving
   the DCM transfer function from scratch.
   Verify: reads standalone (a reader unfamiliar with this session's bench
   session understands why the numbers differ) - self-review only, no
   build step for prose.
2. If plan 011 has merged: add the "Firmware operating modes" note,
   cross-referencing the firmware README rather than restating its
   detail. If not yet merged: skip this step and mark it BLOCKED on 011 in
   the done criteria below, do not guess at the design.
3. Proofread both additions against this repo's doc conventions (plain
   language, no em dashes, matches `AGENTS.md`'s general tone) before
   finishing.

## Done criteria

- [ ] CCM/DCM subsection added to `docs/rationale.md`, grounded in the
      real plan 002 bench numbers
- [ ] "Firmware operating modes" note added (or explicitly marked BLOCKED
      on plan 011 if 011 hasn't landed yet)
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- Plan 011's actual design (mode names, setpoint const name, chosen
  watchdog behavior) differs from what's assumed here once it lands -
  re-read plan 011's final state before writing the mode note, do not
  write from memory of this plan's own guess.

## Maintenance notes

- If plan 003 (bench duty sweep) or a future bench-voltage-sweep variant
  (noted as a follow-up in plan 011) produces more CCM/DCM data points,
  this is the natural place to fold them in as a small table rather than
  prose-only.
