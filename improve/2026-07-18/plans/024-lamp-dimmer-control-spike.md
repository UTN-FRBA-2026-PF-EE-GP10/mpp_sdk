# Plan 024: Microcontroller-driven lamp dimmer - design spike

> **Executor instructions**: This is a **design spike**, not an
> implementation plan. Its deliverable is a written design + a bench
> feasibility check, ending in a go/no-go the operator decides on. Do not
> build the final firmware path from this document; a follow-up
> implementation plan gets written once the questions below are answered.
> If a STOP condition fires, stop and report.
>
> **Drift check**: not applicable - no existing code is in scope.

## Status

- **Priority**: P3 (operator flagged it as "a month or so" out)
- **Effort**: M (spike), L (implementation, not yet planned)
- **Risk**: HIGH - **mains voltage** is in scope for most dimmer options.
  See "Safety" before any hardware work.
- **Depends on**: nothing in software. Depends on hardware decisions that
  have not been made.
- **Category**: direction / research
- **Planned at**: commit `f837fc2`, 2026-08-26

## Why this matters

The measurement campaign wants curves across a range of illumination, not
just "lamp on". Today irradiance is varied by physically moving a lamp or
tilting a panel, which is neither repeatable nor recordable - two curves
captured a day apart are not comparable because nothing pins down how
bright it was.

A microcontroller-controlled dimmer makes illumination a *swept variable*:
capture the same panel configuration at N brightness levels, and the
resulting family of curves is what a real day's irradiance ramp looks
like. That is what turns plan 022's replay from "here is one curve" into
"here is how this algorithm behaves as conditions change" - which is the
actual thesis question.

It also matters for partial shading: with two panels and a controllable
source, the shaded/unshaded ratio becomes a dial rather than a guess.

## Safety

**Read this first.** Most lamp-dimming approaches involve mains voltage.
This project's board is a low-voltage DC design and nothing in it is rated
for mains. Consequences that must shape the design:

- No mains wiring on or near the existing PCB, and no mains-referenced
  signal sharing a ground with the Pico or the Pi.
- Any mains-side control needs proper isolation (opto-isolated triac
  module, or a commercial dimmer with an isolated control input).
- A low-voltage DC lamp (see Option A) sidesteps the entire category and
  is strongly preferred for that reason alone.

If the chosen option involves mains, that is an operator decision made
with full knowledge of the risk, and the implementation plan must
document the isolation scheme explicitly. **Do not improvise mains
wiring as part of executing a plan.**

## Questions this spike must answer

1. **What is the light source?** The answer drives everything else.
   Present bench setup uses a lamp of unspecified type - identify it,
   including whether it is mains or DC, and its power.
2. **Is its output dimmable in a way a panel cares about?** Many LED
   lamps flicker heavily when dimmed (PWM at a few hundred Hz). A PV panel
   plus the tracer's ~250 ms settle averages that, but the *sweep* also
   averages 5 INA229 samples per point - confirm the interaction produces
   stable readings rather than noise. This is the single most likely
   reason a given lamp is unsuitable.
3. **What is the control interface?** See options below.
4. **How is brightness recorded?** A commanded dimmer level is not
   irradiance. Options: record the raw command as an opaque level (honest
   but not physical), or add a reference sensor (a small PV cell or a
   photodiode - note the repo already has an `esp32c3-bpw34` sensor
   experiment worth reviewing). Plan 021's schema has no irradiance field;
   adding one is a `schema` bump.
5. **Does the RP2040 drive it, or the Pi?** The board's SPI protocol and
   spare GPIO are a natural fit, but a USB-serial dimmer hung off the Pi
   avoids touching the firmware at all.

## Options to evaluate

### Option A: low-voltage DC lamp, driven by the RP2040 (preferred)

A 12/24 V LED array driven through a MOSFET from a spare Pico PWM channel.

- No mains anywhere. Same voltage domain as the rest of the bench.
- Reuses the board's existing idiom - the curve tracer already does
  RC-filtered PWM into a linear stage (see `TRACER_PWM_MAX`'s doc
  comment), so the pattern and its pitfalls are already understood here.
