# PLAN.md

Living planning document for **mpp-sdk**, the SDK supporting an Electronics
Engineering thesis on photovoltaic Maximum Power Point Tracking. This file
covers the roadmap, the verification expectations, the contributor
liability statement, and the LLM-usage policy.

## Context

- **Academic setting:** Electronics Engineering Thesis. Design,
  comparison, and validation of MPPT algorithms in simulation and on a
  hardware rig, culminating in a small algorithm deployed on a
  commodity microcontroller.
- **Deliverables:**
  1. The `mpp-sdk` Python library (this repository).
  2. A written paper / thesis describing methodology, comparisons, and
     conclusions.
  3. A reproducible hardware demonstrator: Raspberry Pi 5 + a small
     intermediary MCU (Raspberry Pi Pico / RP2040) over SPI + a
     **SEPIC** power stage (chosen so panel `V_mpp` may sit on either
     side of the load voltage) + small PV panel.
  4. **An MCU-deployable algorithm**: a controller that has been
     validated against the framework's comparison harness *and* ported
     to MCU firmware, with code-size / RAM / latency budgets reported
     against classical baselines.
- **Non-goals:** production-grade MPPT firmware, support for industrial
  inverter hardware, or competing with general-purpose libraries such
  as `pvlib`.

## Team allocation, schedule, and scope

This section sizes the work against the real team and timetable. Numbers
here are *the* binding budget the rest of the plan must fit inside — if a
phase's tasks conflict with this, the tasks lose, not the schedule.

### Capacity

- **Headcount:** 3 contributors.
- **Timeframe:** 7 months target (≈ 30 weeks), 8-month soft ceiling.
- **Weekly hours per contributor:** 6 nominal.
- **Person A (maintainer / thesis author)** may contribute fewer direct
  hours but operates with heavy LLM assistance, roughly ×2 effective
  output on software and prose. This *does not* speed up hardware
  bringup or measurement work — AI cannot read a scope.

| Source                                  | Hours |
| --------------------------------------- | ----: |
| 3 × 6 h/week × 30 weeks                 |   540 |
| Person A AI uplift (≈ ×2 on SW / prose) |   +60 |
| **Effective budget**                    | ≈ 600 |

This is tight for the headline scope. The schedule below is built
backwards from 600 hours; the *Out of scope* subsection trims the
roadmap until it fits.

### Roles

The pillars map cleanly to three streams. Owners are the *primary*
author for each stream; the team meets weekly to cross-pollinate.

- **Person A — SDK & integration lead.** `mpp_sdk/` Python work
  (models, algorithms, comparison harness, visualisation), the Pi-side
  `SpiMcuSource`, paper drafting, CI / reproducibility. Heavy LLM
  assistance expected and welcome here.
- **Person B — Power-electronics hardware lead.** Schematic and PCB
  (KiCad), component selection (MOSFET ✓, gate driver ✓, INA229 + INA281 ✓, V/I
  sense), BOM, assembly, bench bringup, calibration, hardware chapter
  of the paper.
- **Person C — Embedded firmware lead.** RP2040 bringup (Rust, `rp2040-hal`),
  ADC / PWM / SPI-slave firmware, HIL protocol, the algorithm port from Python
  to MCU, resource-budget reporting, firmware chapter of the paper.

The B↔C boundary is permeable; they pair on bringup. A↔C pair on the
SPI protocol and on the algorithm port.

### Schedule

7 months ≈ 30 weeks, in 4-week blocks. "Done" means the deliverable
has shipped *and* been independently verified per the rules in
*Verification*.

