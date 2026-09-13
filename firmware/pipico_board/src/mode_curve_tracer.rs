//! Curve tracer: a runtime sweep, not a `FirmwareMode` (see `main.rs`'s
//! `TRACER_ACTIVE` static and its doc comment for why). A sweep is
//! triggered either by `But1` or by the Pi over SPI (`TRACER_COMMAND`).
//! While a sweep runs, the panel is rerouted from the SEPIC path onto the
//! bleed path by the relay (`Tracer_En`, GPIO2), and `Tracer_pwm` (GPIO3)
//! commands a linear current sink (see `TRACER_PWM_MAX`) that is stepped
//! from zero up to this sweep's auto-ranged top (see `auto_range`) while
//! `MEAS_V_MV`/`MEAS_I_MA` (published by `sensors_task`, `main.rs`) are
//! sampled at each step to trace the panel's I-V curve. Results are
//! published to
//! `LAST_SWEEP` for the Pi to fetch over SPI. The relay stays engaged
//! across any number of sweeps - it is released only by an explicit
//! `TracerCommand::ReleaseRelay` (`But1` never releases it either; only
//! `release_relay()` does), not automatically at the end of each sweep.

use core::cell::RefCell;

use critical_section::Mutex;
use embassy_futures::select::{Either, select};
use embassy_rp::gpio::{Input, Output};
use embassy_rp::pwm::{Config as PwmConfig, Pwm};
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;
use embassy_time::{Duration, Timer, with_timeout};
use portable_atomic::{AtomicU32, Ordering};
use safety_checks::breach;

use crate::{MEAS_I_MA, MEAS_V_MV, RELAY_ENGAGED, TRACER_ACTIVE};

/// Points per sweep - matches the ESP32-C3 reference device's default
/// sample count. Raising it means resizing the SPI bulk-dump frame
/// (`spi_slave_pio.rs`'s `BULK_FRAME_LEN`) and its Pi-side reader, so the
/// budget is fixed and the points are placed where they are worth most -
/// see `sweep_duty_for_step`. Unlike the reference (which has the
/// operator dial in a target current range), the sweep's top is found
/// automatically per sweep - see `auto_range`.
pub const TRACER_SWEEP_POINTS: usize = 20;

/// Points of the budget above spent on the fine leg across the knee. The
/// rest split between the flat region below it and a short tail above.
const TRACER_FINE_POINTS: usize = 12;

/// Points spent above the knee band, reaching the auto-ranged top. Enough
/// to pin Isc and to still catch the collapse if illumination drifted
/// between auto-range and the sweep, and no more: past the cliff every
/// extra point reads the same short-circuit current.
const TRACER_TAIL_POINTS: usize = 2;

/// Where the fine leg starts and ends, as a percent of the knee duty.
/// Below the start a panel is a current source and the curve is nearly
/// flat, so coarse steps lose almost nothing; across this band it bends
/// through the MPP and collapses. Bench measurement: the MPP sat at 0.90x
/// the knee and the collapse finished by 1.01x.
const TRACER_FINE_BAND_START_PERCENT: u32 = 85;
const TRACER_FINE_BAND_END_PERCENT: u32 = 102;

/// Top of `Tracer_pwm`'s PWM range: `top = 12499`, divider 1, at the
/// default 125 MHz sysclk -> 10 kHz.
///
/// `Tracer_pwm` is **not** a switch drive - the hardware (schematic sheet
/// `SepicConverter.kicad_sch`) low-pass filters it through two RC stages
/// (R1/C29, R3/C30, 10K + 100nF each) into an analog setpoint, which an
/// op-amp (U5, OPA171) servos against the voltage across the 100 mOhm
/// sense resistor (R29) by driving Q3's gate. So the MOSFET runs *linear*
/// as a voltage-controlled current sink, and this duty sets a **commanded
/// load current**, not a switching ratio. 10 kHz is the DAC carrier; the
/// RC stages (tau = 1 ms each) filter its ripple, so a step needs ~10 ms
/// to settle - well inside `TRACER_SETTLE_MS`.
pub const TRACER_PWM_MAX: u16 = 12499;

