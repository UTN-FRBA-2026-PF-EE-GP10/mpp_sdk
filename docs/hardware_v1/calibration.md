# ADC calibration (hardware v1)

The board measures V in with the INA229, and V out with the RP2040's
on-chip ADC. The INA229 needs no calibration. The on-chip ADC does, and
this page explains why and how.

## What it does

The ADC gives a raw code (0 to 4095) for the voltage on its pin. The
firmware turns that code into volts with one straight line:

```text
pin voltage = 0.79322 mV x (code - 13.19)
```

Then it multiplies by the divider ratio (8.5 on the `Low` range) to get the
voltage at the terminals.

The two numbers are the **gain** (0.79322 mV per code) and the **zero**
(13.19 codes). They are in `firmware/pipico_board/src/adc_cal.rs`. The
same line is used for `ADC_PWR`, `ADC_VOUT` and `ADC_Input_Curr`: they
share one ADC.

## Why it is needed

The ADC reads about **13 codes at 0 V**. On the `Low` range that is about
**90 mV at the terminals**. Before the calibration:

- V out showed 85-95 mV with the converter off and 0 V on the output.
- Below 1.2 V, readings were 6-16 % too high.
- From 3 V to 18 V, readings were already within 0.5 %.

So the calibration matters most near 0 V and at low voltage. Measured on
2026-09-19, against a multimeter:

| Test | Meter | ADC_VOUT |
|------|-------|----------|
| Output at 0 V, converter off | 0.000 V | 0.000 V |
| Supply on the output | 5.030 V | 5.006 V |
| Converter switching, D = 0.45, 5 V in, 10 Ohm load | 3.2 V | 3.221 V |
| Converter switching, D = 0.40, 12 V in, 10 Ohm load | 7.00 V | 7.006 V |

!!! note "Remaining error"
    The RP2040 ADC has uneven code steps near codes 512 and 1536 (errata
    RP2040-E11; about 3.4 V and 10.2 V at the terminals on `Low`). A
    straight line cannot follow them: expect up to about 50 mV of error
    there. For better accuracy, use the INA229 (V in only).

## When to redo it

- After you change the ADC range (`ADC_DIVIDER_RANGE` and its jumpers).
  For example, `Mid` for two panels in series.
- On a different board, or after you change the Pico.

## How to redo it (about 15 minutes)

You need a bench power supply and a multimeter.

1. **Keep the duty at 0.** Leave the workbench server idle. Do not press
   **Start Measurement** or **Start run**.
2. **Connect the supply to the input**, J3: + on pin 1 or 2, − on pin 3 or
   4. Set the current limit to 50 mA.
3. **Read the log** with the debug probe
   (`cargo run --release` in `firmware/pipico_board`). Once per second the
   firmware prints a line like this:

    ```text
    ADC cal: PWR raw=1495.4 ... | INA229 V=9970 mV
    ```

    `raw` is the ADC code, and `INA229 V` is the true voltage.

4. **Take two points, far apart.** One low (1-2 V) and one near the top
   of the range (18 V on `Low`). Hold each voltage for 10 s and write down
   `raw` and `INA229 V`. Do not use two high points: the zero then comes
   out wrong.
5. **Calculate the two numbers.** With points (c1, V1) and (c2, V2), in
   codes and terminal mV, and the divider ratio R (8.5 on `Low`):

    ```text
    slope = (V2 - V1) / (c2 - c1)       terminal mV per code
    zero  = c1 - V1 / slope             codes
    gain  = slope / R                   pin mV per code
    ```

    Example (2026-09-19): (192.4, 1200) and (2677.6, 17970) give
    slope 6.748, zero 14.6 and gain 0.7939. The numbers in the firmware
    come from a fit through all eight points taken that day; two points
    give almost the same line.

6. **Put them in `adc_cal.rs`**: `UV_X100_PER_CODE` is the gain in
   microvolts x 100 (0.7939 mV becomes 79390), `ZERO_CODE_X100` is the
   zero x 100 (14.6 becomes 1460). Build and flash.

## Check the result

Put the supply on the **output**, J4: + on pin 1 or 2, − on pin 3 or 4.
This is safe with the duty at 0: the output diode stops the supply from
feeding the converter. Compare `ADC_VOUT` in the log against the meter at
two or three voltages. It must agree within about 50 mV.

!!! danger "Never run the converter with no load"
    With nothing on the output, the SEPIC output rises far above the input:
    about 50 V at 10 % duty with 18 V in. To check V out while the converter
    switches, put a load resistor on the output (10 Ohm, 10 W) and use
    `scripts/duty_sweep.py`.