- Needs: a suitable lamp, a driver MOSFET, and a free PWM-capable GPIO.
  **Check GPIO availability against the README's pin table before
  assuming one is free** - GPIO0/2/3/4/10-15/26-28 are already assigned.
- Dimming an LED by PWM changes its spectrum little but does flicker;
  a high PWM frequency (tens of kHz) plus the sweep's settle time should
  make that invisible to the panel. Verify, do not assume.

### Option B: mains dimmer via an isolated control module

An off-the-shelf opto-isolated AC dimmer module driven by the Pico.

- Works with an existing incandescent/halogen lamp, which has a smoother
  spectrum and no flicker concerns at the panel's timescale.
- Brings mains onto the bench under microcontroller control. Requires the
  isolation discipline in "Safety" and, realistically, a separate enclosure.
- Phase-cut dimming interacts badly with many LED lamps; with
  incandescent it is well behaved.

### Option C: Pi-side USB/serial dimmer, firmware untouched

A commercial dimmer with a serial or USB interface, commanded by the Pi.

- Zero firmware risk, and no new SPI protocol surface - a real advantage
  given how much of this session went into that protocol.
- Weakest coupling to the sweep: the Pi must sequence "set brightness →
  wait for it to settle → trigger sweep → save", which is exactly what
  the capture script would do anyway.
- Availability and cost unknown; this is a purchasing question.

**Initial recommendation**: Option A if a suitable DC lamp is available,
Option C otherwise. Option B only if an existing mains lamp must be used
and proper isolation is in place.

## Deliverables

1. A written comparison of the three options against the bench's actual
   lamp and available GPIO, with a recommendation - appended to this file
   under an "Findings" heading.
2. A bench measurement answering question 2: capture the same curve at
   two brightness levels with whatever manual dimming is possible today,
   and confirm the tracer's readings are stable (not noisy) at reduced
   illumination. **This is doable now with no new hardware** and is the
   highest-value part of the spike - if low-light sweeps are noisy, that
   constrains every option.
3. A go/no-go, and if go, a follow-up implementation plan (025) covering:
   the chosen interface, the `schema` bump for recording brightness, the
   capture-sequencing script, and the safety/isolation scheme if
   applicable.

## Steps

### Step 1: inventory

Identify the bench lamp (type, mains or DC, wattage) and confirm which
Pico GPIOs are genuinely free, cross-checked against
`firmware/pipico_board/README.md`'s pin table and the schematic. Record
both in the Findings section.

**Verify**: findings written; the free-GPIO claim cites the pin table.

### Step 2: low-light stability check (no new hardware)

With the existing lamp, capture curves at two or three manually-set
distances. For each, confirm: auto-range finds a sensible knee, the 20
points form a smooth curve, and repeating the same setup twice gives
closely matching curves.

**Verify**: curves saved via plan 021 (if landed) or the defmt log
captured, with the repeatability observation written down.

### Step 3: option comparison + recommendation

Write the comparison and recommendation into Findings.

### Step 4: go/no-go

Present to the operator. On "go", write plan 025.

## STOP conditions

- **Any mains wiring work.** Stop and get explicit operator sign-off with
  the isolation scheme agreed in advance. This is not a judgement call to
  make mid-execution.
- Step 2 shows sweeps are unstable or unrepeatable at low illumination -
  that is a measurement-chain problem (settle time, averaging, sensor
  resolution near zero) and must be understood before adding a dimmer,
  since a dimmer's whole purpose is producing low-light conditions.
- No free PWM-capable GPIO exists for Option A, making it moot.
- The spike starts turning into an implementation - stop and write plan
  025 instead.

## Maintenance notes

- Recording brightness needs a plan 021 `schema` bump; design it once,
  with a decision on commanded-level vs measured-irradiance, rather than
  bolting on a field per option.
- The `esp32c3-bpw34` crate in this repo is a standalone photodiode sensor
  experiment - relevant prior art if question 4 lands on a reference
  sensor, and worth reading before designing one from scratch.
- If Option C wins, none of this touches firmware, and the capture
  sequencing belongs next to plan 021's save path rather than in
  `mpp_sdk/`.