/// Hard ceiling on the sweep's commanded current, as a percent of
/// `TRACER_PWM_MAX`. Full scale is amps into a *linearly* biased MOSFET -
/// at a panel's tens of volts that is tens of watts in Q3, far past what
/// it can dissipate. The ESP32-C3 reference device caps its own load the
/// same way (`DYNAMIC_LOAD_DUTY_MAX_PERCENT 10`), and this is a hard
/// bound on top of the `TRACER_I_MAX_MA`/`TRACER_P_MAX_MW` cutoffs, not a
/// replacement.
///
/// Bench measurement: duty 640 commanded ~215 mA, so full scale is
/// ~4.2 A and 20 % is ~840 mA. Kept just above `TRACER_I_MAX_MA` (700 mA)
/// so the current and power cutoffs are what actually bound a sweep -
/// this only stops a runaway if those readings are wrong.
const TRACER_SWEEP_DUTY_MAX_PERCENT: u32 = 20;

/// Settle time after each duty step before sampling. Starting point
/// matches the ESP32 reference's 250 ms; this project has no
/// schematic-derived time constant for the bleed path, so this needs
/// on-target re-tuning.
const TRACER_SETTLE_MS: u64 = 250;

/// Consecutive fresh `MEAS_V_MV`/`MEAS_I_MA` samples averaged per point,
/// gated on `INA_SAMPLE_COUNT` freshness (see that static's doc comment in
/// `main.rs`) - not value-equality, which stalls if two consecutive INA229
/// reads happen to match (the exact bug `mode_power_supply.rs`'s
/// `ClosedLoopState` had to be fixed for - same failure class, different
/// data source). `sensors_task` free-runs at ~1 kHz, so this is also the
/// averaging window in milliseconds.
///
/// Sized to span several periods of mains-driven light ripple, not just
/// to beat sensor noise. A lamp on 50 Hz mains modulates the panel at
/// 100 Hz, and at the previous 5 samples each point averaged half a
/// ripple period at an arbitrary phase: adjacent points in the knee band
/// came back non-monotonic, V rising as commanded current rose, which no
/// panel does. The window is deliberately several periods rather than
/// exactly one - `sensors_task`'s cadence is `Timer::after_millis(1)`
/// plus an SPI read, so the period is a little over 1 ms and a
/// single-period window would not land on a whole number of cycles.
const TRACER_AVG_SAMPLES: u32 = 40;

/// Bounds `wait_fresh_ina_sample` - `sensors_task` normally publishes at
/// ~1 kHz, so this is generous headroom, not a tight budget. Without this,
/// a stalled/glitched INA229 link (SPI0 fault, sensor unplugged - exactly
/// the kind of bench fault this sweep should be robust to) leaves
/// `wait_fresh_ina_sample` spinning forever: `INA_SAMPLE_COUNT` only
/// advances on a *successful* read (`sensors_task`'s `Ok(v), Ok(i)` arm),
/// so a stuck sensor means `run_sweep` never reaches its own cleanup
/// (stop driving the bleed load, clear `TRACER_ACTIVE`) - the SEPIC gate
/// would stay force-zeroed indefinitely. Timing out and aborting the
/// sweep here is the fix.
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

/// Debounce window for `But1`'s falling edge - rejects contact-bounce
/// glitches shorter than this before committing to a sweep.
const BUTTON_DEBOUNCE_MS: u64 = 30;

// ── auto-range (see `auto_range`) ────────────────────────────────────────
//
// The load's full-scale current is far above what a small PV panel can
// deliver (the reference device's is ~3.9 A; a lit panel here sources
// ~0.2 A), so a fixed 0..TRACER_PWM_MAX sweep spends all but its first
// point past Isc, with the panel collapsed to ~0 V - 20 identical
// short-circuit readings instead of a curve. Each sweep therefore probes
// for its own top first, which also tracks illumination and shading
// changes without anyone dialling in a range.

