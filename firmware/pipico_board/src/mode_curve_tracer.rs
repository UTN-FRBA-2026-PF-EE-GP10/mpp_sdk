//! Curve tracer: a runtime, one-shot sweep triggered by `But1`, not a
//! `FirmwareMode` (see `main.rs`'s `TRACER_ACTIVE` static and its doc
//! comment for why). While a sweep runs, the panel is rerouted from the
//! SEPIC path onto the bleed path by the relay (`Tracer_En`, GPIO2), and
//! `Tracer_pwm` (GPIO3) is stepped linearly across its full range while
//! `MEAS_V_MV`/`MEAS_I_MA` (published by `sensors_task`, `main.rs`) are
//! sampled at each step to trace the panel's I-V curve. Results are dumped
//! via `defmt` on completion or abort - no Pi transport yet, see plan 016's
//! history and plan 018 (the follow-up that adds one).

use core::cell::RefCell;

use critical_section::Mutex;
use embassy_rp::gpio::{Input, Output};
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_time::{Duration, Timer, with_timeout};
use portable_atomic::{AtomicU32, Ordering};

use crate::{MEAS_I_MA, MEAS_V_MV, TRACER_ACTIVE};

/// Number of points spanned linearly across the full PWM range - matches
/// the ESP32-C3 reference device's default sample count (see plan 016).
/// This board sweeps the *full* range (no user dial to pick a target
/// current subset, unlike the reference).
pub const TRACER_SWEEP_POINTS: usize = 20;

/// Top of `Tracer_pwm`'s PWM range: `top = 12499`, divider 1, at the
/// default 125 MHz sysclk -> 10 kHz. Conservative starting point (plan 016
/// deliberately does not match the SEPIC gate's 100 kHz - the bleed path
/// switches a slower thermal/electrical process, not a converter
/// inductor); confirm on-target it doesn't audibly/electrically misbehave
/// before trusting this value.
pub const TRACER_PWM_MAX: u16 = 12499;

/// Settle time after each duty step before sampling. Starting point per
/// plan 016 (matches the ESP32 reference's 250 ms); this project has no
/// schematic-derived time constant for the bleed path, so this needs
/// on-target re-tuning.
const TRACER_SETTLE_MS: u64 = 250;

/// Consecutive fresh `MEAS_V_MV`/`MEAS_I_MA` samples averaged per point,
/// gated on `INA_SAMPLE_COUNT` freshness (see that static's doc comment in
/// `main.rs`) - not value-equality, which stalls if two consecutive INA229
/// reads happen to match (the exact bug `mode_power_supply.rs`'s
/// `ClosedLoopState` had to be fixed for - same failure class, different
/// data source). `sensors_task` free-runs at ~1 kHz, much faster than the
/// ESP32 reference's I2C-polled INA219, so a short averaging window is a
/// reasonable starting point versus the reference's ~1 s/point - needs
/// on-target confirmation, not just porting the assumption.
const TRACER_AVG_SAMPLES: u32 = 5;

/// Bounds `wait_fresh_ina_sample` - `sensors_task` normally publishes at
/// ~1 kHz, so this is generous headroom, not a tight budget. Without this,
/// a stalled/glitched INA229 link (SPI0 fault, sensor unplugged - exactly
/// the kind of bench fault this sweep should be robust to) leaves
/// `wait_fresh_ina_sample` spinning forever: `INA_SAMPLE_COUNT` only
/// advances on a *successful* read (`sensors_task`'s `Ok(v), Ok(i)` arm),
/// so a stuck sensor means `run_sweep` never reaches its own cleanup
/// (de-energize, clear `TRACER_ACTIVE`) - the SEPIC gate would stay
/// force-zeroed indefinitely. Timing out and aborting the sweep here is
/// the fix.
const TRACER_SAMPLE_TIMEOUT_MS: u64 = 500;

/// How often to poll `MEAS_V_MV`/`MEAS_I_MA` for a safety-cutoff breach
/// during the settle window after each duty step - not gated on sample
/// freshness like `wait_fresh_ina_sample` (a slightly-stale reading is
/// fine for "is this dangerously high right now", unlike the point
/// average, which wants genuinely fresh data). Without this, a spike
/// immediately after stepping duty goes unmonitored for the whole
/// `TRACER_SETTLE_MS` window - unlike the ESP32 reference (which never
/// monitors during its own settle wait either, a gap worth *not*
/// carrying over here).
const TRACER_SETTLE_POLL_MS: u64 = 10;

/// Safety cutoff: current, referencing the INA229's own calibrated
/// full-scale rather than inventing a separate limit disconnected from
/// what the sensor can even measure.
const TRACER_I_MAX_MA: u16 = crate::ina229::I_MAX_MA as u16;

/// Safety cutoff: power, in milliwatts. Conservative starting point (well
/// under the board's `<= 40 V, <= 1 A` design limits, see
/// `docs/general_information.md`) - the bleed element's actual rating
/// hasn't been reviewed against this (no schematic read, see plan 016's
/// Scope); re-tune on-target once that's known.
const TRACER_P_MAX_MW: u32 = 5000;

