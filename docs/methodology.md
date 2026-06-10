# Comparison methodology

How the harness measures MPPT performance, what each number means, and how
the simulation results will be reproduced on PLECS and on the bench. For
the system overview see `general_information.md`; for design decisions,
`rationale.md`.

## One idea behind every metric

At every instant the panel has a best possible power, $P_\text{mpp}$: the
global maximum of the P-V curve for the current irradiance and
temperature. Every metric compares what the controller actually captured
against that ideal. The reference comes from the same panel model the
simulation runs on (`TabulatedPanel.mpp()`), so the simulated world and
the grading curve are identical by construction.

## Three harnesses, three questions

| Harness | Question | Replicable on hardware? |
| --- | --- | --- |
| `compare_cyclic.py` | Which algorithm is better under realistic, changing shading? | No, and it does not need to be (sim-only ranking) |
| `compare_bank.py` | Does the simulation predict reality? | Yes: five simple scenarios, one shade cloth |
| `compare_noise.py` | How fast does each algorithm degrade with measurement noise? | Indirectly (the bench has a fixed noise floor) |

The split matters: a rich, chaotic, seeded schedule is ideal for *ranking*
but impossible to reproduce with a real sun, while bench scenarios must be
simple. Asking one experiment to do both jobs would do both badly.

`compare_static.py`, `compare_dynamic.py` and `animate.py` predate the
methodology and remain as smoke tests and demos.

## The metrics

- **eta energy** $= \sum_k P_k \,/\, \sum_k P_{\text{mpp},k}$: captured
  energy over ideally-available energy across the whole run, with a
  time-varying reference (`metrics.energy_efficiency`). The headline
  energy bill. It is *energy-weighted*: deep-shade segments offer little
  energy, so failing them dents this number surprisingly little. Always
  read it together with the trap columns.
- **success / trapped**: how many held conditions (plateaus) ended within
  5 % of $P_\text{mpp}$, and for the trapped ones, the settled fraction of
  available power (mean and worst). This is the honest pain number: "when
  trapped, the controller delivers X % of what the panel could give".
- **re-acquisition**: time from a condition change until the power is back
  inside the 5 % band and stays there. Local trackers re-acquire in
  ~10 ms or never (trapped); global trackers always re-acquire but pay
  their search time, bounded by the rescan period.
- Building blocks in `mpp_sdk.metrics`: `tracking_efficiency`,
  `final_efficiency`, `settling_time`, `steady_state_ripple`,
  `overshoot`, `trap_depth`. Each harness prints a plain-language guide
  before its table.

## Why global trackers need a trigger policy

A global search (full duty sweep, or a PSO pass) physically drives the
converter across its range: exploration costs energy, so it cannot run
continuously. After the search, a local P&O holds the found peak. The open
question is *when to search again*, and it moves the results more than the
choice of search itself. Two mechanisms, both on the controller side and
both fed only by $(V, I)$:

1. **Step detector** (`PowerChangeDetector`, on by default): restart when
   $|\Delta P|/P > 20\,\%$ for 3 consecutive control steps, with the
   reference following the power while it stays in band. It arms only once
   the power is stable after a search, so the converter's own recovery
   transient (the input capacitor recharging, panel-current-limited at low
   irradiance) cannot cause a restart loop. It fires on *steps* only.
2. **Periodic backstop** (`rescan_period`): re-search every $N$ tracking
   steps unconditionally. It exists for the step detector's blind spot:
   changes that reshape the curve without moving the tracked power, which
   includes every *slow ramp* into partial shading. Its cost is one search
   per period (a few percent of energy at 1 s); its benefit is bounding
   the worst-case trapped time to the period.

Measured on the cyclic schedule: local trackers trap in roughly half the
shaded plateaus at 44-67 % of available power; the configured global
trackers cut traps to a handful at the price of up to ~1 s re-acquisition
when only the backstop can free them.

## Measurement noise

Real sense chains are noisy, and clean-sim numbers flatter the simple
methods. `NoisySource` adds seeded Gaussian noise to the $(V, I)$ samples
the controller sees (the plant stays clean; grading uses true power),
specified as a fraction of the hardware full scale (40 V / 1 A).

The theory of the observed cliff: fixed-step P&O decides direction from
the *sign* of the power change across a duty perturbation. Near the MPP
that change is tiny, so once per-sample noise exceeds it the decision is a
coin flip and the tracker random-walks away (this is the classical
step-size design constraint, Femia et al. 2005). On this rig the cliff
sits between 0.25 % and 0.5 % of full scale; global searches keep a ~60 %
floor at levels that reduce P&O to ~19 %, because each sweep yanks the
operating point back near the peak.

## Sim-to-real: the three-layer comparison

Closed-loop waveforms from different environments are never compared
directly; the claim is split so a disagreement points at the broken layer:

1. **Plant vs plant** (validates `DynamicSimulatedSource` against the
   PLECS switched model): replay the *same recorded duty sequence*
   open-loop into both and compare $V(t), I(t)$. The panel enters PLECS
   as a lookup table exported by `scripts/export_iv_plecs.py`, so both
   simulators share the same curve by construction.
2. **Controller vs controller** (validates a port, PLECS C-Script or the
   RP2040 firmware, against the Python reference): replay recorded
   $(V, I)$ traces through both and compare the emitted duty sequences
   step by step. Deterministic algorithms only.
3. **Closed loop**: run the test-case bank in each environment and compare
   the metrics tables within documented tolerances.

`compare_bank.py` dumps a $(t, V, I, D)$ CSV per run precisely to feed
layers 1 and 2. On the bench, the scenarios map to one shade cloth of
~30 % transmission (cover on, cover off, steady shade) plus the
controller's configured start duty for the Voc-side trap case; the ground
truth $P_\text{mpp}$ comes from a calibration duty sweep with the
condition held - the rig is its own instrument.

## The numbers the simulation assumes

| Quantity | Value | Where |
| --- | --- | --- |
| Control loop | 1 kHz (1 ms per step) | `panel_config.CONTROL_PERIOD_MS`, RP2040 target |
| Input capacitance | 100 uF | `DynamicSimulatedSource` default |
| Load | 10 Ohm resistive | harness scripts |
| Hardware full scale | 40 V / 1 A | `panel_config.V_IN_MAX`, `I_MAX` (PCB limits) |
| Panel string | 2x Hissuma PSF10MONO in series | `panel_config.shaded_string` |
| Shade cloth | ~30 % transmission | `compare_bank.CLOTH_TRANSMISSION` |

## Reproducibility

Every stochastic element is seeded: the cyclic schedule, the PSO swarm,
the noise stream. Re-running any harness reproduces its numbers exactly;
changing a seed is a deliberate, visible act. This is a PLAN-level rule
because every figure in the paper must be regenerable from a command.
