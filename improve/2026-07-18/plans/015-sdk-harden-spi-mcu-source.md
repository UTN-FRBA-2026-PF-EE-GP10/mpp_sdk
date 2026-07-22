# Plan 015: Harden `SpiMcuSource`

> Executor: run every verification command before moving on. On a STOP
> condition, stop and report. Update this plan's row in `README.md` when
> done.
>
> Drift check: written at commit `2aa9d35`. `git diff --stat
> 2aa9d35..HEAD -- mpp_sdk/io/spi_mcu.py` - if it changed, re-check the
> excerpt below before editing.

## Why

A follow-up `/improve` audit (2026-07-22) found `mpp_sdk/io/spi_mcu.py`'s
`SpiMcuSource` - the Pi-side HIL wrapper - has drifted from the firmware
it talks to, has zero test coverage, and has two smaller correctness gaps.
All four issues are small, live in one file, and are best fixed together
rather than as separate plans.

**The headline issue**: `SpiMcuSource`'s own default `v_scale`/`i_scale`
(`3.3 / 4095.0`) and docstring describe raw 12-bit ADC counts, but the
firmware (`firmware/pipico_board/README.md`'s "Sensing" section,
`firmware/pipico_board/src/main.rs`) now reports V in millivolts and I in
milliamperes, already calibrated on-device. The firmware README itself
prescribes constructing `SpiMcuSource(v_scale=1e-3, i_scale=1e-3)` -
meaning the class's *own* defaults, if someone follows its docstring
instead of the firmware README, are off by roughly 3300x. This feeds
`(V, I)` straight into MPPT algorithms driving a live SEPIC gate.

This was found by static review, not by a failure in the field - nobody
has hit it yet only because every current call site (bench scripts, the
firmware README's own example) manually overrides the scale factors. It's
a live footgun for the next person who doesn't.

## Current state (`mpp_sdk/io/spi_mcu.py`)

```python
class SpiMcuSource(SignalSource):
    """SignalSource backed by the RP2040 Pico over SPI (HIL mode).
    ...
    V and I are 12-bit ADC counts converted to physical units via the
    calibration scale/offset parameters.
    ...
    """

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        speed_hz: int = 4_000_000,
        mode: int = 0,
        v_scale: float = 3.3 / 4095.0,
        i_scale: float = 3.3 / 4095.0,
        v_offset: float = 0.0,
        i_offset: float = 0.0,
        initial_duty: float = 0.0,
    ) -> None:
        ...
        self._duty = float(initial_duty)
        self._v: float = 0.0
        self._i: float = 0.0

    def read(self) -> tuple[float, float]:
        """Return the (V, I) received in the last ``write()`` transaction."""
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        self._duty = max(0.0, min(1.0, duty_cycle))
        self._v, self._i = self._transact(self._duty)

    def __exit__(self, *_: object) -> None:
        self.soft_stop()
        self.close()
```

`tests/` has no `spi_mcu`/`SpiMcuSource` reference anywhere - none of this
is exercised by the test suite. `spidev` is not installed in the base dev
environment (it's the optional `[hardware]` extra), so any new test must
not require a real import of `spidev` to run in CI.

## Scope

**In scope**: `mpp_sdk/io/spi_mcu.py` only, plus a new
`tests/test_spi_mcu.py`.

**Out of scope**: the SPI frame's CRC/checksum (tracked separately in
plan 014 - this plan's fixes are independent of and compatible with that
one landing later); `scripts/spi_test.py` (already has the correct
`V_SCALE`/`I_SCALE`/`SPEED_HZ`, not part of this gap); any firmware
change.

## Steps

### Step 1: Fix the default scale factors and docstring

Change `v_scale`/`i_scale` defaults from `3.3 / 4095.0` to `1e-3`, change
`speed_hz`'s default from `4_000_000` to `1_000_000` (matching
`scripts/spi_test.py`'s bench-validated speed - 8 MHz is documented as
unreliable on this hardware, 4 MHz has no supporting bench evidence
either way). Rewrite the docstring's "V and I are 12-bit ADC counts..."
sentence to describe the actual wire format: calibrated millivolts/
milliamperes as saturating u16, matching
`firmware/pipico_board/README.md`'s "Sensing" section wording.

**Verify**: `uv run ruff check mpp_sdk/io/spi_mcu.py && uv run ruff format
--check mpp_sdk/io/spi_mcu.py` exit 0.

### Step 2: Fix `__exit__`'s teardown-leak

