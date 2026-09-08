# Plan 026: Unit tests for the curve-tracer safety-cutoff check (`breach`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md` (do not otherwise edit that file).
>
> **Drift check (run first)**: `git diff --stat ff010a4..HEAD --
> firmware/pipico_board/src/mode_curve_tracer.rs
> firmware/pipico_board/Cargo.toml firmware/pipico_board/Cargo.lock
> .github/workflows/firmware.yml`. If any of those files changed
> since this plan was written, re-read them and compare against the
> "Current state" excerpts below before proceeding; on a mismatch in the
> `breach` function's signature or the two threshold constants, treat it as
> a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M (see "Why not just `#[cfg(test)]`" - this is a bigger
  change than the audit's original S estimate, because of a target
  constraint that estimate missed)
- **Risk**: LOW - the extracted function is pure arithmetic with no
  hardware side effects; the three call sites become one-line signature
  changes
- **Depends on**: none
- **Category**: test coverage
- **Planned at**: commit `ff010a4`, 2026-09-06

## Why this matters

`CurveTracer::breach` (`firmware/pipico_board/src/mode_curve_tracer.rs:348`)
is the sweep's safety cutoff - the function that decides whether the
current bench rig (a MOSFET dissipating the sweep current *linearly*, see
`TRACER_P_MAX_MW`'s doc comment at line 109-120) is about to be driven past
its safe envelope. It is called from three places during a sweep
(`settle_and_monitor_for` at line 358, `probe_duty` at line 384, and the
main sweep loop at line 547) and, per its own doc comment, exists
specifically so an over-current or over-power condition is caught *during*
the settle window, not just after. This is exactly the kind of
few-line, easy-to-get-an-inequality-backwards function (`>` vs `>=`, or a
transposed operand) that deserves a fast, hardware-free regression test -
and currently has zero.

Found via the `improve` skill's September 2026 audit (finding TEST-04).

## Current state

`breach` today (`firmware/pipico_board/src/mode_curve_tracer.rs:344-351`):

```rust
    /// Polls `MEAS_V_MV`/`MEAS_I_MA` every `TRACER_SETTLE_POLL_MS` for
    /// `TRACER_SETTLE_MS`, returning `true` the instant the safety cutoff
    /// is breached instead of only checking after the fact - see
    /// `TRACER_SETTLE_POLL_MS`'s doc comment for why.
    fn breach(v_mv: u16, i_ma: u16) -> bool {
        let p_mw = v_mv as u32 * i_ma as u32 / 1000;
        i_ma > TRACER_I_MAX_MA || p_mw > TRACER_P_MAX_MW
    }
```

It is an associated function on `impl CurveTracer` (struct defined at line
272, impl block opens at line 283) - it takes no `self` and touches no
hardware state, it is just grouped there because it is only used by
`CurveTracer`'s methods. The two thresholds it reads
(`firmware/pipico_board/src/mode_curve_tracer.rs:107,120`):

```rust
const TRACER_I_MAX_MA: u16 = 700;
...
const TRACER_P_MAX_MW: u32 = 16_100;
```

The three call sites, all `Self::breach(v_mv, i_ma)`:

- Line 358, inside `settle_and_monitor_for` (polls during the settle
  window).
- Line 384, inside `probe_duty`.
- Line 547, inside the main sweep loop in `run_sweep` (exact surrounding
  method name: read the file to confirm before editing - it was not
  re-quoted here to keep this plan robust to unrelated nearby refactors).

### Why not just add `#[cfg(test)] mod tests` in place

This is the part the audit's original finding missed, and the reason this
plan's effort is S-M instead of the audit's S: `mode_curve_tracer.rs` is a
`mod` of the `mpp-firmware` binary crate
(`firmware/pipico_board/Cargo.toml`, package name `mpp-firmware`), and that
crate cannot build for a host target at all:

1. `firmware/pipico_board/src/main.rs` opens with `#![no_std]` and
   `#![no_main]` (confirmed by reading the first lines of that file) - a
   plain `cargo test` needs `std` and a normal `main`/test harness.
2. `firmware/pipico_board/.cargo/config.toml` forces
   `[build] target = "thumbv6m-none-eabi"` for every cargo invocation run
   from inside that directory (or against that manifest) - there is no
   `--target` override needed or possible without fighting this file.
3. Even ignoring (1) and (2), the crate's dependencies
   (`firmware/pipico_board/Cargo.toml`) include `embassy-rp` (feature
   `rp2040`, an RP2040-PAC/HAL-specific crate) and `cortex-m` (feature
   `inline-asm`, ARM-only) - both fail to compile on any non-ARM host
   target, `thumbv6m-none-eabi` has no test-harness support (it is a bare
   `none` target, no OS, no `std`), and neither combination can run
   `cargo test`.

So a `#[cfg(test)] mod tests` block placed directly in
`mode_curve_tracer.rs` would never actually execute - `cargo test` from
`firmware/pipico_board/` inherits the forced `thumbv6m-none-eabi` target
via `.cargo/config.toml` and fails to build the whole crate (both for the
`embassy-rp`/`cortex-m` reasons above and because that target lacks test
support at all). This has been confirmed by reading the three files above;
it was not additionally re-verified by attempting the build, since the
`#![no_std]`/forced-target/ARM-only-deps combination is individually
sufficient and each is independently confirmed.

**The fix**: extract `breach` and its two threshold constants into a new,
dependency-free sibling crate that lives *outside* `firmware/pipico_board/`
(so it is outside that directory's `.cargo/config.toml` scope - cargo's
config file discovery walks up from the target crate's manifest directory,
not across sibling directories, so a crate rooted at
`firmware/safety-checks/` is never affected by
`firmware/pipico_board/.cargo/config.toml`). Confirmed no interfering
config exists anywhere else in the tree:
`find /home/fd/Desktop/mpp_sdk -name "config.toml" -path "*/.cargo/*"`
returns only `firmware/pipico_board/.cargo/config.toml` - there is no
repo-root or `firmware/`-root `.cargo/config.toml` to also avoid.

`firmware/` has no workspace `Cargo.toml` (confirmed:
`find firmware -maxdepth 1 -name Cargo.toml` finds none at that level;
each of `firmware/pipico_board/` and `firmware/esp32c3-bpw34/` is an
independent crate) - adding a third sibling crate does not touch a
workspace member list because there is no workspace to touch.

## Scope

**In scope**:

- New crate `firmware/safety-checks/` (new directory, `Cargo.toml`,
  generated `Cargo.lock`, and `src/lib.rs`).
- `firmware/pipico_board/Cargo.toml` - add a path dependency on it.
- `firmware/pipico_board/Cargo.lock` - update it for the new path
  dependency; this repository commits firmware lockfiles and CI builds
  with `--locked`.
- `firmware/pipico_board/src/mode_curve_tracer.rs` - remove `breach` and
  the two threshold constants, replace the three call sites, `use` the new
  crate's function.
- `.github/workflows/firmware.yml` - add a step to run
  `cargo test --locked` in the new crate (see Step 4; this workflow already
  runs from a `working-directory: firmware/pipico_board`, so the new step
  needs its own `working-directory: firmware/safety-checks`, not a
  directory change inside a shared step).

**Out of scope**:

- Any other function in `mode_curve_tracer.rs` (e.g. `auto_range`,
  `average_point`) - only `breach` is pure/dependency-free enough to
  extract this cheaply; do not attempt the same treatment for anything
  else in this pass.
- Renaming or restructuring `CurveTracer` itself.
- The `esp32c3-bpw34` crate - unaffected, do not touch.
- Adding tests for anything beyond `breach`'s boundary behavior (see Step 3
  for exactly what to test).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| New crate builds + tests (host target) | `cd firmware/safety-checks && cargo test --locked` | exit 0, test output shows all new tests passing |
