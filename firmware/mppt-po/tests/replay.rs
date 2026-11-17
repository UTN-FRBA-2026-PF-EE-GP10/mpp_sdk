//! Replays Python reference traces. Equality is exact: duty and step are whole
//! u16 counts, so the float reference has no rounding that could differ.

use mppt_po::{Config, PerturbAndObserve};

fn replay(name: &str, csv: &str) {
    let mut po = PerturbAndObserve::new(Config::DEFAULT);
    let mut rows = 0;
    for (n, line) in csv.lines().skip(1).enumerate() {
        let f: Vec<u16> = line.split(',').map(|x| x.parse().unwrap()).collect();
        assert_eq!(po.step(f[0], f[1]), f[2], "{name} row {n}");
        rows += 1;
    }
    assert!(rows >= 100, "{name}: fixture too short");
}

#[test]
fn full_sun() {
    replay("full_sun", include_str!("fixtures/po_full_sun.csv"));
}

#[test]
fn half_sun() {
    replay("half_sun", include_str!("fixtures/po_half_sun.csv"));
}

#[test]
fn low_sun_small_load() {
    replay(
        "low_sun_small_load",
        include_str!("fixtures/po_low_sun_small_load.csv"),
    );
}

#[test]
fn clamps_at_limits() {
    let mut po = PerturbAndObserve::new(Config {
        initial_duty: 100,
        step: 66,
        min_duty: 50,
        max_duty: 150,
    });
    for k in 0..10u16 {
        // P rises while V falls: duty goes up every step.
        assert!(po.step(3000 - 10 * k, 1000 + 100 * k) <= 150);
    }
    assert_eq!(po.duty(), 150);
}