/// Settle time per auto-range probe. Matches `TRACER_SETTLE_MS` rather
/// than undercutting it: a probe's current reading now sets the sweep's
/// whole range (see `auto_range`), so it has to be as settled as a
/// recorded point. `Tracer_pwm`'s RC filter is slow enough to matter at
/// the doubling search's step sizes - at 60 ms a probe reads the filter
/// mid-charge, under-reporting the current the sink is delivering and
/// skewing the mA-per-duty scale the range is computed from.
const TRACER_SCAN_SETTLE_MS: u64 = TRACER_SETTLE_MS;

/// First duty the doubling search tries. Small enough to sit below Isc
/// for any panel this board is meant for, so the search brackets from
/// below rather than starting already collapsed.
const TRACER_SCAN_START_DUTY: u16 = 8;

/// The panel counts as collapsed below this percent of its open-circuit
/// voltage - past the knee and into the constant-current region, meaning
/// the commanded current has overtaken what the panel can source.
const TRACER_COLLAPSE_PERCENT_OF_VOC: u32 = 15;

/// Headroom above the detected knee for the sweep's top, as a percent, so
/// the last points sit just past Isc instead of exactly on it.
const TRACER_SWEEP_HEADROOM_PERCENT: u32 = 115;

/// Below this open-circuit voltage there is no panel worth sweeping (dark,
/// disconnected, or the relay didn't transfer) - auto-ranging would just
/// chase noise, so the sweep aborts instead.
const TRACER_MIN_VOC_MV: u16 = 500;

/// Curves `run_demo_sweep` replays, as `(V mV, I mA)` - both captured on
/// this bench off a real panel under a lamp, at two brightnesses, so the
/// shapes and the Voc/Isc/MPP relationships are real rather than
/// synthesised. Index 0 is the dimmer setting (Voc 18.62 V, Isc 229 mA,
/// MPP 3.07 W, FF 0.72), index 1 the brighter one (Voc 19.34 V, Isc
/// 607 mA, MPP 7.71 W, FF 0.66).
const DEMO_CURVES: [[(u16, u16); TRACER_SWEEP_POINTS]; 2] = [
    [
        (18620, 7),
        (18290, 34),
        (17870, 66),
        (17410, 98),
        (16890, 130),
        (16270, 162),
        (15420, 194),
        (15280, 197),
        (15090, 201),
        (14970, 204),
        (14770, 208),
        (14500, 211),
        (14170, 214),
        (13450, 218),
        (8750, 221),
        (5950, 223),
        (3830, 227),
        (440, 229),
        (50, 229),
        (40, 229),
    ],
    [
        (19337, 6),
        (18658, 86),
        (17929, 171),
        (17179, 256),
        (16386, 341),
        (15544, 425),
        (14599, 509),
        (14490, 519),
        (14362, 528),
        (14212, 537),
        (14074, 546),
        (13887, 555),
        (13463, 564),
        (9011, 573),
        (4822, 581),
        (2521, 589),
        (1048, 598),
        (212, 607),
        (118, 608),
        (116, 607),
    ],
];

/// Commanded duty for one sweep step, given the auto-ranged `top`.
///
/// Three legs, not one linear ramp. Stepping duty uniformly steps the
/// *commanded current* uniformly, and a panel below its knee is a current
/// source: most of such a sweep crawls down a nearly flat V, then the
/// curve turns and collapses within a couple of steps. On the bench a
/// uniform ramp left the MPP - the one number every algorithm is graded
/// against - bracketed by a 10 V gap, while five of its points sat past
/// the cliff all reading the same Isc. So: a coarse leg over the flat
/// region, most of the budget across the knee band, and a short tail to
/// reach `top` and pin Isc.
///
/// `top` is `TRACER_SWEEP_HEADROOM_PERCENT` of the knee duty, so the knee
/// is recovered from it by that ratio. Monotonically increasing, step 0
/// is always duty 0, and the last step is always exactly `top` - the
/// sweep only ever commands more current than the step before (see
/// `auto_range` on why descending steps read stale).
fn sweep_duty_for_step(step: usize, top: u16) -> u16 {
    let coarse_points = TRACER_SWEEP_POINTS - TRACER_FINE_POINTS - TRACER_TAIL_POINTS;
    let knee = top as u32 * 100 / TRACER_SWEEP_HEADROOM_PERCENT;
    let band_start = (knee * TRACER_FINE_BAND_START_PERCENT / 100) as u16;
    let band_end = ((knee * TRACER_FINE_BAND_END_PERCENT / 100) as u16).min(top);

    if step < coarse_points {
        (step as u32 * band_start as u32 / coarse_points as u32) as u16
    } else if step < coarse_points + TRACER_FINE_POINTS {
        let fine_step = (step - coarse_points) as u32;
        let span = band_end.saturating_sub(band_start) as u32;
        band_start + (fine_step * span / (TRACER_FINE_POINTS - 1) as u32) as u16
    } else {
        let tail_step = (step - coarse_points - TRACER_FINE_POINTS + 1) as u32;
        let span = top.saturating_sub(band_end) as u32;
        band_end + (tail_step * span / TRACER_TAIL_POINTS as u32) as u16
    }
}