/// Debounce window for `But1`'s falling edge - rejects contact-bounce
/// glitches shorter than this before committing to a sweep.
const BUTTON_DEBOUNCE_MS: u64 = 30;

/// One completed (or aborted) sweep's results - `points[..count]` are
/// valid, `points[count..]` are the zeroed unfilled tail on an abort.
/// `Copy` (fixed-size array of `Copy` tuples) so `spi_slave_pio.rs`'s
/// bulk-read state machine (plan 018) can hold a snapshot by value without
/// borrowing this module's storage across an `.await`.
#[derive(Clone, Copy)]
pub struct SweepResult {
    pub points: [(u16, u16); TRACER_SWEEP_POINTS],
    pub count: usize,
}

/// Most recent sweep's result, if any and not yet fetched. Written once by
/// `run_sweep` on completion/abort; read (and cleared) exactly once by
/// `spi_slave_pio.rs`'s bulk-read request handling (`take_last_sweep`) -
/// see plan 018. `critical_section::Mutex` rather than an atomic because
/// `SweepResult` isn't a single machine word; this firmware runs a single
/// cooperative executor on one core (see `spi_slave_pio.rs`'s module doc
/// comment), so a critical section here is only ever contending with
/// itself, never truly concurrent hardware access.
static LAST_SWEEP: Mutex<RefCell<Option<SweepResult>>> = Mutex::new(RefCell::new(None));

/// Takes (removes) the most recent sweep result, if any - `None` if no
/// sweep has completed yet, or the last one was already fetched.
pub fn take_last_sweep() -> Option<SweepResult> {
    critical_section::with(|cs| LAST_SWEEP.borrow(cs).borrow_mut().take())
}

/// Owned by the curve-tracer task - exactly one instance ever runs.
pub struct CurveTracer {
    tracer_en: Output<'static>,
    tracer_pwm: Pwm<'static>,
    tracer_pwm_cfg: PwmConfig,
    but1: Input<'static>,
    /// Freshness counter for `wait_fresh_ina_sample` - separate from
    /// `INA_SAMPLE_COUNT`'s own storage, this is just "the last value this
    /// sweep has already consumed."
    last_ina_sample_seen: Option<u32>,
}

impl CurveTracer {
    pub fn new(
        tracer_en: Output<'static>,
        tracer_pwm: Pwm<'static>,
        tracer_pwm_cfg: PwmConfig,
        but1: Input<'static>,
    ) -> Self {
        Self {
            tracer_en,
            tracer_pwm,
            tracer_pwm_cfg,
            but1,
            last_ina_sample_seen: None,
        }
    }

    fn set_pwm(&mut self, duty: u16) {
        self.tracer_pwm_cfg.compare_b = duty;
        self.tracer_pwm.set_config(&self.tracer_pwm_cfg);
    }

    /// Waits for a fresh `sensors_task` INA229 sample, returning it - see
    /// `TRACER_AVG_SAMPLES`'s doc comment for why this is freshness-gated
    /// rather than polled on a fixed timer. Returns `None` on
    /// `TRACER_SAMPLE_TIMEOUT_MS` timeout (see its doc comment) instead of
    /// blocking forever.
    async fn wait_fresh_ina_sample(&mut self) -> Option<(u16, u16)> {
        let last_seen = &mut self.last_ina_sample_seen;
        with_timeout(Duration::from_millis(TRACER_SAMPLE_TIMEOUT_MS), async {
            loop {
                let sample = INA_SAMPLE_COUNT.load(Ordering::Relaxed);
                if *last_seen != Some(sample) {
                    *last_seen = Some(sample);
                    return (
                        MEAS_V_MV.load(Ordering::Relaxed),
                        MEAS_I_MA.load(Ordering::Relaxed),
                    );
                }
                Timer::after_millis(1).await;
            }
        })
        .await
        .ok()
    }

    /// `None` on a `wait_fresh_ina_sample` timeout - caller must abort the
    /// sweep, not treat it as a valid (0, 0) point.
    async fn average_point(&mut self) -> Option<(u16, u16)> {
        let mut v_sum: u32 = 0;
        let mut i_sum: u32 = 0;
        for _ in 0..TRACER_AVG_SAMPLES {
            let (v, i) = self.wait_fresh_ina_sample().await?;
            v_sum += v as u32;
            i_sum += i as u32;
        }
        Some((
            (v_sum / TRACER_AVG_SAMPLES) as u16,
            (i_sum / TRACER_AVG_SAMPLES) as u16,
        ))
    }

    /// Polls `MEAS_V_MV`/`MEAS_I_MA` every `TRACER_SETTLE_POLL_MS` for
    /// `TRACER_SETTLE_MS`, returning `true` the instant the safety cutoff
    /// is breached instead of only checking after the fact - see
    /// `TRACER_SETTLE_POLL_MS`'s doc comment for why.
    fn breach(v_mv: u16, i_ma: u16) -> bool {
        let p_mw = v_mv as u32 * i_ma as u32 / 1000;
        i_ma > TRACER_I_MAX_MA || p_mw > TRACER_P_MAX_MW
    }

