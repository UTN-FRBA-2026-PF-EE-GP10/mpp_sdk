# Plan 003: Bench duty sweep into a 10 Ohm load

> Bench procedure, not a code change (one small Pi-side script is the only
> code). Needs plan 002 flashed on the target. Update this plan's row in
> `README.md` with the outcome, and file the measured table under `data/`.

## Why

First closed-chain validation of the whole power path: Pi commands duty
over SPI, RP2040 drives the SEPIC gate at 100 kHz, INA229 measures the
input side. Sweeping duty into a known resistive load checks the SEPIC
transfer function against theory and produces the project's first
efficiency numbers - before any panel or MPPT algorithm enters the loop.

## Setup

- Input: lab PSU (preferred - it has a current limit) or battery on the
  panel input (`VPWR`). Suggested `V_in = 12 V`, **PSU current limit
  1.0 A** (the inductor + shunt rating, `harness/panel_config.py`).
- Output: 10 Ohm power resistor on `VOUT` (rate it >= 10 W or heatsink
  it: worst case below is ~9.6 W).
- Multimeter on the output (the INA229 only sees the input side).
- Pi wired per `firmware/pipico_board/README.md` HIL table; probe
  attached for defmt logs if available.

## Theory to check against

SEPIC: `V_out = V_in * D / (1 - D)`. At `V_in = 12 V`, `R = 10 Ohm`:

| D | DUTY u16 | V_out theory | I_out | P_out |
|------|---------|--------------|--------|-------|
| 0.10 | 6554 | 1.33 V | 0.13 A | 0.2 W |
| 0.15 | 9830 | 2.12 V | 0.21 A | 0.4 W |
| 0.20 | 13107 | 3.00 V | 0.30 A | 0.9 W |
| 0.25 | 16384 | 4.00 V | 0.40 A | 1.6 W |
| 0.30 | 19661 | 5.14 V | 0.51 A | 2.6 W |
| 0.35 | 22938 | 6.46 V | 0.65 A | 4.2 W |
| 0.40 | 26214 | 8.00 V | 0.80 A | 6.4 W |
| 0.45 | 29491 | 9.82 V | 0.98 A | 9.6 W |

**Hard cap: D <= 0.45.** D = 0.50 already means 1.2 A output and 14 W -
past the 1 A rating. Real V_out will fall increasingly short of theory as
D rises (conduction + switching losses); that gap IS the efficiency
measurement, not an error.

## Steps

1. Write `scripts/duty_sweep.py` (Pi side): for each DUTY value in the
   table, command it via `SpiMcuSource(v_scale=1e-3, i_scale=1e-3)`, hold
   ~5 s, average the last 2 s of V_in/I_in readings, prompt the operator
   for the multimeter V_out, append a CSV row
   `(D, duty_u16, v_in, i_in, v_out, p_in, p_out, eta)`. Model it on
   `scripts/spi_test.py`.
2. Dry run at D = 0 with the PSU on: confirm V_in reads supply voltage,
   I_in ~ 0, V_out ~ 0.
3. Run the sweep upward, one step at a time. At each step, sanity-check
   I_in against the PSU's own readout before advancing. Stop early if
   anything smells (see STOP).
4. Save the CSV under `data/bench/duty_sweep_10R_<date>.csv` and add a
   short findings note (max deviation from theory, eta vs D curve shape)
   to `data/README.md`.

## Done criteria

- [ ] CSV with all 8 rows (or a documented early stop)
- [ ] Measured V_out within ~15 % of theory at low D (<= 0.25); monotonic
      eta curve at higher D
- [ ] Findings note committed with the CSV

## STOP conditions

- PSU current limit trips, or I_in exceeds 1.0 A before D = 0.45: back
  off one step and end the sweep there.
- V_out does not track D at all at low duty: gate likely not switching -
  go back to plan 002 step 2 (scope GPIO15) before touching power again.
- Any component (MOSFET, diode, coupling caps, load resistor) too hot to
  touch: stop, let it cool, note the duty at which it happened.
- Audible whine or visible ringing that changes with D: note it and stop;
  snubber/layout review before pushing power further.
