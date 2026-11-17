# SEPIC settling time

Why the step response was slow, what fixed it, and the measured result.

## Cause

- A step on the duty cycle took about 100 ms to settle at a 50 kHz switching
  frequency. That is about 5000 switching cycles (20 us each).
- The main cause was the $1000\,\mu\text{F}$ input capacitor in parallel
  with the panel. The panel has limited current, so it charges and
  discharges that capacitor slowly.
- You cannot remove the input capacitor. Without it the panel sees the raw
  50 kHz ripple and the ADC readings are distorted. A value of
  $22 - 100\,\mu\text{F}$ is enough for the ripple.

## Decision

Four changes, in this order:

1. **Smaller capacitor.** Replace the $1000\,\mu\text{F}$ capacitor with a
   $22\,\mu\text{F}$ low-ESR part. The RC time constant falls by about 5
   times. The worst hardware lag falls from 68.4 ms to about 15 ms.
2. **20 ms mains notch.** The lamps of the solar simulator produce a 100 Hz
   ripple of $\pm 30 - 50\,\text{mV}$. A burst of 25 samples over 1.25 ms
   (50 us spacing) caught a random phase of it. This inverted the
   $\Delta V$ slope in fine MPPT steps (0.2 % to 0.5 %) and the voltage
   drifted toward $V_\text{oc}$. The firmware now spaces the 25 samples by
   800 us (`Timer::after_micros(800)`). The window is exactly 20 ms: 1 cycle
   of 50 Hz and 2 cycles of 100 Hz. The sine ripple integrates to zero and
   the steady-state ripple falls to 0.0 mV pp.
3. **Outlier rejection and flush.** The firmware takes a 25-sample trimmed
   mean (drops the 4 lowest and 4 highest, averages the middle 17). On a
   duty change command the Pico clears its buffers, waits for the hardware
   transition, computes the settled value and holds that one measurement.
   It does not stream raw readings.
4. **Driver and step size.**
   - `SpiMcuSource` has a raw mode (`settling_time_s = 0.0`). The step
     response tool `scripts/sepic_step_response.py` uses it to record
     transients every 3 ms.
   - For closed-loop tracking, `settling_time_s` is `0.05` (50 ms). This
     covers the filter and the hardware.
   - With $\Delta D = 0.002$ (0.2 %), the algorithms converge to
     $V_\text{mpp} \approx 14.30\,\text{V}$ (error under 0.6 % of the sweep
     peak) with an oscillation span of about 1.0 V.

An adaptive P&O step size is a separate software option. It reduces the
number of steps and does not change the settling time of one step.

## Measured result

Duty steps from 0.40 to 0.70 into a $10\,\Omega$ load. Settling times in
ms:

| Duty step | $V_\text{in}$ mean | $V_\text{out}$ | $1000\,\mu\text{F}$, no filter | $22\,\mu\text{F}$, 1.25 ms burst | $22\,\mu\text{F}$ + 20 ms notch |
| --- | --- | --- | --- | --- | --- |
| 0.40 to 0.45 | 15.50 V | 11.57 to 13.52 V | 7.3 | 14.1 | **41.1** |
| 0.45 to 0.50 | 13.74 V | 13.52 to 14.53 V | 23.8 | 5.5 | **45.6** |
| 0.50 to 0.55 | 9.58 V | 14.53 to 12.15 V | 68.4 | 14.6 | **42.0** |
| 0.55 to 0.60 | 6.55 V | 12.15 to 10.05 V | 55.3 | 14.6 | **44.5** |
| 0.60 to 0.65 | 4.38 V | 10.05 to 8.12 V | 41.7 | 0.0 (artifact) | **42.1** |
| 0.65 to 0.70 | 2.87 V | 8.12 to 6.44 V | 28.2 | 0.0 (artifact) | **42.0** |

- The $V_\text{out}$ and $V_\text{in}$ ripple is 0.0 mV pp in the last column.
- The 0.0 ms values are artifacts. The ripple phase hid the transition.
- The settling time with the notch is uniform: 41.1 to 45.6 ms, mean 42.9
  ms. It is the sum of two parts:
  - power stage: about 22.9 ms (L-C-L tank and coupling capacitor, within
    the $\pm 2\%$ band, with the $22\,\mu\text{F}$ capacitor),
  - notch window: 20.0 ms (25 samples x 800 us).
- $V_\text{out}$ peaks at 14.53 V ($P \approx 21.1\,\text{W}$ into
  $10\,\Omega$) at $D = 0.50$ ($V_\text{in} \approx 13.74\,\text{V}$). This
  matches the panel MPP.

## Analog divider range: `Full` or `Low`

`Low` (8.5x) gives 2.76 times finer ADC voltage resolution than `Full`
(23.5x). The quantization noise is lower.

| Metric | `Full` (235 k / 10 k) | `Low` (85 k / 10 k) |
| --- | --- | --- |
| Divider ratio | 23.5x | 8.5x |
| Full scale | about 75.6 V | about 27.3 V |
| 1 LSB | about 23.5 mV | about 8.5 mV |
| Ripple, step 0.40 to 0.45 | 94.0 mV pp (about 4 LSB) | **43.0 mV pp** (about 5 LSB) |
| Ripple, step 0.45 to 0.50 | 212.0 mV pp | **51.0 mV pp** |
| Ripple, step 0.55 to 0.60 | 517.0 mV pp | **77.0 mV pp** |

For setups with $V_\text{oc} \le 27.3\,\text{V}$, `Low` gives the best
gradient sensitivity for fine-step MPPT.

For the closed-loop timing diagram and the single-measurement protocol see
[the measurement protocol](mppt_measurement_protocol.md).