    async fn settle_and_monitor(&self) -> bool {
        let mut waited_ms = 0u64;
        while waited_ms < TRACER_SETTLE_MS {
            let v_mv = MEAS_V_MV.load(Ordering::Relaxed);
            let i_ma = MEAS_I_MA.load(Ordering::Relaxed);
            if Self::breach(v_mv, i_ma) {
                return true;
            }
            Timer::after_millis(TRACER_SETTLE_POLL_MS).await;
            waited_ms += TRACER_SETTLE_POLL_MS;
        }
        false
    }

    /// Runs one full sweep: energizes the relay, steps `Tracer_pwm` from 0
    /// to `TRACER_PWM_MAX` in `TRACER_SWEEP_POINTS` equal steps, aborts
    /// early on a safety-cutoff breach, then always de-energizes and
    /// clears `TRACER_ACTIVE` - the SEPIC gate must never stay forced to 0
    /// past the sweep's own lifetime, breach or not.
    async fn run_sweep(&mut self) {
        defmt::info!("curve_tracer: sweep starting");
        TRACER_ACTIVE.store(true, Ordering::Relaxed);
        self.tracer_en.set_high();

        let mut points = [(0u16, 0u16); TRACER_SWEEP_POINTS];
        let mut points_captured: usize = 0;
        let mut aborted = false;

        for (step, point) in points.iter_mut().enumerate() {
            let duty =
                (step as u32 * TRACER_PWM_MAX as u32 / (TRACER_SWEEP_POINTS - 1) as u32) as u16;
            self.set_pwm(duty);

            if self.settle_and_monitor().await {
                let v_mv = MEAS_V_MV.load(Ordering::Relaxed);
                let i_ma = MEAS_I_MA.load(Ordering::Relaxed);
                defmt::warn!(
                    "curve_tracer: safety cutoff during settle at step {} \
                     (V={} mV I={} mA), aborting sweep",
                    step,
                    v_mv,
                    i_ma
                );
                aborted = true;
                break;
            }

            let Some((v_mv, i_ma)) = self.average_point().await else {
                defmt::warn!(
                    "curve_tracer: INA229 sample timeout at step {}, aborting sweep",
                    step
                );
                aborted = true;
                break;
            };

            if Self::breach(v_mv, i_ma) {
                defmt::warn!(
                    "curve_tracer: safety cutoff at step {} (V={} mV I={} mA), aborting sweep",
                    step,
                    v_mv,
                    i_ma
                );
                aborted = true;
                break;
            }

            *point = (v_mv, i_ma);
            points_captured = step + 1;
        }

        // Always de-energize and hand the gate back, breach or not - this
        // must not depend on how the loop above exited.
        self.set_pwm(0);
        self.tracer_en.set_low();
        TRACER_ACTIVE.store(false, Ordering::Relaxed);

        if aborted {
            defmt::warn!(
                "curve_tracer: sweep aborted after {} points",
                points_captured
            );
        } else {
            defmt::info!("curve_tracer: sweep complete, {} points", points_captured);
        }
        for (idx, (v_mv, i_ma)) in points[..points_captured].iter().enumerate() {
            defmt::info!("curve_tracer: point {}: V={} mV I={} mA", idx, v_mv, i_ma);
        }

        // Publish for the SPI bulk-read path (plan 018) - overwrites
        // whatever the previous sweep left, fetched or not; only the most
        // recent sweep's result is ever available to fetch.
        critical_section::with(|cs| {
            *LAST_SWEEP.borrow(cs).borrow_mut() = Some(SweepResult {
                points,
                count: points_captured,
            });
        });
    }
}

/// Bumped once per `sensors_task` INA229 read (`main.rs`), independent of
/// `ADC_SAMPLE_COUNT` (which tracks `onchip_adc_task`'s on-chip-ADC
/// readings instead, a different task on a much slower ~100 ms cadence) -
/// averaging `MEAS_V_MV`/`MEAS_I_MA` needs a counter on *that* data's own
/// publish rate, not a different task's.
pub static INA_SAMPLE_COUNT: AtomicU32 = AtomicU32::new(0);

/// Waits for a debounced `But1` press, runs one sweep, waits for release,
/// repeats. A press while a sweep is already running is impossible by
/// construction - the task is single-threaded and spends the whole sweep
/// inside `run_sweep()`, not polling `But1`.
#[embassy_executor::task]
pub async fn curve_tracer_task(mut tracer: CurveTracer) {
    loop {
        tracer.but1.wait_for_falling_edge().await;
        Timer::after_millis(BUTTON_DEBOUNCE_MS).await;
        if tracer.but1.is_high() {
            // Debounce rejected a glitch, not a real press.
            continue;
        }

        tracer.run_sweep().await;

        // Wait for release before re-arming, so a still-held button can't
        // immediately retrigger the next sweep.
        tracer.but1.wait_for_high().await;
    }
}
