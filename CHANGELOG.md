# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[SemVer](https://semver.org/spec/v2.0.0.html). Entries describe **the state
of the repo at each version**, not a transcript of every commit — see
`AGENTS.md` for the compactness rule.

## [Unreleased]

## [0.1.0] - 2026-04-30

Initial scaffolding.

- **Four-pillar package** under `mpp_sdk/`: `models/` (`PanelModel` ABC +
  `IdealSingleDiode`), `converters/` (`BoostConverter`, ideal CCM with
  `R_in = (1-D)² R_load`), `algorithms/` (`MPPTAlgorithm` ABC +
  `PerturbAndObserve`, sign-corrected for boost duty cycle), `io/`
  (`SignalSource` ABC + `SimulatedSource` resolving the operating point
  by bisection). `visualization.py` provides `LivePanelView` (animatable
  I-V / P-V) and `plot_iv_with_operating_point` (one-shot snapshot);
  matplotlib is imported lazily.
- **Live demo** (`main.py` and `examples/pno_demo.py`): indefinite
  `FuncAnimation` of P&O against the ideal panel, with a slow photocurrent
  drift so the algorithm has a moving MPP to chase.
- **Docs**: `AGENTS.md` (architecture, conventions, MCU-portability rule,
  model-fidelity split into in-tree vs `PvlibPanelModel`-adapted tracks,
  Pi 5 ↔ Pico/ESP32 hardware topology), `PLAN.md` (phased roadmap with
  verification, reproducibility, contributor liability, LLM policy, and a
  viability assessment vs `pvlib-python`), `README.md` (`## Why` pitch,
  pvlib comparison, roadmap, references).
- **Build**: hatchling library layout. Base dependencies `numpy` and
  `matplotlib`; optional dependency groups `pvlib`, `hardware` (`spidev`
  for the Phase-5 SPI client), and `all`.
- `PLAN.md` *Team allocation, schedule, and scope* section: 3-person /
  ~600-hour budget over 30 weeks, role split (SDK & integration /
  hardware / firmware), 4-week-block schedule with hard milestones at
  PCB-to-fab (week 6) and HIL working (week 16), explicit in-scope and
  out-of-scope lists, and the top three delivery risks with mitigations.
- `AUDIT_FOR_JUNE.md` — self-contained audit prompt to run manually
  around mid-June 2026 (end of week 6). Read-only protocol that scores
  hardware-fab status, long-lead parts, decision lock-in, SDK / firmware
  progress, out-of-scope creep, and top-level health, and produces a
  short verdict report in a fixed format.
