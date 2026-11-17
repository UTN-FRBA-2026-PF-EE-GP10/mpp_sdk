# mppt-po

Fixed-step Perturb & Observe for the RP2040, as a `no_std` crate with no dependencies.
It is a port of `mpp_sdk/algorithms/perturb_observe.py`.

- API: `PerturbAndObserve::new(Config)` and `step(v_mv: u16, i_ma: u16) -> u16` (next duty).
- Integer math only. Power is `mV * mA` in a `u32`.
- Default config: start 32768, step 66 (about 0.001), min 3277 (0.05), max 62258 (firmware `DUTY_MAX`).
- Raising duty lowers the panel voltage (SEPIC).

## Cross-check with Python

- `scripts/gen_po_traces.py` runs the Python reference on three simulated sources.
  It writes `tests/fixtures/*.csv` (`v_mv,i_ma,duty_u16`).
- All V and I values are rounded to whole mV and mA, as on the Pico.
- `tests/replay.rs` feeds the V and I rows to the Rust code.
  The duty must be **exactly equal** on every row (tolerance 0).
  Duty and step are whole u16 counts, so the float reference has no rounding error.
- `tests/test_gen_po_traces.py` fails if the committed fixtures differ from the script output.
- Regenerate with `uv run python scripts/gen_po_traces.py`.

```sh
cargo test --locked
```

## Size and time

Built for `thumbv6m-none-eabi` with the `pipico_board` release profile (`opt-level = "z"`, fat LTO).
The probe is a small binary that calls `step` in a loop.
Measured with `arm-none-eabi-size` and `objdump`.

| Item | Result | Budget |
| --- | --- | --- |
| Flash (code of `step` and a loop) | 116 bytes | 16 KB |
| Static RAM | 24 bytes of state (struct size), 0 bytes of globals | 4 KB |
| Time per step | about 36 instructions on the worst path, under 1 us at 125 MHz | 1 ms |

- Config and inputs are runtime values in the probe, so the numbers are not folded.
  `step` is 108 bytes, `new` is 46 bytes, 186 bytes in total.
- The time is an **estimate**: a count of Cortex-M0+ instructions on the longest path in the disassembly.
  Measure the real time on the Pico.