/// One completed (or aborted) sweep's results - `points[..count]` are
/// valid, `points[count..]` are the zeroed unfilled tail on an abort.
/// `Copy` (fixed-size array of `Copy` tuples) so `spi_slave_pio.rs`'s
/// bulk-read state machine can hold a snapshot by value without
/// borrowing this module's storage across an `.await`.
#[derive(Clone, Copy)]
pub struct SweepResult {
    pub points: [(u16, u16); TRACER_SWEEP_POINTS],
    pub count: usize,
}

/// Most recent sweep's result, if any and not yet fetched. Written once by
/// `run_sweep` on completion/abort; read (and cleared) exactly once by
/// `spi_slave_pio.rs`'s bulk-read request handling (`take_last_sweep`).
/// `critical_section::Mutex` rather than an atomic because `SweepResult`
/// isn't a single machine word; this firmware runs a single cooperative
/// executor on one core (see `spi_slave_pio.rs`'s module doc comment), so
/// a critical section here is only ever contending with itself, never
/// truly concurrent hardware access.
static LAST_SWEEP: Mutex<RefCell<Option<SweepResult>>> = Mutex::new(RefCell::new(None));

/// Takes (removes) the most recent sweep result, if any - `None` if no
/// sweep has completed yet, or the last one was already fetched.
pub fn take_last_sweep() -> Option<SweepResult> {
    critical_section::with(|cs| LAST_SWEEP.borrow(cs).borrow_mut().take())
}

/// Puts a taken-but-undelivered sweep back, so a torn frame partway
/// through the bulk-read handshake doesn't destroy the result. The
/// handshake carries the sweep *by value* once `take_last_sweep()` has
/// removed it, so without this a single dropped frame mid-exchange loses
/// that sweep permanently and the Pi's retry finds nothing.
///
/// Only fills an empty slot - a sweep that finished while the previous
/// one was mid-handshake is newer and must not be clobbered by the stale
/// one being handed back.
pub fn restore_last_sweep(sweep: SweepResult) {
    critical_section::with(|cs| {
        let slot = LAST_SWEEP.borrow(cs);
        let mut slot = slot.borrow_mut();
        if slot.is_none() {
            *slot = Some(sweep);
        }
    });
}

/// One point's worth of in-progress sweep state, for the Pi to draw a
/// sweep point-by-point instead of waiting for the bulk read at the end.
/// Lossy by design - unlike `SweepResult`, a dropped update is not a lost
/// measurement, since the bulk read remains the authoritative source once
/// the sweep completes.
#[derive(Clone, Copy)]
pub struct SweepProgress {
    /// Index of the point just captured, `0..TRACER_SWEEP_POINTS`.
    pub index: u8,
    pub v_mv: u16,
    pub i_ma: u16,
    /// `false` once the sweep this point belongs to has finished (or
    /// aborted) - the Pi switches from drawing `partial` to trusting the
    /// bulk-read `points` once it sees this go false.
    pub active: bool,
    /// `true` only on the one extra publish after the sweep loop exits,
    /// marking "no more points are coming" distinct from the per-point
    /// updates during the sweep (which are all `final_point: false`).
    pub final_point: bool,
}

