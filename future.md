1) [x] (Done) since we have 4 RGB leds in the PICO, keep 1 as SPI communication status, and use the other 3 to track the 3 adc channels Vin, Vout, I. Blinking red when we are over the limit for that jumper setup. Green when we are below 50%, then yellow to orange to red for in between values.
2) [x] (Done) Implement dynamic config for jumpers, ron values on the pico. MAX31865 enable/disable on the fly. Hardware cutoffs (Imax, Vmax). Activate/deactivate power supply mode, Vout target, fixed duty.
   - Defaults:
     - Vin Divider Range: `Low` (~27.3 V max)
     - Vout Divider Range: `Low` (~27.3 V max)
     - $R_{\text{on}}$: `6` $\text{m}\Omega$ (IPP060N06N)
     - MAX31865: `false` (disabled)
     - $I_{\max}$ Cutoff: `1000` mA ($1.0\text{ A}$)
     - $V_{\max}$ Cutoff: `40000` mV ($40.0\text{ V}$)
     - Firmware Mode: `MppTracker` (0)
     - Power Supply Loop: `ClosedLoop` (0)
     - Power Supply $V_{\text{out}}$ Target: `5000` mV ($5.0\text{ V}$)
     - Power Supply Fixed Duty: `32768` ($50\,\%$)

