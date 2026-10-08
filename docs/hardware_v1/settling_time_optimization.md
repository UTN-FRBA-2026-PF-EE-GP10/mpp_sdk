# SEPIC Settling Time and Capacitor Analysis

**Date:** 2026-10-07

## Problem Statement
The current hardware setup exhibits a very slow settling time ($\sim 100\,\text{ms}$) when a step response is applied to the SEPIC converter duty cycle. At a $50\,\text{kHz}$ switching frequency, one switching cycle takes $20\,\mu\text{s}$. Waiting $100\,\text{ms}$ means waiting **$5,000$ switching cycles** for the system to settle. For a typical DC-DC converter, settling should happen in tens or hundreds of cycles (around $1\,\text{ms}$ to $5\,\text{ms}$).

## The Physics of the $1000\,\mu\text{F}$ Input Capacitor
The $1000\,\mu\text{F}$ input capacitor (in parallel with the solar panel) is almost certainly the main reason for this slow settling time. 

When the MPPT algorithm changes the SEPIC's duty cycle ($D$), it changes the equivalent resistance that the solar panel "sees". The solar panel then wants to move to a new voltage and current point on its I-V curve. 

However, before the *measured* voltage can reach that new steady state, the $1000\,\mu\text{F}$ capacitor has to charge or discharge to the new voltage level. Because a solar panel has a limited current output, it takes a long time to fill or drain that massive $1000\,\mu\text{F}$ energy buffer.

**Can it be removed?**
No. You **cannot remove it completely**. Without an input capacitor, the solar panel would see the raw $50\,\text{kHz}$ switching ripple (switching between drawing zero current and peak inductor current). Solar panels do not operate efficiently under high-ripple pulsating currents, and ADC measurements would be heavily distorted.

## Options to Improve Speed Without Losing Accuracy

### Option A: Reduce the Input Capacitor (Hardware - Highly Recommended)
You don't need $1000\,\mu\text{F}$ to filter out a $50\,\text{kHz}$ ripple. 
* **The Fix**: Swap the $1000\,\mu\text{F}$ capacitor for a much smaller one. A value between **$22\,\mu\text{F}$ and $100\,\mu\text{F}$** (preferably a low-ESR ceramic or good quality electrolytic) should be more than enough to smooth the $50\,\text{kHz}$ switching ripple.
* **The Result**: The time constant will drop by a factor of 10 to 50. The settling time could drop from $100\,\text{ms}$ down to $5\,\text{ms}$ or $10\,\text{ms}$, allowing the algorithm to run $10\times$ faster natively.

### Option B: Adaptive Step Size (Software/Algorithmic)
If you cannot change the hardware right now, you have to accept that every step takes $100\,\text{ms}$. To make the *overall* algorithm find the MPP faster, you must take fewer steps.
* **The Fix**: Implement an Adaptive Perturb & Observe (P&O) algorithm. If the change in power ($\Delta P$) is large, take a large duty cycle step (e.g., `0.05`). When $\Delta P$ gets very small (indicating you are near the peak), shrink the step size (e.g., `0.005`).
* **The Result**: You reach the Maximum Power Point in 5-10 iterations instead of 50. 

### Option C: Dynamic Settling Detection (Firmware/Software)
Instead of hardcoding a blind `0.10s` wait time, we can dynamically detect when the system has settled.
* **The Fix**: In the firmware or the Python loop, start taking measurements after $5\,\text{ms}$. Keep a rolling buffer of readings. If the difference between the maximum and minimum of those readings is less than a small threshold (e.g., less than the known ripple), assume it has settled and return the value early.
* **The Result**: Small duty cycle steps will return quickly (maybe $20\,\text{ms}$), while large steps will dynamically wait longer (up to $100\,\text{ms}$) only when necessary.

## Conclusion
The most effective engineering fix is **Option A**. A $1000\,\mu\text{F}$ capacitor acts as a large energy storage tank, not a high-frequency switching filter. Swapping it for a $\sim 47\,\mu\text{F}$ capacitor will solve the speed issue at the hardware level, allowing the `settling-time-s` parameter to be safely lowered to `0.01` or `0.02` seconds.
