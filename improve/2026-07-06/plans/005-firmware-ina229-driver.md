# Plan 005: Firmware INA229 driver - real V/I acquisition replacing the simulated ADC task

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `improve/2026-07-06/plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c647b61..HEAD -- firmware/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Prerequisites - confirm BEFORE starting**: (1) network access to the
> INA229 datasheet (<https://www.ti.com/lit/ds/symlink/ina229.pdf>) - the
> register constants in step 3 must be verified against it and cannot be
> verified offline; (2) a channel to the operator for the R_shunt value
> (step 1). Missing either one is an immediate STOP - report it as
> "blocked: missing prerequisite" rather than starting steps 2-4 on
> unverified constants.

## Status

- **Priority**: P1 (operator's active work area)
- **Effort**: L (driver + acquisition task + on-target bring-up)
- **Risk**: MED (hardware bring-up; wrong calibration silently corrupts every
  HIL measurement)
- **Depends on**: none (independent of plans 001-004)
- **Category**: direction / feature
- **Planned at**: commit `c647b61`, 2026-07-06 (amended after cold-read review)

## Why this matters

The firmware's `adc_task` is a placeholder: it feeds the SPI link to the
Raspberry Pi with pseudo-random numbers from an LCG. Every HIL experiment is
therefore fiction until real sensing lands. The board carries a TI INA229
(20-bit, SPI power monitor) measuring the panel-side bus voltage and shunt
current - exactly the `(V, I)` pair the MPPT algorithms consume. This plan
implements its driver and wires real measurements into the existing
Pico -> Pi frame, preserving the Pi-side `SpiMcuSource` contract.

## Current state

### Firmware (all in `firmware/`)

- `src/main.rs:20-37` - the placeholder to replace:

  ```rust
  pub static DUTY: AtomicU16 = AtomicU16::new(0x8000); // 50 % initial
  pub static SIM_V: AtomicU16 = AtomicU16::new(2048);
  pub static SIM_I: AtomicU16 = AtomicU16::new(512);

  fn lcg(s: &mut u32) -> u16 { /* pseudo-random 12-bit */ }

  #[embassy_executor::task]
  async fn adc_task() {
      let mut rng: u32 = 0xDEAD_BEEF;
      loop {
          SIM_V.store(2000 + (lcg(&mut rng) & 0xFF), Ordering::Relaxed);
          SIM_I.store(500 + (lcg(&mut rng) & 0x7F), Ordering::Relaxed);
          Timer::after_millis(10).await;
      }
  }
  ```

- `src/main.rs:50-54` - peripherals: PIO0 implements the SPI **slave** link
  to the Pi on GPIO10-13 (so the RP2040's SPI0/SPI1 peripheral blocks are
  both free; only the pins 10-13 are taken); tasks spawned:

  ```rust
  let sm = spi_slave_pio::init(p.PIO0, p.PIN_10, p.PIN_11, p.PIN_12, p.PIN_13);
  let dma_ch = dma::Channel::new(p.DMA_CH0, DmaIrqs);
  spawner.spawn(adc_task().unwrap());
  spawner.spawn(spi_slave_pio::spi_pio_task(sm, dma_ch).unwrap());
  ```

  Note the `.unwrap()` placement inside `spawn(...)` - the idiomatic
  embassy form is `spawner.spawn(task(...)).unwrap()`, and `.unwrap()` on a
  `SpawnToken` normally does not compile. Do not assume either way: run
  `cargo build --release` FIRST on the untouched tree to learn the actual
  baseline. If it fails on these lines, fixing them to the idiomatic form
  is in scope and should be your first commit; if it builds, change them
  anyway when you rewire the spawns in step 4.

- `src/spi_slave_pio.rs:98-159` - the consumer of the measurements:
  `build_tx_frame(v: u16, i: u16)` packs big-endian u16 V then u16 I into a
  12-byte frame; `spi_pio_task` loads `SIM_V` / `SIM_I` once per frame
  exchange. **This is the only integration point the driver must feed.**
- `Cargo.toml` - embassy from git (pinned by the committed `Cargo.lock`):
  `embassy-rp` (features `rp2040`, `time-driver`, ...), `embassy-time`,
  `embassy-sync`, `embassy-futures`, `defmt` + `defmt-rtt`, `panic-probe`.
  No embedded-hal SPI-bus-sharing crate; do not add one (see design).
- `README.md` GPIO table (nets from the KiCad project, `hardware/`):

  | GPIO | Net | Role for this plan |
  |------|-----|--------------------|
  | 16 | SPI0_MISO | INA229 SDO -> Pico |
  | 17 | SPI0_CS1 | INA229 chip select (net `CS_INA`) |
  | 18 | SPI0_SCK | SPI0 clock |
  | 19 | SPI0_MOSI | Pico -> INA229 SDI |
  | 20 | SPI0_CS2 | MAX31865 chip select (net `CS_TP100`) - keep HIGH |
  | 21 | INA_OOR_Alert | INA229 ALERT output (input to Pico) |
  | 22 | DRDY_TMP | MAX31865 (PT100) data-ready - NOT this plan |

  The CS mapping was traced through the top-level sheet wiring in
  `hardware/Proyecto0.1V.kicad_sch` (SPI0_CS1 -> CS_INA,
  SPI0_CS2 -> CS_TP100) and is recorded in the `firmware/README.md`
  GPIO table.

### Hardware (from `hardware/untitled.kicad_sch`, the sensing sheet)

- One INA229 (`Sensor_Energy:INA229`, datasheet
  <https://www.ti.com/lit/ds/symlink/ina229.pdf>): VBUS side on net `VPWR`
  (panel/input power rail), shunt on nets `Isense+` / `Isense-`, chip select
  net `CS_INA`, alert net `INA_OOR_Alert`.
- One MAX31865 (PT100 RTD front end) on the same SPI0 bus, chip select net
  `CS_TP100`, data-ready `DRDY_PT100`. Out of scope here, but the bus wiring
  must anticipate it (manual per-device CS, bus not consumed by one driver).
- One INA281 analog current-sense amplifier feeding `ADC_Input_Curr`
  (GPIO28) - an analog redundancy path read by the RP2040's own ADC. Out of
  scope for this plan (see maintenance notes).
- **Unresolved at planning time - resolve before coding (step 1):**
  the shunt resistor value (the schematic shows generic `R_US` values,
  not ohms).

### Pi side (contract to preserve)

`mpp_sdk/io/spi_mcu.py` - `SpiMcuSource` sends duty as u16 and reads V/I as
u16, converting with constructor parameters `v_scale` / `i_scale`
(defaults assume raw 12-bit ADC counts; they are parameters precisely so
calibration can move into the firmware). The 12-byte frame layout must not
change.

## Design decisions (already made - follow them)

1. **Units on the wire**: the firmware sends V in **millivolts** and I in
   **milliamperes** as u16 (saturating; negative clamps to 0). Rationale:
   65535 mV = 65.5 V ceiling covers V_IN_MAX = 40 V with margin, keeps the
   frame layout untouched, and the Pi side just constructs
   `SpiMcuSource(v_scale=1e-3, i_scale=1e-3)`. Calibration lives in ONE
   place (the firmware, next to the sensor).
2. **Bus sharing**: keep it simple and dependency-free - the acquisition
   task exclusively owns the `Spi<'static, SPI0, Async>` instance plus one
   `Output` per chip select. The INA229 driver takes `&mut Spi` and
   `&mut Output` per transaction (a plain `struct Ina229` holding
   calibration state and methods like
   `async fn read_register(&mut self, spi: &mut ..., cs: &mut Output<'_>, ...)`
   or owning both - either is fine as long as the MAX31865 can later share
   the bus by living in the same task). Do NOT add `embassy-embedded-hal`
   or `embedded-hal-bus` for this.
