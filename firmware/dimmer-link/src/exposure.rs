//! Exposure limiter of the lamp: a leaky bucket of the time the lamp is
//! commanded on. Pure and `no_std`, so the rules run as host unit tests.
//!
//! The bucket counts commanded time, not real firing, so it also runs with no
//! mains. It fills 1 ms per ms while the lamp is on and drains 1 ms per ms
//! while it is off. At `EXPOSURE_MAX_ON_MS` it trips and latches. The latch
//! clears only when the bucket is down to `EXPOSURE_RESUME_MS` AND the host
//! sent an explicit OFF after the trip, so a host that keeps repeating its old
//! "on" command never gets an automatic restart.

use crate::{EXPOSURE_MAX_ON_MS, EXPOSURE_RESUME_MS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Exposure {
    heat_ms: u32,
    /// Clock value the bucket is advanced to. The clock starts at 0 at boot,
    /// so time before the first call counts too.
    last_ms: u32,
    tripped: bool,
    /// An explicit host OFF arrived since the trip.
    off_seen: bool,
}

impl Default for Exposure {
    fn default() -> Self {
        Self::new()
    }
}

impl Exposure {
    pub const fn new() -> Self {
        Self {
            heat_ms: 0,
            last_ms: 0,
            tripped: false,
            off_seen: false,
        }
    }

    /// Advances the bucket to `now_ms` (wrapping clock). `on` is the state the
    /// lamp was commanded to since the last tick. A long gap between ticks is
    /// counted as one block of that state, which is the safe side for "on".
    pub fn tick(&mut self, now_ms: u32, on: bool) {
        let dt = now_ms.wrapping_sub(self.last_ms);
        self.last_ms = now_ms;
        if on {
            // Capped at the trip level, so a stall does not lengthen the cool-down.
            self.heat_ms = self.heat_ms.saturating_add(dt).min(EXPOSURE_MAX_ON_MS);
            if self.heat_ms >= EXPOSURE_MAX_ON_MS && !self.tripped {
                self.tripped = true;
                self.off_seen = false;
            }
        } else {
            self.heat_ms = self.heat_ms.saturating_sub(dt);
        }
        self.try_clear();
    }

    /// The one decision for a new lamp command: `prev_on` is the state until now,
    /// `new_on` the state the command asks for. The bucket is first advanced to
    /// `now_ms` with the PREVIOUS state, so a short on-time between two loop ticks
    /// is still counted. Returns false when an on-command is refused.
    ///
    /// `explicit_off` is true only for an OFF the host asked for. The deadman and the
    /// limiter's own forced off pass false: they must not acknowledge a trip.
    pub fn apply(&mut self, now_ms: u32, prev_on: bool, new_on: bool, explicit_off: bool) -> bool {
        self.tick(now_ms, prev_on);
        if new_on {
            return self.on_command();
        }
        if explicit_off {
            self.off_command();
        }
        true
    }

    /// The host asked for a lamp on. Never changes state; returns whether the
    /// command may be applied.
    pub fn on_command(&self) -> bool {
        self.allows_on()
    }

    /// The host sent an explicit OFF (not the deadman, not the trip itself).
    pub fn off_command(&mut self) {
        if self.tripped {
            self.off_seen = true;
            self.try_clear();
        }
    }

    pub fn allows_on(&self) -> bool {
        !self.tripped
    }

    pub fn tripped(&self) -> bool {
        self.tripped
    }

    /// Not tripped: whole seconds of on time left before a trip. Tripped:
    /// seconds until the bucket reaches the resume level (0 means cooled and
    /// waiting for the host OFF). Saturates at 255.
    pub fn budget_s(&self) -> u8 {
        let secs = if self.tripped {
            // Round up, so 0 only means really cooled.
            self.heat_ms
                .saturating_sub(EXPOSURE_RESUME_MS)
                .div_ceil(1_000)
        } else {
            (EXPOSURE_MAX_ON_MS - self.heat_ms) / 1_000
        };
        secs.min(u8::MAX as u32) as u8
    }

    fn try_clear(&mut self) {
        if self.tripped && self.off_seen && self.heat_ms <= EXPOSURE_RESUME_MS {
            self.tripped = false;
            self.off_seen = false;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Ticks every `step` ms for `total` ms with the same `on`; returns the clock.
    fn run(e: &mut Exposure, mut now: u32, total: u32, step: u32, on: bool) -> u32 {
        let mut left = total;
        while left > 0 {
            let dt = step.min(left);
            now = now.wrapping_add(dt);
            e.tick(now, on);
            left -= dt;
        }
        now
    }

    fn started() -> (Exposure, u32) {
        (Exposure::new(), 0)
    }

    #[test]
    fn a_fresh_bucket_allows_on_with_the_full_budget() {
        let e = Exposure::new();
        assert!(e.allows_on() && !e.tripped());
        assert_eq!(e.budget_s(), 120);
    }

    #[test]
    fn trips_after_exactly_the_max_on_time_in_10_ms_ticks() {
        let (mut e, now) = started();
        let now = run(&mut e, now, EXPOSURE_MAX_ON_MS - 10, 10, true);
        assert!(!e.tripped());
        run(&mut e, now, 10, 10, true);
        assert!(e.tripped());
    }

    #[test]
    fn trips_after_exactly_the_max_on_time_in_one_tick() {
        let (mut e, _) = started();
        e.tick(EXPOSURE_MAX_ON_MS - 1, true);
        assert!(!e.tripped());
        e.tick(EXPOSURE_MAX_ON_MS, true);
        assert!(e.tripped());
    }

    #[test]
    fn a_long_stall_while_on_trips_and_does_not_overfill() {
        let (mut e, _) = started();
        e.tick(3_600_000, true);
        assert!(e.tripped());
        // Capped at the trip level: the cool-down takes max - resume, not an hour.
        assert_eq!(
            e.budget_s() as u32,
            (EXPOSURE_MAX_ON_MS - EXPOSURE_RESUME_MS) / 1_000
        );
    }

    #[test]
    fn a_stalled_tick_over_the_clock_wrap_counts_the_real_time() {
        let mut e = Exposure::new();
        let start = u32::MAX - 50_000;
        e.tick(start, false);
        // 100 s later, across the wrap.
        let mid = start.wrapping_add(100_000);
        e.tick(mid, true);
        assert!(!e.tripped());
        assert_eq!(e.budget_s(), 20);
        e.tick(mid.wrapping_add(20_000), true);
        assert!(e.tripped());
    }

    #[test]
    fn ticks_across_the_wrap_keep_counting() {
        let mut e = Exposure::new();
        let start = u32::MAX - 5_000;
        e.tick(start, false);
        run(&mut e, start, EXPOSURE_MAX_ON_MS, 10, true);
        assert!(e.tripped());
    }

    #[test]
    fn the_bucket_never_goes_below_zero() {
        let (mut e, now) = started();
        let now = run(&mut e, now, 10_000, 10, true);
        run(&mut e, now, 1_000_000, 1_000, false);
        assert_eq!(e.budget_s(), 120);
        assert!(!e.tripped());
    }

    #[test]
    fn repeated_short_windows_fill_the_bucket() {
        let (mut e, mut now) = started();
        // 10 s on, 5 s off: net 5 s per cycle. The 23rd window ends at 120 s.
        let mut windows = 0;
        while !e.tripped() {
            assert!(windows < 100, "never tripped");
            now = run(&mut e, now, 10_000, 10, true);
            windows += 1;
            if !e.tripped() {
                now = run(&mut e, now, 5_000, 10, false);
            }
        }
        assert_eq!(windows, 23);
    }

    #[test]
    fn a_tripped_lamp_resumes_only_after_cool_down_and_off() {
        let (mut e, now) = started();
        let now = run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, true);
        assert!(e.tripped());
        assert!(!e.on_command());
        run(
            &mut e,
            now,
            EXPOSURE_MAX_ON_MS - EXPOSURE_RESUME_MS,
            10,
            false,
        );
        // Cooled, but no OFF yet: still latched, budget 0 means "send OFF".
        assert!(e.tripped());
        assert_eq!(e.budget_s(), 0);
        e.off_command();
        assert!(!e.tripped());
        assert!(e.allows_on());
        assert_eq!(e.budget_s(), 60);
    }

    #[test]
    fn a_stream_of_on_commands_never_clears_the_latch() {
        let (mut e, mut now) = started();
        now = run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, true);
        for _ in 0..100_000 {
            assert!(!e.on_command());
            now = run(&mut e, now, 10, 10, false);
            assert!(!e.allows_on());
        }
        assert!(e.tripped());
        assert_eq!(e.budget_s(), 0);
    }

    #[test]
    fn an_off_before_the_cool_down_ends_is_remembered() {
        let (mut e, now) = started();
        let now = run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, true);
        let now = run(&mut e, now, 10_000, 10, false);
        e.off_command();
        assert!(e.tripped());
        // 50 s to go, then it clears by itself, with no new OFF.
        let now = run(&mut e, now, 49_990, 10, false);
        assert!(e.tripped());
        run(&mut e, now, 10, 10, false);
        assert!(!e.tripped());
    }

    #[test]
    fn an_off_before_the_trip_does_not_count() {
        let (mut e, now) = started();
        e.off_command();
        let now = run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, true);
        assert!(e.tripped());
        run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, false);
        assert!(e.tripped());
    }

    #[test]
    fn an_off_while_not_tripped_changes_nothing() {
        let (mut e, now) = started();
        run(&mut e, now, 30_000, 10, true);
        e.off_command();
        assert!(!e.tripped());
        assert_eq!(e.budget_s(), 90);
    }

    #[test]
    fn the_resume_level_is_inclusive() {
        let (mut e, now) = started();
        let now = run(&mut e, now, EXPOSURE_MAX_ON_MS, 10, true);
        e.off_command();
        let now = run(
            &mut e,
            now,
            EXPOSURE_MAX_ON_MS - EXPOSURE_RESUME_MS - 10,
            10,
            false,
        );
        assert!(e.tripped());
        run(&mut e, now, 10, 10, false);
        assert!(!e.tripped());
    }

    #[test]
    fn budget_counts_down_while_on_and_up_while_off() {
        let (mut e, now) = started();
        let now = run(&mut e, now, 10_500, 10, true);
        assert_eq!(e.budget_s(), 109);
        run(&mut e, now, 5_000, 10, false);
        assert_eq!(e.budget_s(), 114);
    }

    #[test]
    fn budget_saturates_at_255() {
        // Unreachable with the shipped constants (max 120 s), so set the state
        // directly: this pins the clamp for a later, larger constant.
        let mut e = Exposure::new();
        e.tripped = true;
        e.heat_ms = EXPOSURE_RESUME_MS + 300_000;
        assert_eq!(e.budget_s(), 255);
    }

    #[test]
    fn budget_is_exact_at_the_limits() {
        let (mut e, now) = started();
        assert_eq!(e.budget_s(), 120);
        run(&mut e, now, EXPOSURE_MAX_ON_MS, 1_000, true);
        assert!(e.tripped());
        assert_eq!(e.budget_s(), 60);
    }

    #[test]
    fn time_before_the_first_tick_counts() {
        let mut e = Exposure::new();
        e.tick(EXPOSURE_MAX_ON_MS, true);
        assert!(e.tripped());
    }

    #[test]
    fn an_on_command_before_the_first_tick_counts_from_boot() {
        let mut e = Exposure::new();
        assert!(e.apply(3_000, false, true, false));
        // The loop starts 200 s later and sees the lamp on the whole time.
        e.tick(3_000 + EXPOSURE_MAX_ON_MS, true);
        assert!(e.tripped());
    }

    #[test]
    fn tripped_budget_rounds_up() {
        let mut e = Exposure::new();
        e.tripped = true;
        e.heat_ms = EXPOSURE_RESUME_MS + 500;
        assert_eq!(e.budget_s(), 1);
        e.heat_ms = EXPOSURE_RESUME_MS;
        assert_eq!(e.budget_s(), 0);
    }

    #[test]
    fn a_budget_of_0_can_still_allow_on() {
        let (mut e, _) = started();
        e.tick(EXPOSURE_MAX_ON_MS - 500, true);
        assert_eq!(e.budget_s(), 0);
        assert!(!e.tripped());
        assert!(e.allows_on());
    }

    #[test]
    fn apply_counts_the_previous_state_up_to_the_command() {
        let (mut e, _) = started();
        assert!(e.apply(0, false, true, false));
        assert!(e.apply(60_000, true, false, true));
        assert_eq!(e.budget_s(), 60);
    }

    #[test]
    fn toggling_between_loop_ticks_is_still_counted() {
        // On for 9 ms, off for 1 ms, with the loop tick only every 10 ms and always
        // seeing the lamp off. The commands themselves carry the on time.
        let mut e = Exposure::new();
        let mut now = 0u32;
        let mut on = false;
        for _ in 0..100_000 {
            assert!(e.apply(now, on, true, false) || e.tripped());
            on = !e.tripped();
            now += 9;
            e.apply(now, on, false, true);
            on = false;
            now += 1;
            e.tick(now, on);
            if e.tripped() {
                break;
            }
        }
        // 90 percent duty trips after 120 s / (0.9 - 0.1) = 150 s.
        assert!(e.tripped());
        assert!(now <= 150_010, "tripped late, at {now} ms");
    }

    #[test]
    fn an_on_command_that_finds_the_bucket_full_is_refused() {
        let (mut e, _) = started();
        assert!(e.apply(0, false, true, false));
        assert!(!e.apply(EXPOSURE_MAX_ON_MS, true, true, false));
        assert!(e.tripped());
    }

    #[test]
    fn only_an_explicit_off_acknowledges_a_trip() {
        let (mut e, _) = started();
        e.tick(EXPOSURE_MAX_ON_MS, true);
        // The deadman and the forced off pass explicit_off = false.
        e.apply(EXPOSURE_MAX_ON_MS + 1, false, false, false);
        e.tick(EXPOSURE_MAX_ON_MS + 100_000, false);
        assert!(e.tripped());
        assert!(!e.apply(EXPOSURE_MAX_ON_MS + 100_001, false, true, false));
        assert!(e.apply(EXPOSURE_MAX_ON_MS + 100_002, false, false, true));
        assert!(!e.tripped());
    }

    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }
    }

    /// Mimics main.rs: `lamp_on` is FRACTION != OFF.
    struct Fw {
        e: Exposure,
        lamp_on: bool,
    }
    impl Fw {
        fn cmd_on(&mut self, now: u32) -> bool {
            let ok = self.e.apply(now, self.lamp_on, true, false);
            self.lamp_on = ok;
            ok
        }
        fn cmd_off(&mut self, now: u32) {
            self.e.apply(now, self.lamp_on, false, true);
            self.lamp_on = false;
        }
        fn loop_tick(&mut self, now: u32) {
            self.e.tick(now, self.lamp_on);
            if self.e.tripped() {
                self.lamp_on = false;
            }
        }
    }

    /// Random commands against a plain reference model, also across the clock wrap.
    #[test]
    fn random_sequences_match_reference() {
        for seed in 1..40u64 {
            let mut r = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
            let start = if seed % 3 == 0 {
                u32::MAX - (r.next() % 200_000) as u32
            } else {
                0
            };
            let mut fw = Fw {
                e: Exposure::new(),
                lamp_on: false,
            };
            let mut now = start;
            fw.loop_tick(now);
            let mut heat: i64 = 0;
            let mut tripped = false;
            let mut off_seen = false;
            let mut cont_on: u32 = 0;
            let mut worst_cont = 0u32;
            let mut on_ms: u64 = 0;
            let mut off_ms: u64 = 0;
            let max = EXPOSURE_MAX_ON_MS as i64;
            let res = EXPOSURE_RESUME_MS as i64;
            for _step in 0..4_000 {
                let a = r.next() % 100;
                let dur = match r.next() % 4 {
                    0 => 10,
                    1 => 100,
                    2 => 1000,
                    _ => 10_000,
                } as u32;
                if a < 45 {
                    let ok = fw.cmd_on(now);
                    assert_eq!(ok, !tripped, "seed {seed}");
                } else if a < 75 {
                    fw.cmd_off(now);
                    if tripped {
                        off_seen = true;
                        if heat <= res {
                            tripped = false;
                            off_seen = false;
                        }
                    }
                }
                let mut left = dur;
                while left > 0 {
                    let dt = left.min(10);
                    left -= dt;
                    now = now.wrapping_add(dt);
                    let on = fw.lamp_on;
                    fw.loop_tick(now);
                    if on {
                        heat = (heat + dt as i64).min(max);
                        cont_on += dt;
                        on_ms += dt as u64;
                        if heat >= max && !tripped {
                            tripped = true;
                            off_seen = false;
                        }
                    } else {
                        heat = (heat - dt as i64).max(0);
                        cont_on = 0;
                        off_ms += dt as u64;
                    }
                    if tripped && off_seen && heat <= res {
                        tripped = false;
                        off_seen = false;
                    }
                    worst_cont = worst_cont.max(cont_on);
                    assert_eq!(fw.e.tripped(), tripped, "seed {seed} now {now}");
                    assert_eq!(fw.e.allows_on(), !tripped);
                    if tripped {
                        assert!(!fw.lamp_on);
                    }
                    let b = fw.e.budget_s() as i64;
                    if !tripped {
                        assert!(b * 1000 <= max - heat, "seed {seed}");
                    } else {
                        assert!(b * 1000 >= heat - res);
                    }
                }
            }
            assert!(
                worst_cont <= EXPOSURE_MAX_ON_MS + 10,
                "seed {seed} cont {worst_cont}"
            );
            assert!(
                on_ms <= off_ms + EXPOSURE_MAX_ON_MS as u64 + 10,
                "seed {seed}"
            );
        }
    }
}