/// Most recent sweep-progress update, if any sweep has ever run.
/// `critical_section::Mutex` for the same single-executor reasoning as
/// `LAST_SWEEP` - see its doc comment.
static PROGRESS: Mutex<RefCell<Option<SweepProgress>>> = Mutex::new(RefCell::new(None));

/// Publishes one progress update - called by `run_sweep` after each
/// captured point, and once more at the end with `active: false`.
fn publish_progress(p: SweepProgress) {
    critical_section::with(|cs| {
        *PROGRESS.borrow(cs).borrow_mut() = Some(p);
    });
}

/// Peeks (does not consume) the most recent progress update, `None` only
/// if no sweep has ever run yet. Unlike `take_last_sweep`, this must not
/// consume: a dropped progress frame is not a lost measurement (the bulk
/// read still has it), and consuming would make a torn frame silently
/// skip reporting a point that in fact happened.
pub fn peek_progress() -> Option<SweepProgress> {
    critical_section::with(|cs| *PROGRESS.borrow(cs).borrow())
}

/// A curve-tracer action the Pi can request over SPI - mirrors `But1`'s
/// two effects (start a sweep; the relay's release, previously implicit
/// at the end of every sweep, is now explicit-only).
#[derive(Clone, Copy)]
pub enum TracerCommand {
    StartSweep,
    ReleaseRelay,
    /// Index into `DEMO_CURVES` - see `run_demo_sweep`.
    DemoSweep(usize),
}