| Block             | Weeks | A — SDK & integration                                                    | B — hardware                                              | C — firmware                                                  |
| ----------------- | ----- | ------------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------- |
| **Foundation** ✓  | 1–4   | Phase 2 in-tree (`lossy`, `array`); `pvlib_adapter` skeleton             | Topology ✓; MOSFET + gate-driver ✓; INA229 + INA281 ✓; SEPIC in PLECS ✓; PCB design closed ✓ | MCU bringup (RP2040, Rust) ✓; SPI-slave skeleton with PIO ✓ |
| **Sim & SPI** ✓   | 5–8   | Phase 3: P&O variants + InCond ✓; harness scaffold ✓; `SpiMcuSource` skeleton ✓ | PCB layout v1 ✓; **fab order by week 6** ✓ (at fab 2026-06-10); long-lead parts in ✓ (all components bought) | SPI protocol locked; loopback HIL working in software ✓ (#10) |
| **Hardware up**   | 9–12  | First sim-only comparison results; pvlib adapter integrated              | PCB assembly; bringup; ADC calibration                    | ADC / PWM jitter measurement; SPI link to Pi alive            |
| **HIL milestone** | 13–16 | Sim + HIL numbers in the harness                                         | Bench: sense path validated against scope                 | **Phase 5a done** — HIL end-to-end with Python algorithm      |
| **Algo push**     | 17–20 | Add one Global-MPPT method; first paper figures                          | Hardware-vs-sim cross-check at multiple operating points  | Begin algorithm port to MCU (deployed mode)                   |
| **Deployment**    | 21–24 | Lock candidate algorithm for port; freeze figures                        | Outdoor PV test if time (stretch goal)                    | **Phase 5b done** — deployed algorithm matches Python ref     |
| **Writeup**       | 25–30 | Paper draft → review → polish                                            | Hardware chapter; BOM; calibration log                    | Firmware chapter; resource budget report                      |

**Two hard milestones drive everything else:**

1. **PCB to fab by end of week 6.** Hardware slip here cascades.
   ✓ **Met (2026-06-10):** PCB sent to the manufacturer, all components
   purchased. Assembly, soldering and bench checks estimated at ~2 weeks
   after boards arrive, so board-level firmware bringup (Phase 5a) starts
   late June / mid July — inside the Hardware-up block (weeks 9–12).
2. **HIL working by end of week 16.** If HIL is not running by then,
   *deployed mode* is at risk and the paper falls back to a
   simulation-only contribution.

### In scope for v1 (the paper)

- `IdealSingleDiode` (shipped); `SingleDiodeWithLosses` in-tree (pending).
- `PvlibPanelModel` adapter for temperature / irradiance (shipped).
- `PvString` + bypass diodes (one canonical shading pattern in the
  paper, not a topology survey) (shipped).
- `SEPICConverter` model (shipped).
- Algorithms (shipped): P&O, Incremental Conductance, Fuzzy, and two
  Global-MPPT methods (`ScanAndTrack`, `ParticleSwarm`). Pick the one easier to
  port for the MCU deployment.
- Algorithm-focused comparison harness with the metrics listed in
  Phase 4 below — no inverter-efficiency / EN-50530 work in v1.
- Custom board: **SEPIC** stage (simulated in PLECS ✓), MOSFET + gate driver ✓,
  V/I sense via INA229 + INA281 ✓, MCU
  section, SPI to Pi, basic protections.
- MCU firmware: HIL mode + the chosen algorithm in deployed mode.
- Hardware-vs-simulation comparison; resource-budget report.
- Paper / thesis covering all of the above.

### Out of scope for v1

These are real and interesting and they will sink the schedule. They
become "future work" in the paper and re-open after v1 ships.

- **Two-diode model in-tree** — `bishop88` via the pvlib adapter
  covers the use case.
- **Sliding-mode / model-predictive** controllers. (Fuzzy was listed here
  originally but shipped in Phase 3 and is in the v1 scope above.)
- **Data-driven / RL** baseline.
- **More than one Global-MPPT variant.**
- **Empirical-model library from large datasets** — one panel's swept
  curves is enough; no library work.
- **Outdoor PV testing as required.** Bench is enough for the paper;
  outdoor is a block-6 stretch goal.
- **Synchronous rectification, multi-string MPPT in hardware, Wi-Fi
  telemetry.**
- **Inverter-efficiency / EN-50530-style scoring.** EN 50530 grades
  the inverter as a whole; this work is algorithm-focused, so we
  measure the metrics in Phase 4 instead and leave EN-50530 numbers
  to "future work."
- **A general fixture format for the harness.** Hard-code the v1
  test cases first; generalise later if a second profile shows up.

### Top risks

- **Hardware slip.** The single biggest risk. *Mitigation:* lock the
  topology in week 2; long-lead parts on order by week 4; PCB to fab
  by week 6; keep a *fallback rig* using a commercial dev board (TI /
  Microchip eval board, or a published reference design) wired up in
  parallel so the software track is never blocked on the custom PCB.
- **Algorithm port fails the resource budget.** *Mitigation:* by
  week 16, pick the port candidate against an explicit budget — ≤ 16 KB
  flash, ≤ 4 KB RAM, ≤ 1 ms per step on the chosen MCU. If fixed-step
  P&O is the only thing that fits, that is a fine paper result and
  matches the "minimal-state, branch-light" design constraint.
- **Person A under-delivers; AI multiplier does not materialise.**
  *Mitigation:* keep Person A on the integration surface (glue, code
  review, prose — where AI helps most) rather than on a critical
  path. B and C each own one critical path; a one-person dropout is
  not fatal.

## Roadmap

Phases unblock each other in order. Do not start phase N before phase N−1
has **shipped *and* been independently verified**.

### Phase 1 — Scaffolding (shipped)

- Package layout and four-pillar architecture.
- `IdealSingleDiode` model, ideal `SEPICConverter`, `SimulatedSource`.
- `PerturbAndObserve` controller (sign-corrected for SEPIC duty cycle;
  same sign as a boost so boost-based papers port unchanged).
- Live I-V / P-V view (`LivePanelView`) driven by `FuncAnimation`.
- `AGENTS.md` (architectural pillars) and this `PLAN.md`.

### Phase 2 — Realistic models

#### Single-module fidelity — in-tree (pedagogical)

These keep the SDK self-contained for a reader who just wants to see the
equations. They live next to `IdealSingleDiode` under `mpp_sdk/models/`.

- [ ] `models/lossy.py / SingleDiodeWithLosses` — single-diode with
      series and shunt resistance (`R_s`, `R_sh`). `I(V)` becomes
      implicit; solve with hand-rolled Newton-Raphson or bisection. The
      point of carrying this in-tree is to *exhibit* the implicit-solver
      step, not to compete with pvlib.

#### Single-module fidelity — via `models/pvlib_adapter.py`

Higher-fidelity physics is delegated to pvlib through a single
`PvlibPanelModel(PanelModel)` adapter behind an optional dependency
group (`mpp-sdk[pvlib]`). Because it subclasses `PanelModel`, the rest
of the SDK consumes it transparently.

- [x] `PvlibPanelModel(PanelModel)` wrapping pvlib's De Soto single-diode,
      temperature- and irradiance-aware via `calcparams_desoto`.
      `from_datasheet(...)` fits parameters; `hissuma_psf10mono(...)` is the
      project panel.
- [ ] Two-diode / reverse-bias regime via pvlib's `bishop88` family
      (per-cell partial-shading; current shading is modelled at the module
      level by `PvString` bypass diodes instead).
- [ ] Empirical model: interpolation over swept I-V tables (CEC database or
      user curves under `data/`). `TabulatedPanel` already caches an I-V
      curve; this would back it from measured data.

#### Composition: strings, bypass diodes, shading

Orthogonal to single-module fidelity — a `PvString` *is* a `PanelModel`, so it
composes any module above and the rest of the SDK consumes it identically.

- [x] `PvString(PanelModel)` — N panels in series with per-panel bypass diodes;
      solves the common string current. Per-panel irradiance produces the
      multi-modal P-V curve (motivation for the global MPPT in Phase 3).
      Parallel / SP / TCT / BL topologies remain future work.
- [x] Dedicated smoke test pinning the count / location of local maxima for
      canonical shading patterns (`tests/test_string.py`).

### Phase 3 — Algorithm zoo

- [x] Perturb & Observe (shipped in Phase 1).
- [x] Incremental Conductance (InCond), fixed step.
- [x] Fuzzy-logic controller (local tracker).
- [x] **Global MPPT** — `ScanAndTrack` (full-range scan + local refinement) and
      `ParticleSwarm`. Escape the local maxima from bypass diodes under shading.
- [ ] Adaptive-step P&O / variable-step InCond.
- [ ] Own model-informed candidate scan (peaks near k·V_mp) for minimal MCU cost.
- [ ] Sliding-mode / model-predictive controllers.
- [ ] Data-driven baseline (supervised on swept curves and/or RL).

### Phase 4 — Algorithm comparison harness

The harness is **algorithm-focused**, not system-efficiency-focused.
We are not measuring inverter conversion efficiency (the SEPIC is not
optimised for that, and EN 50530 grades the inverter as a whole) — we
are measuring how well an MPPT controller finds and holds the panel's
MPP under realistic conditions, including the partial-shading case
where Global-MPPT is the whole point.

- [ ] **Test cases** (a fixed set, hard-coded for v1; generalise to a
      fixture format only if a second profile shows up):
  - Cold start at STC.
  - Slow / medium / fast irradiance ramps.
  - Step changes in irradiance.
  - Partial-shading patterns producing 2 / 3 / 4 local maxima on the
    P-V curve.
  - Noise injected on V and I measurements at several levels.
Shipped so far in `mpp_sdk.metrics` (preliminary — see the methodology warning
in that module; the current fixed-start comparison is **not yet a valid
measurement**):

- [x] Tracking efficiency `η = ⟨P⟩ / P_mpp`, final (steady-state) efficiency.
- [x] Settling time, steady-state ripple, overshoot, trap depth
      `P_local / P_global`.

Still to do:

- [x] **Cyclic irradiance profile** (full → A shaded → full → B shaded → both →
      full) and energy-integrated efficiency over it — the valid dynamic
      measurement (`harness/compare_cyclic.py`, `metrics.energy_efficiency`).
- [ ] Fixed test-case bank — mostly shipped in `harness/compare_bank.py`
      (cold start, cover-on/off steps, steady shade, Voc-side trap, with
      (t, V, I, D) trace dumps for sim-to-real replay); still missing
      isolated ramps and measurement noise.
- [ ] **Partial-shading bank metrics**: global-MPP success rate and
      time-to-global ship with the cyclic harness; worst-case trap depth
      *across patterns* waits on the 2/3/4-peak shading bank.
- [ ] **Robustness**: `η` vs measurement-noise level ✓
      (`harness/compare_noise.py` via `NoisySource`); vs sample rate pending.
- [ ] **Implementation-cost** (binding for the MCU port): state size in bytes,
      per-step compute, code size after the port.
- [ ] Auto-generated result tables and figures consumed directly by the paper.

### Phase 5 — Hardware demonstrator

The power-electronics board is driven by an **RP2040 (Pi Pico, firmware in
Rust)**, connected to the Raspberry Pi 5 over SPI. The MCU provides isolation
from the Pi (the expensive, soft-real-time side) *and* is the deployment target
for the final algorithm. The phase is split into two sub-phases:

#### Phase 5a — Pi + MCU HIL bringup

The MCU is an I/O proxy in this phase: ADC + PWM + SPI-slave, with the
algorithm still running on the Pi in Python. This validates the
electronics, the SPI protocol, and the calibration without the
additional uncertainty of a ported algorithm.

- [ ] `SpiMcuSource(SignalSource)` — Pi-side Python wrapper around the
      SPI protocol (duty-cycle out, `(V, I)` in, with a watchdog).
- [ ] MCU firmware (HIL mode): ADC sense, hardware-PWM drive,
      SPI-slave handler, and a small command set (set duty, read
      sample, read calibration, soft-stop on watchdog timeout).
- [ ] Calibration procedure: ADC scale / offset, sense-resistor value,
      PWM frequency, soft duty-cycle limits, SPI clock, watchdog
      timeout.
- [ ] Bench validation: reproduce a simulated tracking efficiency on
      real hardware within a documented tolerance.
- [ ] Outdoor test with a small PV panel under varying irradiance.

#### Phase 5b — Algorithm port to MCU (deployed mode)

The validated algorithm is ported from Python to MCU firmware; the Pi
is reduced to monitoring and configuration. This is the contribution
the paper's "MCU-deployable algorithm" claim rests on.

- [x] Firmware language / toolchain: Rust with `rp2040-hal` ✓.
- [ ] Port the chosen algorithm. Cross-validate it against the Python
      reference point-by-point on recorded `(V, I, D)` traces from
      Phase 5a — same inputs, same outputs (within a defined
      numerical tolerance).
- [ ] Resource budget report: code size (flash), peak RAM, worst-case
      step latency, energy per control step.
- [ ] Bench: deployed-MCU vs Pi-driven-Python on the same physical
      rig, same load profile.
- [ ] Outdoor test with a small PV panel — deployed mode end-to-end.

### Phase 6 — Paper / thesis

- [ ] Methodology chapter (models, algorithms, simulation framework).
- [ ] Results chapter (comparison metrics, plots).
- [ ] Hardware validation chapter.
- [ ] Discussion and conclusions.
- [ ] SDK reference and reproducibility appendix.

### Publishing to PyPI

Releasing the package to PyPI makes it installable with a single command in
any project (`uv add mpp-sdk`) and signals that the SDK is a citable,
versioned artefact — useful for the thesis reproducibility appendix.

**Prerequisites — add to `pyproject.toml` before the first upload:**

```toml
[project]
license   = { text = "MIT" }
authors   = [{ name = "Federico Borello", email = "fborello.contact@gmail.com" }]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Scientific/Engineering :: Physics",
]

[project.urls]
Homepage   = "https://github.com/<org>/mpp-sdk"
Repository = "https://github.com/<org>/mpp-sdk"
```

**Manual release steps:**

```bash
# 1. Build the wheel and sdist
uv build

# 2. Smoke-check the distributions
uv run twine check dist/*

# 3. Test on Test PyPI first
uv publish --publish-url https://test.pypi.org/legacy/ --token $TEST_PYPI_TOKEN

# 4. Install from Test PyPI and run smoke tests
uv add --index https://test.pypi.org/simple mpp-sdk
uv run pytest tests/test_smoke.py

# 5. Tag and publish to the real registry
git tag v0.x.y && git push --tags
uv publish --token $PYPI_TOKEN
```

**Automated CI release (add `.github/workflows/publish.yml`):**

```yaml
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # OIDC trusted publishing — no stored token needed
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build
      - run: uv publish
```

Configure **Trusted Publishers** at pypi.org (project → Publishing tab) to
avoid storing an API token as a GitHub secret. The workflow above is ready
for it: `id-token: write` grants the OIDC credential automatically.

**Optional extras are already wired** in `[project.optional-dependencies]`
and work out of the box after publishing:

```bash
uv add "mpp-sdk[pvlib]"     # high-fidelity panel models via pvlib adapter
uv add "mpp-sdk[hardware]"  # SPI hardware deps for Phase-5 SpiMcuSource
uv add "mpp-sdk[all]"       # both extras at once
```

## Verification — each part must work separately

Modular verification is non-negotiable. The four pillars (`models/`,
`converters/`, `algorithms/`, `io/`) are decoupled **by design**; keep
them that way under test. Each new module ships with:

1. **Unit tests** under `tests/` that exercise the public API in
   isolation. Concrete examples:
   - For a new panel model: `I(0) ≈ Isc`, `I(Voc) ≈ 0`, MPP within
     tolerance of an analytic or datasheet reference.
   - For a new algorithm: against a fixed `SimulatedSource`, it must
     converge to within `ε W` of the MPP in ≤ `N` iterations and stay
     bounded afterwards.
   - For a new converter: voltage / current relations and reflected
     impedance match closed-form expectations across the duty range.
2. **A standalone demo script** under `examples/` that can be run by
   hand and produces a single interpretable plot. Demos are the
   project's living documentation (`AGENTS.md`).
3. **An integration test** wiring the new piece into the full loop
   (panel + converter + algorithm + view) to confirm system-level
   behaviour.

Code that passes the integration test but cannot be exercised in
isolation indicates a leaky abstraction. **Fix the abstraction, not the
test.** A change that requires touching modules from more than one
pillar simultaneously deserves a second look — the seams are there for
a reason, not least so the same code can later run on real hardware.

## Reproducibility for the paper

- Pin dependency versions in `uv.lock` for every published result.
- Tag the repository (`v0.x.y`) at each milestone the paper references
  and cite the tag in the methodology chapter.
- Store benchmark profiles (irradiance / temperature traces) and
  measured panel curves under `data/` with a README documenting
  provenance.
- Every figure in the paper is produced by a script in `examples/` or
  `paper/figures/`. No figure is hand-edited.
- Set RNG seeds explicitly for any stochastic experiment.

## Contributor liability

By committing to this repository, an author:

- Asserts the commit is their own work, or attributes it clearly to its
  source (other authors, papers, datasheets, third-party libraries).
- Accepts responsibility for the correctness of the change and for any
  consequences of running the code — including on real hardware.

The thesis author (the repository maintainer) is ultimately accountable
for the scientific content of the paper. External contributions will be
acknowledged in a `CONTRIBUTORS.md` (created when the first external
contribution lands), but accountability for the thesis does **not**
transfer with the commit.

The MIT license (see `LICENSE`) covers redistribution; **it is not a
warranty.** Anyone wiring this code to real hardware is responsible for
electrical safety, for the protection of the panel and converter, and
for validating the code against their own measurements.

## Use of large language models

Large language models (Claude, ChatGPT, Copilot, …) have been used during
development of this repository. The policy:

1. **Disclose.** The thesis and the paper include an "Acknowledgements"
   or "Tools" section naming the LLMs used and the kinds of tasks they
   were used for (code generation, refactoring, prose editing). A
   suggested wording:

   > Portions of this software and supporting prose were drafted with
   > assistance from large language models (Claude, …). All code was
   > reviewed, tested, and integrated by the human author, who is
   > responsible for its correctness. Experimental results and
   > conclusions are the author's own work.

2. **Verify.** No LLM output is merged on the basis of *"it looks
   right."* Every LLM-assisted change must be:
   - Read and understood by a human contributor.
   - Exercised by the verification procedure above (unit + smoke +
     integration as applicable).
   - Cited to its primary reference (paper, datasheet) wherever the
     LLM reproduces or paraphrases a known algorithm, formula, or
     proof.
3. **Author.** The human contributor remains the `Author:` of every
   commit. A `Co-Authored-By:` trailer may credit the LLM, but the
   human is accountable for the diff regardless of whose keystrokes
   produced it.
4. **Off-limits.** Numerical results, measured data, experimental
   claims, and conclusions in the paper are written and validated by
   the human author. LLMs may help with prose, structure, and code;
   the science is not theirs.

### Academic-integrity considerations

The disclosure policy above (Disclose / Verify / Author / Off-limits)
covers the *transparency* requirement. This subsection deals with the
secondary risk that a heavily AI-assisted public repository may be
*perceived* as undermining the academic contribution, regardless of
disclosure. The mitigation is to (a) position AI as a deliberate
methodological choice, (b) map exposure across project layers so
reviewers can see what is and is not AI-touched, and (c) confirm each
contributor's institutional policy before submission.

**AI exposure by layer** (high → low):

| Layer                         | AI exposure | Why it is acceptable                                                                                                       |
| ----------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------- |
| SDK Python code (this repo)   | High        | Framework / scaffolding work; every line was reviewed and is testable. Open source — reviewers can audit any line.         |
| Documentation in this repo    | Medium      | Drafted with assistance, edited and signed off by a human. The thesis text itself is human-authored.                       |
| Comparison-harness analysis   | Medium      | Glue code and figure plumbing are AI-assisted; the *choice* of metrics and the interpretation of results are the author's. |
| Hardware design (PCB, BOM)    | Low         | Hands-on engineering; AI has limited effective contribution to PCB layout, soldering, or scope work.                       |
| Algorithm derivations         | Low         | Mathematics in the thesis traces to citable references and is the author's analysis. AI may suggest references; it does not author the proofs. |
| Experimental measurements     | None        | Real data on real hardware; the human reads the scope.                                                                     |
| Conclusions and discussion    | None        | The author's argument, defended at the viva.                                                                               |

**Defence talking points** (rehearse before the viva):

1. *"Where did AI help, and where didn't it?"* — point at the table
   above. The framework is AI-leveraged so the team's limited hours
   could be spent on the original contributions: hardware design,
   algorithm analysis, and experimental validation.
2. *"How do we know the AI-generated code is correct?"* — point at
   the verification policy: unit / smoke / integration tests for
   every module; cross-validation between the in-tree models and the
   pvlib adapter; HIL- and deployed-MCU cross-validation against the
   Python reference.
3. *"How do we know the prose is the author's argument?"* — the
   thesis document is human-written; the repo's docs serve a
   different purpose (project housekeeping) and have a different
   bar.
4. *"What if a reviewer is biased against AI-assisted work?"* —
   engage with it. AI assistance is itself a methodological
   contribution worth a paragraph in the methodology chapter, not
   something to apologise for. The thesis's value is the framework,
   the hardware, and the experiments — none of which AI authored.

**Institutional policy — confirm per contributor.** Each contributor's
institution has its own AI-assistance policy. Before the thesis is
submitted, confirm:

- The disclosure level the policy requires (footnote, dedicated
  section, declaration form).
- Whether the policy bans AI assistance on any specific layer
  (e.g. some institutions ban it on "the writing of the thesis
  itself"). Layers under such a ban must stay AI-free regardless of
  what this repo does.
- That co-authors / classmates are aware of the policy and the
  disclosure and have given informed consent.

These are tracked in *Open questions* until each institution is
checked off.

## Viability assessment and related work

This section answers two questions explicitly: *is the project viable as
a thesis / paper contribution*, and *how does it position against the
existing open-source ecosystem (in particular pvlib)*. The conclusions
below should be revisited after the comparison harness ships and we have
real numbers in hand.

### What pvlib already covers

[`pvlib-python`](https://pvlib-python.readthedocs.io/) is the de-facto
open-source reference for photovoltaic *performance modelling* in
Python and was originally a port of Sandia's MATLAB PVLIB toolbox
[Anderson et al. 2023, Holmgren et al. 2018]. It provides:

- Solar position, clear-sky and decomposition / transposition
  irradiance models, atmospheric and spectral corrections.
- Single- and two-diode panel I-V solvers, including the `bishop88`
  reverse-bias / breakdown formulation [Bishop 1988] that supports
  partial-shading analysis at cell or substring granularity.
- Temperature models, soiling and snow losses, single-axis trackers,
  bifacial irradiance, and inverter / energy-yield (`ModelChain`)
  workflows.

It is steady-state and analytical: it returns *the* maximum power point
for a given panel and environment, not a controller that has to find
the MPP from a stream of (V, I) measurements. There is no time-stepping
controller simulation, no power-stage model, and no hardware
abstraction. The maintainers describe the scope explicitly as
performance simulation rather than dynamic system control.

### What mpp-sdk adds

The complementary contribution of `mpp-sdk` is concentrated in three
layers that pvlib does not address:

1. **MPPT controllers**: a uniform `MPPTAlgorithm.step(V, I) → D`
   interface and an extensible zoo of implementations (P&O shipped;
   InCond, adaptive-step, fuzzy, sliding-mode, MPC, Global-MPPT and
   data-driven baselines on the roadmap).
2. **Power-stage abstraction with an MCU-mediated hardware seam**: a
   `SEPICConverter` model plus a `SignalSource` ABC. The hardware
   implementation is intentionally split — the Pi 5 hosts the SDK and
   the algorithm; a small MCU (Raspberry Pi Pico / RP2040) drives
   the power stage and talks to the Pi over SPI. This isolates the
   fast-switching / high-current side from the Pi *and* gives us a
   natural target for deploying the validated algorithm on the MCU
   itself, which is the thesis's headline deliverable.
3. **A reproducible comparison harness**: standardized dynamic
   profiles (EN 50530), agreed-upon metrics (tracking efficiency,
   settling time, steady-state oscillation, step response), and
   auto-generated figures that the paper consumes directly.

The intended relationship with pvlib is not competition but
**adoption**: a `PvlibPanelModel(PanelModel)` adapter (Phase 2) wraps
pvlib's single-diode and `bishop88` solvers behind our interface so
that the controllers and the comparison harness benefit from pvlib's
validated physics without us re-implementing it. We expect the SDK's
in-tree models to remain pedagogical (the ideal single-diode is useful
precisely because it has a closed-form I(V)); the heavy lifting under
the eventual paper's experiments comes from pvlib via the adapter.

### Why this is publishable

Most of the MPPT comparison literature [Esram & Chapman 2007; Subudhi &
Pradhan 2013] uses MATLAB / Simulink, with code that is rarely
released; comparisons across papers are difficult to reproduce because
each work uses its own panel parameters, irradiance profiles, and
metrics. The sim-to-real gap is also an open problem: hardware
validation papers and pure-simulation papers usually rely on different
codebases, so a controller's "simulated 99 % efficiency" is hard to
relate to its bench result.

A Python framework that:

- Has a uniform algorithm interface (so adding a new controller is a
  one-file PR),
- Is pvlib-compatible for panel physics (so reviewers trust the
  modelling),
- Standardises on EN 50530 profiles and a fixed set of metrics (so
  numbers are comparable across studies),
- Uses the same controller code in simulation and on a small hardware
  demonstrator (so sim-to-real claims are first-class), and
- Carries an explicit deployment path from Python to MCU firmware,
  with cross-validation between the two,

fills a real, currently-empty niche. The thesis's contribution is best
framed as the *framework + comparative study + hardware validation +
MCU-deployable algorithm*, with novel custom algorithms entering as
case studies that exercise the framework rather than as the
centrepiece. The MCU-deployment requirement is itself a design
constraint that biases the work toward fixed-step / minimal-state
methods — which are also the easiest to analyse — and so reinforces
rather than competes with the academic story. The framing is robust
even if the headline novel-algorithm result turns out modest, because
the framework + the deployment evidence are the artefacts.

### Risks and mitigations

- **Reinventing pvlib.** Mitigation: the `PvlibPanelModel` adapter is a
  Phase-2 deliverable; in-tree models stay minimal and pedagogical.
- **"Yet another MPPT review" framing.** Mitigation: position the paper
  around the *framework* and *sim-to-real reproducibility*, not around
  yet another P&O-vs-InCond table; lean on hardware validation as the
  novel contribution.
- **Hardware effort.** Mitigation: scope the demonstrator small (one
  panel or short string, ~50–200 W), use commodity parts (INA226 or
  similar for sense, hardware PWM on the MCU), and document the bill
  of materials in `data/hardware/`.
- **Real-time control budget.** Mitigation: the inner control loop
  *intentionally* lives on the MCU rather than on the Pi 5. The MCU is
  not a fallback — it is the planned topology, both for jitter
  reasons (Linux user space is too soft a real-time environment for
  kHz-class PWM control) and because the MCU is the deployment target
  the paper rests on. If the MCU itself proves under-resourced, the
  candidate set extends to STM32 / RP2040-via-PIO without changing the
  Pi-side SDK.
- **Sim-to-real-to-MCU consistency.** Mitigation: every controller is
  verified at three levels — (i) Python against `SimulatedSource`,
  (ii) Python against `SpiMcuSource` (HIL), (iii) ported MCU firmware
  against the Python reference, point-by-point on recorded traces.

## Open questions (track and resolve before locking the methodology)

- Boost-converter modelling: validate the reflected-resistance formula
  `R_in = (1−D)²·R_load` against bench measurements; replace with a
  non-ideal model (switch on-resistance, inductor DCR, diode drop) once
  the demonstrator is wired.
- Choice of measured-panel dataset for the empirical model (NREL, JRC,
  in-house bench measurements).
- Array topology to model first (series-parallel vs total-cross-tied vs
  bridge-link) — pick the one closest to the demonstrator's reference
  design.
- Bypass-diode granularity: one diode per panel, or one per substring of
  N cells (typical: 20-cell substrings on a 60-cell module).
- Standard partial-shading patterns to benchmark Global-MPPT algorithms
  against (single-panel shaded, single-substring shaded, multi-peak
  contrived patterns from the literature).
- Demonstrator topology: synchronous vs asynchronous boost, switching
  frequency, current sensor (shunt + INA226 vs Hall-effect).
- **MCU choice (Phase 5):** Resolved — Raspberry Pi Pico (RP2040).
  Firmware language: Rust (decided during Block 1; SPI-slave PIO
  scaffolding already in place).
- **Firmware language for the deployed algorithm:** Resolved — Rust
  with `rp2040-hal`. MicroPython prototyping path dropped.
- **SPI protocol design (Phase 5a):** master/slave roles, frame
  format, sample rate, watchdog / soft-stop semantics. Document the
  protocol in `data/hardware/spi_protocol.md` once it stabilises.
- **Institutional AI-assistance policy per contributor.** Disclosure
  level required, layers where AI is banned, declaration-form
  requirements, co-author informed consent. Must be checked off per
  contributor before thesis submission.
- Form of the comparison-harness configuration: YAML fixtures vs pure
  Python.
