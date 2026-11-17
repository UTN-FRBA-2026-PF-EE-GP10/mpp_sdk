//! Fixed-step Perturb & Observe for the RP2040, in integer math.
//!
//! This is a port of `mpp_sdk/algorithms/perturb_observe.py`. Duty is a `u16`
//! (0..=65535 is 0..1). On the SEPIC, raising duty lowers the panel voltage.
#![no_std]

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config {
    pub initial_duty: u16,
    pub step: u16,
    pub min_duty: u16,
    pub max_duty: u16,
}

impl Config {
    /// The Python defaults (0.5, 0.001, 0.05) in u16 counts, with the firmware `DUTY_MAX`.
    pub const DEFAULT: Config = Config {
        initial_duty: 32768,
        step: 66,
        min_duty: 3277,
        max_duty: 62258,
    };
}

#[derive(Clone, Debug)]
pub struct PerturbAndObserve {
    cfg: Config,
    duty: u16,
    // None until the first sample. Power in mV * mA fits u32 (65535^2 < 2^32).
    last: Option<(u16, u32)>,
}

impl PerturbAndObserve {
    pub fn new(cfg: Config) -> Self {
        // Not `clamp`: it panics on an inverted pair, and a panic resets the Pico.
        let duty = cfg.initial_duty.max(cfg.min_duty).min(cfg.max_duty);
        Self {
            cfg,
            duty,
            last: None,
        }
    }

    pub fn duty(&self) -> u16 {
        self.duty
    }

    /// Takes the latest V (mV) and I (mA), returns the next duty.
    pub fn step(&mut self, v_mv: u16, i_ma: u16) -> u16 {
        let p = u32::from(v_mv) * u32::from(i_ma);
        let up = match self.last {
            // First sample: always step up, like the Python reference.
            None => true,
            Some((last_v, last_p)) => {
                if p == last_p {
                    // Equal power: hold.
                    self.last = Some((v_mv, p));
                    return self.duty;
                }
                // P and V moving the same way means V should keep going, so
                // duty goes down. Any other case (including dv == 0) goes up.
                let same_way = v_mv != last_v && (p > last_p) == (v_mv > last_v);
                !same_way
            }
        };
        self.last = Some((v_mv, p));
        self.duty = if up {
            self.duty
                .saturating_add(self.cfg.step)
                .min(self.cfg.max_duty)
        } else {
            self.duty
                .saturating_sub(self.cfg.step)
                .max(self.cfg.min_duty)
        };
        self.duty
    }
}
