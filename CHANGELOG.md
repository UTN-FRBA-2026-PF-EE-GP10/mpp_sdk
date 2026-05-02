# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[SemVer](https://semver.org/spec/v2.0.0.html). Entries describe **the state
of the repo at each version**, not a transcript of every commit — see
`AGENTS.md` for the compactness rule.

## [Unreleased]

## [0.1.0] - 2026-04-30

Initial scaffolding.

- **Four-pillar package** (`models/`, `converters/`, `algorithms/`, `io/`):
  `IdealSingleDiode`, `SEPICConverter` (`R_in = R_load·((1−D)/D)²`, unity
  at `D = 0.5`), `PerturbAndObserve`, and `SimulatedSource` (bisection
  operating-point solver). `visualization.py` adds `LivePanelView`
  (animatable I-V / P-V) and `plot_iv_with_operating_point` (one-shot);
  matplotlib imported lazily.
- **Live demo** (`main.py`, `examples/pno_demo.py`): indefinite
  `FuncAnimation` of P&O tracking a drifting MPP via photocurrent ramp.
- **Docs**: `AGENTS.md` (architecture, MCU-portability rule, model-fidelity
  tracks, no-secrets policy), `PLAN.md` (3-person / ~600 h / 30-week
  schedule, algorithm-focused metrics, pvlib viability verdict,
  academic-integrity AI-exposure table), `README.md` (why pitch, pvlib
  comparison, references), `AUDIT_FOR_JUNE.md` (mid-June self-audit prompt).
- **Build & CI**: hatchling layout; optional deps `pvlib`, `hardware`, `all`;
  dev group (`pytest`, `ruff`); GitHub Actions `ci.yml` (lint + format +
  test) and `auto-assign.yml` (PR opener assignment).
- **Tests**: 8 smoke tests — panel endpoints, MPP envelope, SEPIC invariants,
  P&O convergence within 1 % of analytic MPP, headless visualization.