Wrap `soft_stop()` and `close()` in try/finally so a raised exception from
`soft_stop()` (e.g. a real SPI bus fault during teardown - plausible per
plan 014's documented on-target frame-corruption behavior) doesn't leak
the `/dev/spidevX.Y` file descriptor and doesn't mask whatever exception
was already propagating out of the `with` block.

```python
def __exit__(self, *_: object) -> None:
    try:
        self.soft_stop()
    finally:
        self.close()
```

**Verify**: same lint/format command as step 1.

### Step 3: Fix `read()`-before-`write()`

`read()` currently returns `(0.0, 0.0)` before any `write()` has happened,
indistinguishable from a real "panel disconnected" reading (this gap
was carried over from the 2026-07-06 audit and is still live). Add an
internal flag; raise `RuntimeError("SpiMcuSource.read() called before the
first write()")` if `read()` is called before `write()` has run at least
once. Update the class docstring's usage example if it implies otherwise
(check whether the example calls `read()` first - if so, fix the example
too, don't just fix the code and leave a contradicting docstring).

**Verify**: same lint/format command; also `uv run pytest -q` (whole
suite, in case anything indirectly relies on the old `(0.0, 0.0)`
default - grep `tests/` for `SpiMcuSource` first to check, expect no
hits per the audit).

### Step 4: Add `tests/test_spi_mcu.py`

`spidev` is a real Linux-only C-backed module and isn't installed in the
base dev environment - do not `import spidev` directly in the test. Two
options, pick whichever is less code:

1. Inject a fake module into `sys.modules["spidev"]` before importing
   `mpp_sdk.io.spi_mcu` (a minimal `SpiDev`-like class with `open`,
   `max_speed_hz`, `mode`, `xfer2`, `close`), or
2. `monkeypatch.setattr` on `SpiMcuSource` after construction to replace
   `self._spi` with a fake object, bypassing the need to fake the whole
   module - only works if you restructure `__init__` minimally to allow
   it, prefer option 1 if that restructuring would touch more than a line
   or two.

Cover, following this repo's existing test style (see
`tests/test_sources.py` for the `SignalSource`-family pattern):

- Byte-order round-trip: a known duty float encodes to the right
  `DUTY_H`/`DUTY_L` bytes and a known fake `rx` response decodes to the
  right `(V, I)` given the new `1e-3` default scale.
- Duty clamping at `0.0`, `1.0`, and out-of-range inputs (`-0.5`, `1.5`).
- `read()` raises before any `write()`, and returns the right values
  after one.
- `__exit__` calls `close()` even if a fake `soft_stop()`/`write()` raises
  (patch `_transact` to raise, assert the fake SPI's `close` was still
  called).

**Verify**: `uv run pytest -q tests/test_spi_mcu.py` and the full `uv run
pytest -q` both pass; `uv run ruff check .` clean.

## Done criteria

- [ ] `v_scale`/`i_scale` default to `1e-3`, `speed_hz` defaults to
      `1_000_000`, docstring describes mV/mA not raw ADC counts
- [ ] `__exit__` uses try/finally, `close()` always runs
- [ ] `read()` before first `write()` raises instead of returning `(0,0)`
- [ ] `tests/test_spi_mcu.py` exists and covers the four items in step 4,
      without requiring the real `spidev` package to be installed
- [ ] `uv run pytest -q` and `uv run ruff check .` both exit 0
- [ ] `improve/2026-07-18/plans/README.md` row updated

## STOP conditions

- Changing `read()`'s before-first-write behavior turns out to break an
  existing caller that relies on `(0.0, 0.0)` (check
  `improve/2026-07-18/plans/003-bench-duty-sweep.md` and any other plan
  referencing `SpiMcuSource` for an assumption like this before changing
  the behavior) - if so, report and propose a non-breaking alternative
  (e.g. a `has_measurement` property) instead of silently picking one.
- The fake-`spidev` approach in step 4 turns out to need more than ~20
  lines of scaffolding to work - STOP and report; that would suggest
  `SpiMcuSource`'s constructor needs a small refactor (e.g. accept an
  injected transport) to be reasonably testable, which is a slightly
  bigger change than this plan scoped and worth a operator decision.

## Maintenance notes

- If plan 014 (SPI frame CRC) lands after this plan, `_transact()` will
  need a corresponding update to verify/strip the checksum byte - not this
  plan's job, just noting the interaction point for whoever picks up 014.
- The `speed_hz` default change (4 MHz -> 1 MHz) only affects the
  *default*; nothing currently constructs `SpiMcuSource()` without an
  explicit `speed_hz` in the codebase today (checked during the audit),
  so this is a safety-net fix, not a behavior change for existing code.