/// Cross-task command channel from `spi_pio_task` (`spi_slave_pio.rs`,
/// on seeing `CMD_START_SWEEP`/`CMD_RELEASE_RELAY`) into
/// `curve_tracer_task`. `Signal` is single-slot and "latest value wins":
/// if the Pi sends a second command before the task consumes the first,
/// the first is silently dropped - acceptable since sweeps are Pi-paced
/// and one at a time.
pub static TRACER_COMMAND: Signal<CriticalSectionRawMutex, TracerCommand> = Signal::new();

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
    async fn settle_and_monitor_for(&self, settle_ms: u64) -> bool {
        let mut waited_ms = 0u64;
        while waited_ms < settle_ms {
            let v_mv = MEAS_V_MV.load(Ordering::Relaxed);
            let i_ma = MEAS_I_MA.load(Ordering::Relaxed);
            if breach(v_mv, i_ma) {
                return true;
            }
            Timer::after_millis(TRACER_SETTLE_POLL_MS).await;
            waited_ms += TRACER_SETTLE_POLL_MS;
        }
        false
    }

    async fn settle_and_monitor(&self) -> bool {
        self.settle_and_monitor_for(TRACER_SETTLE_MS).await
    }

    /// Commands `duty`, lets it settle for `settle_ms`, and returns the
    /// averaged `(V, I)`. `None` means the sweep must abort (safety
    /// breach or a stalled sensor), same contract as `average_point`.
    ///
    /// Only ever call this with a duty at or above the one currently
    /// commanded - see `auto_range`.
    async fn probe(&mut self, duty: u16, settle_ms: u64) -> Option<(u16, u16)> {
        self.set_pwm(duty);
        if self.settle_and_monitor_for(settle_ms).await {
            defmt::warn!(
                "curve_tracer: safety cutoff while probing duty {}, aborting",
                duty
            );
            return None;
        }
        let (v_mv, i_ma) = self.average_point().await?;
        if breach(v_mv, i_ma) {
            defmt::warn!(
                "curve_tracer: safety cutoff at probed duty {} (V={} mV I={} mA), aborting",
                duty,
                v_mv,
                i_ma
            );
            return None;
        }
        defmt::info!(
            "curve_tracer: probe duty={} -> V={} mV I={} mA",
            duty,
            v_mv,
            i_ma
        );
        Some((v_mv, i_ma))
    }

    /// Finds this sweep's top duty: the commanded current just past the
    /// panel's Isc, so the 20 recorded points span the real curve instead
    /// of piling up in the collapsed region (see the auto-range constants).
    ///
    /// Measures Voc at zero load, then doubles the commanded current until
    /// the panel voltage collapses. Doubling rather than a linear scan
    /// because Isc can sit anywhere from a fraction of a percent to most of
    /// full scale depending on panel and illumination - a linear scan fine
    /// enough for the former would take far too many probes for the latter.
    ///
    /// **Every probe steps the commanded current up, never down.**
    /// `Tracer_pwm` is RC-filtered into the sink's bias, and that filter is
    /// slow next to a probe's settle window: on the bench, a probe at duty
    /// 0 still measured 27 mA, and probes walking *down* from duty 1024
    /// (768, 640, 576) all read the panel collapsed at ~215 mA, which is
    /// duty 1024's current still draining out of the filter rather than
    /// the current each probe asked for. A descending bisection therefore
    /// reported a knee at duty 576 that the (ascending) sweep ran straight
    /// past, truncating every captured curve at 78% of Voc, well short of
    /// Isc.
    ///
    /// The top comes out of two measurements instead of a search. A
    /// collapsed panel delivers its short-circuit current, so the first
    /// collapsing probe reads Isc directly; the last surviving probe -
    /// where the sink is still regulating - gives the sink's mA per duty
    /// unit, which is linear to within a percent over the useful range.
    /// The duty that commands Isc follows by arithmetic.
    ///
    /// `None` aborts the sweep (no usable panel, or a probe tripped the
    /// safety cutoff).
    async fn auto_range(&mut self) -> Option<u16> {
        let hard_max = (TRACER_PWM_MAX as u32 * TRACER_SWEEP_DUTY_MAX_PERCENT / 100).max(1) as u16;

        let (voc, _) = self.probe(0, TRACER_SCAN_SETTLE_MS).await?;
        if voc < TRACER_MIN_VOC_MV {
            defmt::warn!(
                "curve_tracer: Voc {} mV below {} mV - no panel to sweep (dark, \
                 disconnected, or the relay didn't transfer), aborting",
                voc,
                TRACER_MIN_VOC_MV
            );
            return None;
        }
        let collapse_mv = (voc as u32 * TRACER_COLLAPSE_PERCENT_OF_VOC / 100) as u16;

        // Ascending doubling search. `lo`/`lo_i_ma` keep the largest duty
        // the panel survived and the current the sink actually delivered
        // there - the scale factor for the arithmetic below.
        let mut lo: u16 = 0;
        let mut lo_i_ma: u16 = 0;
        let mut knee: u16 = 0;
        let mut duty = TRACER_SCAN_START_DUTY.min(hard_max);
        loop {
            let (v_mv, i_ma) = self.probe(duty, TRACER_SCAN_SETTLE_MS).await?;
            if v_mv <= collapse_mv {
                // Collapsed: the sink is asking for more than the panel
                // can source, so `i_ma` is the panel's Isc.
                knee = if lo == 0 || lo_i_ma == 0 {
                    // Collapsed on the very first loaded probe - no
                    // regulating point to take a scale from, so fall back
                    // to the duty that collapsed it.
                    duty
                } else {
                    (i_ma as u32 * lo as u32 / lo_i_ma as u32).min(hard_max as u32) as u16
                };
                defmt::info!(
                    "curve_tracer: collapsed at duty {} - Isc={} mA, sink {} mA per 1000 duty, \
                     knee at duty {}",
                    duty,
                    i_ma,
                    (lo_i_ma as u32 * 1000).checked_div(lo as u32).unwrap_or(0),
                    knee
                );
                break;
            }
            lo = duty;
            lo_i_ma = i_ma;
            if duty >= hard_max {
                break;
            }
            duty = duty.saturating_mul(2).min(hard_max);
        }

        if knee == 0 {
            // Never collapsed, even at the hard cap: this panel sources
            // more than the sweep is allowed to draw, so the curve is
            // whatever fits under the cap.
            defmt::warn!(
                "curve_tracer: panel still above collapse at the {}% duty cap - \
                 sweeping up to it, curve will stop short of Isc",
                TRACER_SWEEP_DUTY_MAX_PERCENT
            );
            return Some(hard_max);
        }

        // Headroom so the final points sit just past the knee, and never
        // above the dissipation cap.
        let top = (knee as u32 * TRACER_SWEEP_HEADROOM_PERCENT / 100)
            .min(hard_max as u32)
            // Keep the steps distinct even for a very weak panel.
            .max(TRACER_SWEEP_POINTS as u32) as u16;
        defmt::info!(
            "curve_tracer: auto-range Voc={} mV, knee at duty {}, sweeping 0..{}",
            voc,
            knee,
            top
        );
        Some(top)
    }

    /// Runs one full sweep: energizes the relay (harmless no-op if already
    /// engaged from a previous sweep - see the module doc comment), steps
    /// `Tracer_pwm` from 0 to the auto-ranged top (see `auto_range`)
    /// across `TRACER_SWEEP_POINTS` steps (see `sweep_duty_for_step` for
    /// how they are spaced), aborts early on a
    /// safety-cutoff breach, then always
    /// stops driving the bleed load and clears `TRACER_ACTIVE` - the SEPIC
    /// gate must never stay forced to 0 past the sweep's own lifetime,
    /// breach or not. Does **not** release the relay, breach or not - only
    /// `release_relay()` does that now.
    async fn run_sweep(&mut self) {
        defmt::info!("curve_tracer: sweep starting");
        // Drop any earlier sweep's result that was never fetched - without
        // this, a request_sweep() issued right after this sweep starts can
        // return stale data left over from before, instead of either
        // "nothing ready yet" or this sweep's own fresh result. Found
        // on-target: a bulk-dump ack fired 1.5 ms after "sweep starting",
        // far too fast to be this sweep's real (multi-second) result.
        let _ = take_last_sweep();
        TRACER_ACTIVE.store(true, Ordering::Relaxed);
        RELAY_ENGAGED.store(true, Ordering::Relaxed);
        self.tracer_en.set_high();

        let mut points = [(0u16, 0u16); TRACER_SWEEP_POINTS];
        let mut points_captured: usize = 0;
        let mut aborted = false;

        // Find where this panel's Isc actually sits before recording
        // anything - a fixed full-scale sweep would spend all but its
        // first point past the knee (see `auto_range`).
        let sweep_top = match self.auto_range().await {
            Some(top) => top,
            None => {
                aborted = true;
                0
            }
        };

        for (step, point) in points.iter_mut().enumerate() {
            if aborted {
                break;
            }
            let duty = sweep_duty_for_step(step, sweep_top);
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

            if breach(v_mv, i_ma) {
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
            publish_progress(SweepProgress {
                index: step as u8,
                v_mv,
                i_ma,
                active: true,
                final_point: false,
            });
        }

        // Always stop driving the bleed load and hand the gate back,
        // breach or not - this must not depend on how the loop above
        // exited. Duty 0 commands 0 A, so Q3 turns fully off and the
        // panel is left at open circuit rather than loaded: nothing
        // should be drawing from it between sweeps. The relay is left as
        // is - it no longer auto-releases here, only `release_relay()`
        // does - so the panel stays on the tracer path, open circuit,
        // ready for the next sweep.
        self.set_pwm(0);
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

        // One last progress update marking the sweep over - `active: false`
        // is what tells the Pi to stop drawing `partial` and trust the bulk
        // read instead. Index 0xFF (same sentinel as "no sweep has ever
        // run") if the sweep produced zero points (e.g. auto_range aborted
        // immediately) - there is no real last point to report.
        let (last_v_mv, last_i_ma) = if points_captured > 0 {
            points[points_captured - 1]
        } else {
            (0, 0)
        };
        publish_progress(SweepProgress {
            index: if points_captured > 0 {
                (points_captured - 1) as u8
            } else {
                0xFF
            },
            v_mv: last_v_mv,
            i_ma: last_i_ma,
            active: false,
            final_point: true,
        });

        // Publish for the SPI bulk-read path - overwrites whatever the
        // previous sweep left, fetched or not; only the most recent
        // sweep's result is ever available to fetch.
        critical_section::with(|cs| {
            *LAST_SWEEP.borrow(cs).borrow_mut() = Some(SweepResult {
                points,
                count: points_captured,
            });
        });
    }

    /// Replays a stored curve through the same progress and bulk-read
    /// path a real sweep uses, touching neither the relay nor the current
    /// sink. Lets the Pi, the server and the web UI be exercised end to
    /// end over real SPI with no panel, no lamp and nothing dissipating
    /// in Q3 - unlike the server's own `--demo` mode, which fakes the
    /// source on the Pi and so never exercises this link at all.
    ///
    /// Paced at `TRACER_SETTLE_MS` per point so the live draw behaves the
    /// way a real sweep does.
    async fn run_demo_sweep(&mut self, curve: usize) {
        let points = DEMO_CURVES[curve.min(DEMO_CURVES.len() - 1)];
        defmt::info!("curve_tracer: demo sweep replaying curve {}", curve);
        let _ = take_last_sweep();
        TRACER_ACTIVE.store(true, Ordering::Relaxed);

        for (idx, (v_mv, i_ma)) in points.iter().enumerate() {
            Timer::after_millis(TRACER_SETTLE_MS).await;
            publish_progress(SweepProgress {
                index: idx as u8,
                v_mv: *v_mv,
                i_ma: *i_ma,
                active: true,
                final_point: false,
            });
        }

        TRACER_ACTIVE.store(false, Ordering::Relaxed);
        let (last_v_mv, last_i_ma) = points[TRACER_SWEEP_POINTS - 1];
        publish_progress(SweepProgress {
            index: (TRACER_SWEEP_POINTS - 1) as u8,
            v_mv: last_v_mv,
            i_ma: last_i_ma,
            active: false,
            final_point: true,
        });
        critical_section::with(|cs| {
            *LAST_SWEEP.borrow(cs).borrow_mut() = Some(SweepResult {
                points,
                count: TRACER_SWEEP_POINTS,
            });
        });
    }

    /// Explicitly disconnects the panel from the tracer path and hands it
    /// back to the SEPIC. The relay otherwise stays engaged across any
    /// number of sweeps - it is no longer released automatically when a
    /// sweep ends. Safe to call whether or not a sweep is in progress or
    /// the relay is already released.
    fn release_relay(&mut self) {
        self.set_pwm(0);
        self.tracer_en.set_low();
        // Cleared only after the relay has actually opened, so main.rs's
        // loop (which gates the SEPIC gate duty on this) never sees "safe
        // to resume driving" a tick before the panel is really back on
        // the SEPIC path.
        RELAY_ENGAGED.store(false, Ordering::Relaxed);
    }
}