| Firmware still builds for the real target | `cd firmware/pipico_board && cargo build --release --locked` | exit 0 |
| Firmware clippy still clean | `cd firmware/pipico_board && cargo clippy --release --locked -- -D warnings` | exit 0 |
| Firmware format check | `cd firmware/pipico_board && cargo fmt --check` | exit 0 (run `cargo fmt` first if it fails on your own new code; do not reformat pre-existing lines beyond what your edit touches) |
| New crate format check | `cd firmware/safety-checks && cargo fmt --check` | exit 0 |
| YAML sanity | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/firmware.yml'))"` | no exception |

## Git workflow

- Branch: `test/fw-safety-breach-tests`.
- Commits: one for the new crate + call-site updates, a second (or amend,
  operator's call) for the CI step - operator preference from this
  session has been one focused commit per PR, so a single commit covering
  both is also fine.
- Push and open a PR only after operator confirmation, same as every
  other plan in this batch.

## Steps

### Step 1: create the sibling crate

Create `firmware/safety-checks/Cargo.toml`:

```toml
[package]
name = "safety-checks"
version = "0.1.0"
edition = "2024"

[dependencies]
```

Create `firmware/safety-checks/src/lib.rs`:

```rust
//! Pure, dependency-free safety-cutoff arithmetic shared with
//! `mpp-firmware`'s curve tracer (`mode_curve_tracer.rs`). Extracted into
//! its own crate so it can be unit-tested with plain `cargo test`: the
//! firmware crate is `#![no_std]`/`#![no_main]`, forces the
//! `thumbv6m-none-eabi` target via its own `.cargo/config.toml`, and pulls
//! in ARM-only dependencies (`embassy-rp`, `cortex-m`) - none of which can
//! build for a host test target. This crate has none of those
//! constraints, so it defaults to the host target and supports `cargo
//! test` normally. `#![no_std]` is still asserted for non-test builds so
//! it stays safe to depend on from the `no_std` firmware crate.
#![cfg_attr(not(test), no_std)]

/// Safety cutoff: current, in milliamps. See `mode_curve_tracer.rs`'s
/// `TRACER_I_MAX_MA` doc comment in the firmware crate for the bench
/// rationale (~23 V x 0.7 A envelope, below the INA229's 1 A full scale).
pub const TRACER_I_MAX_MA: u16 = 700;

/// Safety cutoff: power, in milliwatts. See `mode_curve_tracer.rs`'s
/// `TRACER_P_MAX_MW` doc comment in the firmware crate for the bench
/// rationale (dissipated linearly in Q3, bounded below what two panels in
/// series can deliver at full sun).
pub const TRACER_P_MAX_MW: u32 = 16_100;

/// True if `(v_mv, i_ma)` breaches either cutoff above. Moved here
/// verbatim from `CurveTracer::breach` - no behavior change, extraction
/// only.
pub fn breach(v_mv: u16, i_ma: u16) -> bool {
    let p_mw = v_mv as u32 * i_ma as u32 / 1000;
    i_ma > TRACER_I_MAX_MA || p_mw > TRACER_P_MAX_MW
}
```

Generate and commit the crate's lockfile before using `--locked`:

```bash
cd firmware/safety-checks
cargo generate-lockfile
cargo build --locked
```

Expected: both commands exit 0 and `firmware/safety-checks/Cargo.lock`
exists. The lockfile is intentional even though the crate currently has
no third-party dependencies; plan 006 established committed lockfiles for
every firmware crate so CI resolution cannot drift.

### Step 2: wire it into the firmware crate

In `firmware/pipico_board/Cargo.toml`, add under `[dependencies]`:

```toml
safety-checks = { path = "../safety-checks" }
```

Then run `cargo generate-lockfile` from `firmware/pipico_board/` so its
committed `Cargo.lock` records the new path dependency. Do this before the
`--locked` build below; otherwise Cargo must update the lockfile and the
command will correctly fail.

In `firmware/pipico_board/src/mode_curve_tracer.rs`:

- Delete the `TRACER_I_MAX_MA` const (line 107, plus its doc comment lines
  103-106) and the `TRACER_P_MAX_MW` const (line 120, plus its doc comment
  lines 109-119) - **read the current doc comments first**; if you want to
  preserve any bench-context prose that is not already duplicated in the
  new crate's doc comments (Step 1), move it into
  `firmware/safety-checks/src/lib.rs`'s doc comments instead of losing it,
  since that prose (dissipation being linear in Q3, the two-panels-in-series
  figure) is exactly the kind of hardware rationale this repo's doc
  comments are for.
- Delete the `breach` function itself (lines 344-351, including its doc
  comment).
- Add `use safety_checks::breach;` near the top of the file (with the
  other `use` statements, e.g. near line 27's
  `use crate::{MEAS_I_MA, MEAS_V_MV, RELAY_ENGAGED, TRACER_ACTIVE};`) -
  note the crate name has a hyphen (`safety-checks`) but the Rust path uses
  an underscore (`safety_checks`), same as any other Cargo package name
  with a hyphen.
- Update all three call sites from `Self::breach(v_mv, i_ma)` to
  `breach(v_mv, i_ma)` (grep for `Self::breach` in the file to make sure
  all three - and only those three - are updated).

**Verify**:

```bash
cd firmware/pipico_board
cargo build --release --locked   # exit 0
cargo clippy --release --locked -- -D warnings   # exit 0
cargo fmt --check   # exit 0
```

### Step 3: write the tests

Create `firmware/safety-checks/src/lib.rs`'s test module (append to the
same file, below the `breach` function):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn under_both_thresholds_does_not_breach() {
        assert!(!breach(20_000, 500));
    }

    #[test]
    fn current_at_threshold_does_not_breach() {
        assert!(!breach(1_000, TRACER_I_MAX_MA));
    }

    #[test]
    fn current_just_over_threshold_breaches() {
        assert!(breach(1_000, TRACER_I_MAX_MA + 1));
    }

    #[test]
    fn power_at_threshold_does_not_breach() {
        // v_mv * i_ma / 1000 == TRACER_P_MAX_MW exactly, current alone
        // under its own limit.
        let i_ma = 500u16;
        let v_mv = 32_200u16;
        assert_eq!(v_mv as u32 * i_ma as u32 / 1000, TRACER_P_MAX_MW);
        assert!(!breach(v_mv, i_ma));
    }

    #[test]
    fn power_just_over_threshold_breaches_even_under_current_limit() {
        // 32_201 mV still truncates to exactly 16_100 mW, so use 32_202
        // to cross the integer-arithmetic boundary by one reported mW.
        let i_ma = 500u16;
        let v_mv = 32_202u16;
        assert!(v_mv as u32 * i_ma as u32 / 1000 > TRACER_P_MAX_MW);
        assert!(i_ma <= TRACER_I_MAX_MA);
        assert!(breach(v_mv, i_ma));
    }

    #[test]
    fn zero_current_never_breaches() {
        assert!(!breach(u16::MAX, 0));
    }

    #[test]
    fn max_inputs_do_not_overflow() {
        // v_mv and i_ma are both u16; the u32 intermediate product must
        // not overflow (65535 * 65535 fits in u32, but this pins that
        // assumption so a future type change gets caught here).
        let _ = breach(u16::MAX, u16::MAX);
    }
}
```

The threshold-boundary tests (`current_at_threshold_does_not_breach` /
`current_just_over_threshold_breaches`, and the power pair) are the ones
that would actually catch a `>` vs `>=` regression - that is the point of
this plan, keep them even if you trim the others for time.

**Verify**: `cd firmware/safety-checks && cargo test --locked` -> exit 0, 7 tests
passed.

### Step 4: add a CI step for the new crate

In `.github/workflows/firmware.yml`, add a second job (do not fold this
into the existing `build` job, since that job's `defaults.run.working-
directory` is `firmware/pipico_board` and this crate lives elsewhere):

```yaml
  safety-checks:
    name: safety-checks unit tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: firmware/safety-checks

    steps:
      - uses: actions/checkout@v4

      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt

      - name: Cache cargo registry and build artefacts
        uses: Swatinem/rust-cache@v2
        with:
          workspaces: firmware/safety-checks

      - name: Format check
        run: cargo fmt --check

      - name: Test
        run: cargo test --locked
```

No `targets: thumbv6m-none-eabi` here (unlike the existing `build` job) -
this crate builds and tests for the default host target, that is the
entire point.

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/firmware.yml'))"`
-> no exception. Full confirmation that the job actually runs and passes
needs the PR's CI checks (Step 5).

### Step 5: confirm nothing else references the moved items

```bash
grep -rn "TRACER_I_MAX_MA\|TRACER_P_MAX_MW\|Self::breach" firmware/pipico_board/src/
```

Expected: zero matches (everything now goes through `safety_checks::breach`
or the bare `breach` import). If anything else in `mode_curve_tracer.rs` or
another file in `firmware/pipico_board/src/` referenced these constants
directly (not just via `breach`), update those call sites too - re-export
`pub use safety_checks::{TRACER_I_MAX_MA, TRACER_P_MAX_MW};` from wherever
makes sense rather than duplicating the constants, but this was not
observed in the current source (both constants' only use, outside their
own definitions, is inside `breach` itself - confirmed via the grep in
"Current state" above) so this step is expected to be a no-op confirmation,
not new work.

## Test plan

The 7 tests in Step 3 are the entire test plan for this change - `breach`
is pure arithmetic on two `u16` inputs, so exhaustive boundary coverage
(each threshold, just under, just over) plus one degenerate case
(zero current) and one type-safety pin (no overflow at max inputs) fully
specifies its behavior. No integration test is needed or possible without
the board.

## Done criteria

- [ ] `firmware/safety-checks/` exists with `Cargo.toml` and `src/lib.rs`
      (function + constants + 7 tests)
- [ ] `firmware/safety-checks/Cargo.lock` is committed
- [ ] `firmware/pipico_board/Cargo.lock` records the new path dependency
- [ ] `cd firmware/safety-checks && cargo test --locked` passes, 7/7
- [ ] `cd firmware/safety-checks && cargo fmt --check` passes
- [ ] `cd firmware/pipico_board && cargo build --release --locked` passes
- [ ] `cd firmware/pipico_board && cargo clippy --release --locked -- -D warnings` passes
- [ ] `cd firmware/pipico_board && cargo fmt --check` passes
- [ ] `grep -rn "TRACER_I_MAX_MA\|TRACER_P_MAX_MW\|Self::breach" firmware/pipico_board/src/` returns nothing
- [ ] `.github/workflows/firmware.yml` has the new `safety-checks` job and is valid YAML
- [ ] `improve/2026-07-18/plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `mode_curve_tracer.rs`'s `breach` signature, or either threshold
  constant's value, has changed since this plan was written (per the
  drift check at the top) - re-derive the extraction against the new
  version rather than blindly applying this plan's diff.
- `firmware/pipico_board/Cargo.toml` has gained a `[workspace]` section
  (i.e. someone workspace-ified the firmware crates) since this plan was
  written - the path-dependency mechanics still work inside a workspace,
  but double check `cargo build --locked` in `pipico_board/` doesn't
  suddenly try to resolve `safety-checks` against a workspace-wide
  `Cargo.lock` in a way that breaks `--locked`.
- `cargo test` inside `firmware/safety-checks/` fails to use the host
  target for any reason (e.g. an unexpected inherited `.cargo/config.toml`
  from somewhere outside the repo, like `~/.cargo/config.toml`) - this
  plan's core premise (no interfering config) was verified for the repo
  tree only, not the executor's global cargo config.

## Maintenance notes

- If `mode_curve_tracer.rs` ever needs a different or additional safety
  cutoff (e.g. a voltage ceiling), add it to `safety-checks` the same way,
  not back into the firmware crate directly - that is the whole point of
  having pulled this logic out.
- `firmware/safety-checks` has zero dependencies today; keep it that way if
  at all possible so it keeps building instantly and testing on host stays
  trivial. If a future safety check genuinely needs `libm`-style float
  math, prefer a `no_std`-compatible, dependency-light crate over pulling
  in anything embassy/cortex-m-flavored - that would defeat the extraction.
- This is the first Rust crate in the repo that is neither the RP2040
  firmware nor the ESP32-C3 experiment - if a fourth ever shows up, this is
  also the first place worth considering whether `firmware/` should become
  a real Cargo workspace (shared `Cargo.lock`, one `cargo test --workspace`
  invocation). Not needed yet at three crates.