3. **Keep the simulated path**: gate the LCG task behind a cargo feature
   `sim-adc` so bench-less development (and the existing
   `firmware/script_test.png` demo flow) still works:
   `cargo run --release --features sim-adc`. Default build = real driver.
4. **Naming**: rename `SIM_V` / `SIM_I` to `MEAS_V_MV` / `MEAS_I_MA` (they
   now carry physical millivolts/milliamps, and both the real and `sim-adc`
   tasks write them). Update `spi_slave_pio.rs` uses (lines 30, 129-131,
   154-155) and the defmt log line accordingly.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Build | `cd firmware && cargo build --release` | exit 0 |
| Build (sim path) | `cd firmware && cargo build --release --features sim-adc` | exit 0 |
| Flash + logs (probe attached) | `cd firmware && cargo run --release` | defmt log stream in terminal |
| Format | `cd firmware && cargo fmt --check` | exit 0 |
| Pi-side end-to-end (bench) | `uv run scripts/spi_test.py` (on the Pi, wired per firmware/README.md) | duty/V/I round-trip prints |

## Suggested executor toolkit

- INA229 datasheet: <https://www.ti.com/lit/ds/symlink/ina229.pdf> - read
  sections on the SPI frame format, the register map, and SHUNT_CAL before
  step 3. Register facts below are from planning-time knowledge; **verify
  each against the datasheet and correct the plan's numbers if they
  disagree** (datasheet wins, note the correction in your report).
- KiCad (or grep on the `.kicad_sch` s-expressions) for step 1.

## Scope