/// Bumped once per `sensors_task` INA229 read (`main.rs`), independent of
/// `ADC_SAMPLE_COUNT` (which tracks `onchip_adc_task`'s on-chip-ADC
/// readings instead, a different task on a much slower ~100 ms cadence) -
/// averaging `MEAS_V_MV`/`MEAS_I_MA` needs a counter on *that* data's own
/// publish rate, not a different task's.
pub static INA_SAMPLE_COUNT: AtomicU32 = AtomicU32::new(0);

/// Waits for either a debounced `But1` press or a Pi-issued
/// `TracerCommand`, acts on it, repeats. A trigger while a sweep is
/// already running is impossible by construction - the task is
/// single-threaded and spends the whole sweep inside `run_sweep()`, not
/// polling either trigger source.
#[embassy_executor::task]
pub async fn curve_tracer_task(mut tracer: CurveTracer) {
    loop {
        match select(tracer.but1.wait_for_falling_edge(), TRACER_COMMAND.wait()).await {
            Either::First(()) => {
                Timer::after_millis(BUTTON_DEBOUNCE_MS).await;
                if tracer.but1.is_high() {
                    // Debounce rejected a glitch, not a real press.
                    continue;
                }

                tracer.run_sweep().await;

                // Wait for release before re-arming, so a still-held
                // button can't immediately retrigger the next sweep.
                tracer.but1.wait_for_high().await;
            }
            Either::Second(TracerCommand::StartSweep) => {
                tracer.run_sweep().await;
            }
            Either::Second(TracerCommand::DemoSweep(curve)) => {
                tracer.run_demo_sweep(curve).await;
            }
            Either::Second(TracerCommand::ReleaseRelay) => {
                tracer.release_relay();
            }
        }
    }
}
