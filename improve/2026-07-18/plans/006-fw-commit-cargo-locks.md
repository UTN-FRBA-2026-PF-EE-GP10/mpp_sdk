# Plan 006: Commit the firmware Cargo.lock files and enforce them in CI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-18/plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 6fc47a0..HEAD -- firmware/pipico_board/.gitignore firmware/esp32c3-bpw34/.gitignore .github/workflows/firmware.yml`
> On any change, re-check the excerpts below; mismatch = STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: deps
- **Planned at**: commit `6fc47a0`, 2026-07-18

## Why this matters

`firmware/pipico_board/Cargo.toml` pulls all five embassy crates from git
with **no `rev=` pin**, and both firmware crates **gitignore their
`Cargo.lock`** - so no lockfile exists anywhere in the tree
(`git ls-files | grep Cargo.lock` returns nothing). Every build, including
CI, re-resolves embassy against whatever its default branch is at that
moment: non-reproducible firmware binaries and silent breakage on any
upstream change. These are binary crates - committing the lock is the
standard Rust practice, and an earlier audit explicitly assumed it was
already the case ("reproducibility is covered by the committed
Cargo.lock") - that assumption was false.

## Current state

- `firmware/pipico_board/.gitignore` (entire file):

  ```text
  target/
  Cargo.lock
  ```

- `firmware/esp32c3-bpw34/.gitignore` line 4: `/Cargo.lock`
- `firmware/pipico_board/Cargo.toml:13-17`: `embassy-executor`,
  `embassy-time`, `embassy-rp`, `embassy-sync`, `embassy-futures`, all
  `{ git = "https://github.com/embassy-rs/embassy", ... }`, no `rev`.
- `.github/workflows/firmware.yml` builds `firmware/pipico_board` with
  `cargo fmt --check`, `cargo build --release`, and
  `cargo build --release --features sim-adc` - none use `--locked`.
- Local `Cargo.lock` files likely already exist on disk (the crates have
  been built on this machine); they are just untracked.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Build (generates/refreshes lock) | `cd firmware/pipico_board && cargo build --release` | exit 0 |
| Locked build | `cargo build --release --locked` | exit 0 |
| ESP32 lock check | `ls firmware/esp32c3-bpw34/Cargo.lock` | file exists |

## Scope

**In scope**:

- `firmware/pipico_board/.gitignore` (remove the `Cargo.lock` line)
- `firmware/esp32c3-bpw34/.gitignore` (remove the `/Cargo.lock` line)
- `firmware/pipico_board/Cargo.lock` (commit)
- `firmware/esp32c3-bpw34/Cargo.lock` (commit)
- `.github/workflows/firmware.yml` (add `--locked` to the two build steps)

**Out of scope** (do NOT touch):

- `Cargo.toml` dependency edits, including adding `rev=` pins - noted as
  optional belt-and-suspenders in Maintenance, NOT part of this plan (the
  lock alone fixes reproducibility, and pinning revs is a maintenance-
  cadence decision for the operator).
- The esp32c3 crate's build config or CI (it has no CI job; a separate
  decision).

## Steps

### Step 1: Un-ignore and commit the lockfiles

Remove the `Cargo.lock` entries from both `.gitignore` files. Run
`cargo build --release` in `firmware/pipico_board` to ensure its lock is
fresh. For `firmware/esp32c3-bpw34`: if `Cargo.lock` exists on disk,
commit it as-is (do NOT build this crate - the ESP-IDF toolchain build is
heavy and unnecessary for locking); if it does not exist, run only
`cargo generate-lockfile` there (resolves deps without compiling).

**Verify**: `git status` shows both `.gitignore` edits and both
`Cargo.lock` files as new; `git check-ignore firmware/pipico_board/Cargo.lock`
exits 1 (not ignored).

### Step 2: Enforce the lock in CI

In `.github/workflows/firmware.yml`, change both build steps to
`cargo build --release --locked` and
`cargo build --release --locked --features sim-adc`.

**Verify**: locally, `cd firmware/pipico_board && cargo build --release --locked`
exits 0.

## Test plan

CI itself is the test: the firmware workflow on the PR must pass with
`--locked` (proving the committed lock matches the manifests).

## Done criteria

- [ ] `git ls-files | grep Cargo.lock` lists both firmware lockfiles
- [ ] `cargo build --release --locked` exits 0 in pipico_board
- [ ] firmware.yml uses `--locked` on both build steps
- [ ] No other files modified
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- `cargo build` wants to UPDATE the lock in a way that changes embassy to
  a revision that breaks the build: report the resolution diff instead of
  force-fixing.
- The esp32c3 crate has no lock on disk AND `cargo generate-lockfile`
  fails there (ESP-IDF env issues): commit only the pipico_board lock,
  leave the esp32 gitignore line in place, and note it in the status row.

## Maintenance notes

- Refresh cadence: bump the lock deliberately (e.g. `cargo update -p
  embassy-rp`) when pulling upstream fixes, never implicitly.
- Optional follow-up for the operator: add `rev = "<sha>"` pins matching
  the committed lock to `Cargo.toml` as belt-and-suspenders.
- If a future CI job builds the esp32c3 crate, give it `--locked` too.