**In scope**:

- `firmware/src/ina229.rs` (create)
- `firmware/src/main.rs` (replace adc_task wiring, spawn the new task)
- `firmware/src/spi_slave_pio.rs` (rename of the shared atomics only)
- `firmware/Cargo.toml` (add the `sim-adc` feature; no new dependencies)
- `firmware/README.md` (document the mV/mA wire units and the feature flag)

**Out of scope** (do NOT touch):

- The PIO SPI-slave implementation and the 12-byte frame protocol.
- MAX31865 / PT100 driver (future work; only leave the bus shareable).
- The RP2040 on-chip ADC channels (GPIO26-28, INA281 path) - separate,
  later redundancy work.
- `mpp_sdk/io/spi_mcu.py` - the mV/mA choice deliberately requires zero
  code change there (constructor args at the call site).
- Moving PWM off `PIN_25` onto the board's real gate net (GPIO15) - a known
  separate placeholder, tracked in the plans index, not here.

## Git workflow

- Branch: `feat/fw-ina229`
- Single-line conventional commits, e.g. `feat(fw): INA229 driver over SPI0`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pin down the remaining hardware unknown

1. CS mapping: already resolved and documented - GPIO17 (`SPI0_CS1`) is the
   INA229 (`CS_INA`), GPIO20 (`SPI0_CS2`) is the MAX31865 (`CS_TP100`); see
   the `firmware/README.md` GPIO table. Sanity-check the table against
   `hardware/Proyecto0.1V.kicad_sch` if anything on the bus misbehaves.
2. Shunt value: get R_shunt in ohms from the BOM/board (the schematic value
   fields are generic `R_US`). Ask the operator if not discoverable.

Record R_shunt in `firmware/README.md` (a short "Sensing" section) and as a
constant in `ina229.rs`.

**Verify**: R_shunt written down with its source. If it cannot be
determined, STOP.

### Step 2: Rename the shared atomics and add the sim-adc feature

- `SIM_V`/`SIM_I` -> `MEAS_V_MV`/`MEAS_I_MA` in `main.rs` and
  `spi_slave_pio.rs`.
- `Cargo.toml`: add `[features]\nsim-adc = []`.
- Wrap `adc_task` (the LCG one) in `#[cfg(feature = "sim-adc")]` and its
  spawn likewise; adjust the initial atomic values to plausible mV/mA
  (e.g. 0 each).

**Verify**: `cargo build --release --features sim-adc` exit 0 AND
`cargo build --release` exit 0 (the latter will warn about the not-yet-used
DMA/unused items until step 4 - warnings acceptable, errors not).

### Step 3: Implement firmware/src/ina229.rs

Driver skeleton (verify register facts per the toolkit note):

- SPI transaction: first byte carries the 6-bit register address and the
  read/write bit; reads then clock out the register contents MSB-first.
  Registers (16-bit unless noted): `CONFIG=0x00`, `ADC_CONFIG=0x01`,
  `SHUNT_CAL=0x02`, `VSHUNT=0x04` (24-bit), `VBUS=0x05` (24-bit),
  `DIETEMP=0x06`, `CURRENT=0x07` (24-bit), `DIAG_ALRT=0x0B`,
  `MANUFACTURER_ID=0x3E` (reads ASCII "TI", 0x5449),
  `DEVICE_ID=0x3F`.
- 24-bit conversion registers are left-justified: the 20-bit signed value
  sits in bits 23:4 - shift right 4 and sign-extend from bit 19.
- Scaling: `VBUS` LSB = 195.3125 uV. `CURRENT` LSB = `CURRENT_LSB` chosen at
  calibration: `CURRENT_LSB = I_max / 2^19` with `I_max = 1.0 A` (the
  board's rated string current, `harness/panel_config.py:28`), and
  `SHUNT_CAL = 13107.2e6 * CURRENT_LSB * R_shunt` (ADCRANGE = 0; apply the
  datasheet's x4 factor if you select ADCRANGE = 1).
- API sketch:

  ```rust
  pub struct Ina229 { current_lsb_na: i64 /* or f32 */, ... }
  impl Ina229 {
      pub async fn init(&mut self, spi, cs) -> Result<(), Error>  // ID check + ADC_CONFIG + SHUNT_CAL
      pub async fn read_vbus_mv(&mut self, spi, cs) -> Result<u16, Error>
      pub async fn read_current_ma(&mut self, spi, cs) -> Result<u16, Error>  // saturating, clamps < 0 to 0
  }
  ```

  Keep the raw->physical math in pure `fn` helpers (unit-testable by
  inspection, no peripherals in their signatures).
- SPI config: start at 1 MHz; mode per datasheet (TI power monitors
  typically clock data out on SCLK falling and sample on rising - confirm
  CPOL/CPHA in the datasheet timing diagram before choosing the embassy
  `spi::Config` polarity/phase).

**Verify**: `cargo build --release` exit 0; `cargo fmt --check` exit 0.

### Step 4: Acquisition task and wiring

In `main.rs`:

- Construct `embassy_rp::spi::Spi::new(p.SPI0, ...)` async with the pins
  from the table (SCK GPIO18, MOSI GPIO19, MISO GPIO16) and two
  `Output::new(...)` chip selects (GPIO17, GPIO20; both idle HIGH,
  the unused one stays high so the MAX31865 never floats onto the bus).
- New `#[embassy_executor::task] async fn ina_task(...)`:
  1. `init()`; on ID mismatch log `defmt::error!` and retry with backoff
     (do not panic - the Pi link should keep running and report zeros).
  2. Loop at 1 ms (`Timer::after_millis(1)`, matching the SDK's
     `CONTROL_PERIOD_MS = 1.0`): read VBUS and CURRENT, convert, store into
     `MEAS_V_MV` / `MEAS_I_MA` with `Ordering::Relaxed`.
- Spawn `ina_task` in the default build, LCG task only under `sim-adc`.
- Keep a periodic `defmt::info!("V={} mV I={} mA", ...)` (1 Hz, not 1 kHz -
  RTT flooding stalls the target).

**Verify**: `cargo build --release` exit 0 with **zero warnings** about
unused items; `cargo build --release --features sim-adc` exit 0.

### Step 5: On-target bring-up (needs the board + probe)

1. `cargo run --release` with the debug probe attached (flashing procedure:
   `firmware/README.md`, Option A).
2. defmt log shows the manufacturer ID check passing (expect 0x5449) and a
   V/I line.
3. Plausibility: with the panel (or a bench supply through the input) at a
   known voltage, logged mV within +/- 2 % of a multimeter reading at the
   INA229 VBUS pin; with no load, mA reads near 0 (|I| < a few mA of noise).
4. End-to-end HIL: from the Pi wired per `firmware/README.md`, run
   `uv run scripts/spi_test.py` and confirm the same values arrive
   (construct the source with `v_scale=1e-3, i_scale=1e-3` if the script
   uses defaults - adapt the script invocation, not the frame).

**Verify**: each numbered observation logged in your report with the actual
values seen.

## Test plan

No host-runnable test infra exists for the firmware crate (no_std, embassy
git deps), and adding one is out of scope. The test surface is:

- Build gates in every step (both feature configurations).
- The pure conversion helpers in `ina229.rs` carry doc comments with worked
  examples (raw register value -> mV/mA) so a reviewer can check the math
  against the datasheet by hand.
- The step 5 bring-up checklist against a multimeter.

## Done criteria

- [ ] `cargo build --release` and `--features sim-adc` both exit 0, no
      warnings
- [ ] `firmware/src/ina229.rs` exists; ID check, SHUNT_CAL write and
      VBUS/CURRENT reads implemented; no new crates in `Cargo.toml`
- [ ] Frame protocol and `spi_slave_pio.rs` logic unchanged apart from the
      atomic rename
- [ ] `firmware/README.md` documents wire units (mV/mA), R_shunt, CS
      mapping and the `sim-adc` feature
- [ ] On-target checklist (step 5) completed and reported, or explicitly
      reported as "blocked: no hardware on this machine" with steps 1-4 done
- [ ] `improve/2026-07-06/plans/README.md` status row updated

## STOP conditions

- The step 1 unknown (R_shunt) cannot be resolved.
- The datasheet contradicts the register map / scaling constants above in a
  way that changes the API shape (not just a constant).
- MANUFACTURER_ID reads neither 0x5449 nor all-zeros/all-ones (wrong wiring
  assumption - report the observed value, do not brute-force addresses).
- Feeding real values requires changing the 12-byte frame or
  `mpp_sdk/io/spi_mcu.py` - the design above should make that unnecessary.

## Maintenance notes

- The MAX31865 (PT100) driver comes next and shares SPI0: keep it in the
  same acquisition task, second CS already provisioned in step 4.
- The INA281 -> on-chip-ADC path (GPIO28) is the sanity cross-check for the
  INA229 current reading; when implemented, log both and alert on
  disagreement.
- `INA_OOR_Alert` (GPIO21) is wired but unused after this plan; a follow-up
  can configure DIAG_ALRT limits (e.g. bus overvoltage at 40 V = the SEPIC
  V_in_max) and wire the GPIO to a fast PWM shutdown.
- Reviewer focus: the sign-extension of the 24-bit registers and the
  SHUNT_CAL arithmetic - both fail silently with plausible-looking numbers.
