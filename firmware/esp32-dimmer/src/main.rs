//! Phase-control firmware for the 220 Vac halogen dimmer.
//!
//! - ZC (GPIO3): H11AA1 output with the internal pull-up. It is low while the
//!   mains voltage is high and pulses high around every zero crossing, so the
//!   middle of each pulse is the true zero crossing.
//! - FIRE (GPIO4): drives the MOC3052 LED through Q1. High fires the TRIAC.
//!
//! Safety behaviour:
//! - The lamp is off at every boot, and the level is never stored.
//! - Firing needs `LOCK_HALF_CYCLES` consecutive valid zero crossings. Any
//!   invalid or missing crossing stops firing until the lock is regained.
//! - A firing pulse is skipped rather than sent late, so a delayed pulse can
//!   never spill into the next half-cycle.
//!
//! Control is over I2C from the Pico (slave at `I2C_ADDRESS`). With the `wifi`
//! feature a phone can also control it over Wi-Fi, until the first I2C command
//! arrives. If valid I2C commands stop, the lamp goes off (deadman).

use std::ffi::c_void;
use std::ptr;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicU32, AtomicU8, Ordering::Relaxed};
use std::thread;
use std::time::Duration;

use anyhow::{bail, Result};
use dimmer_link::slave::{applied_alpha, command_timed_out};
use dimmer_link::{
    alpha_to_fraction, decode_command, encode_status, flags, Command, Status, ALPHA_OFF, COMMAND_LEN,
    COMMAND_TIMEOUT_MS, FRACTION_FULL, FRACTION_OFF, I2C_ADDRESS,
};
use esp_idf_svc::hal::delay::TickType;
use esp_idf_svc::hal::i2c::{I2cSlaveConfig, I2cSlaveDriver};
use esp_idf_svc::hal::peripherals::Peripherals;
use esp_idf_svc::sys::{self, esp};
use log::info;
#[cfg(feature = "wifi")]
use esp_idf_svc::eventloop::EspSystemEventLoop;
#[cfg(feature = "wifi")]
use esp_idf_svc::http::server::{Configuration as HttpConfig, EspHttpServer};
#[cfg(feature = "wifi")]
use esp_idf_svc::http::Method;
#[cfg(feature = "wifi")]
use esp_idf_svc::io::Write;
#[cfg(feature = "wifi")]
use esp_idf_svc::wifi::{AccessPointConfiguration, AuthMethod, BlockingWifi, Configuration, EspWifi};

const ZC_GPIO: i32 = 3;
const FIRE_GPIO: i32 = 4;
/// SuperMini blue LED (active low): shows the firmware is alive without a USB cable.
const LED_GPIO: i32 = 8;

/// Accepted ZC pulse width (µs). On the first board the H11AA1 switches very close to
/// zero and the pulses are only 30–100 µs wide (the design estimate was 2.2 ms).
const ZC_WIDTH_US: (u32, u32) = (10, 5_000);
/// Accepted half-period between zero crossings (µs): 40 to 62.5 Hz mains.
const HALF_PERIOD_US: (u32, u32) = (8_000, 12_500);
/// Consecutive valid half-cycles needed before firing.
const LOCK_HALF_CYCLES: u32 = 8;
/// The ZC level is sampled this many times, `ZC_SAMPLE_US` apart, after every edge;
/// the majority decides the level, so short noise spikes are ignored.
const ZC_SAMPLES: u32 = 4;
const ZC_SAMPLE_US: u32 = 2;
/// No ZC edge for this long means mains is gone (µs).
const ZC_TIMEOUT_US: u32 = 30_000;

/// Earliest firing after the zero crossing (µs). The crossing is only known
/// when the ZC pulse ends; this also leaves margin for a wider pulse on another board.
const MIN_DELAY_US: u32 = 1_400;
/// Latest firing, measured back from the next zero crossing (µs).
const MIN_TAIL_US: u32 = 1_500;
/// A pulse that would start later than this before the next crossing is dropped (µs).
const LATE_LIMIT_US: u32 = 1_000;
/// MOC3052 LED pulse length (µs).
const FIRE_PULSE_US: u32 = 150;
/// Optocoupler LED test length (only allowed with no mains present).
const OPTO_TEST: Duration = Duration::from_secs(30);

/// A partial command frame older than this is dropped, so a glitch cannot shift later frames.
const I2C_READ_TIMEOUT_MS: u64 = 20;

#[cfg(feature = "wifi")]
const AP_SSID: &str = "esp32-dimmer";
// Set at build time so no password lives in the repository.
#[cfg(feature = "wifi")]
const AP_PASS: &str = env!("DIMMER_AP_PASS");
// WPA2 needs 8 to 63 characters.
#[cfg(feature = "wifi")]
const _: () = assert!(AP_PASS.len() >= 8 && AP_PASS.len() <= 63, "DIMMER_AP_PASS must have 8 to 63 characters");

// Firing delay as a fraction of the half-period, 0..=65536 (constants from dimmer-link).
// `FRACTION_OFF` never fires; `FRACTION_FULL` keeps FIRE high while locked.
static FRACTION: AtomicU32 = AtomicU32::new(FRACTION_OFF);
static LEVEL: AtomicU32 = AtomicU32::new(0);

/// Set by the first valid I2C `SetAlpha`; from then on the deadman is armed.
static ARMED: AtomicBool = AtomicBool::new(false);
/// Lamp was switched off by the deadman, until the next valid `SetAlpha`.
static TIMED_OUT: AtomicBool = AtomicBool::new(false);
/// Milliseconds clock (wrapping) at the last valid `SetAlpha`.
static LAST_COMMAND_MS: AtomicU32 = AtomicU32::new(0);
/// Rejected I2C frames (wraps).
static BAD_FRAMES: AtomicU8 = AtomicU8::new(0);
static OPTO_TEST_ON: AtomicBool = AtomicBool::new(false);
/// Bumped on every LED test start or stop, so an old timer cannot end a newer test.
static OPTO_TEST_GEN: AtomicU32 = AtomicU32::new(0);

// Zero-cross state. Written only by the ZC interrupt (and reset by the watchdog).
static RISE_US: AtomicU32 = AtomicU32::new(0);
/// Accepted (debounced) ZC level.
static ZC_HIGH: AtomicBool = AtomicBool::new(false);
static LAST_ZERO_US: AtomicU32 = AtomicU32::new(0);
static HALF_US: AtomicU32 = AtomicU32::new(0);
static WIDTH_US: AtomicU32 = AtomicU32::new(0);
static GOOD: AtomicU32 = AtomicU32::new(0);
static EDGES: AtomicU32 = AtomicU32::new(0);
/// Pulses at least `ZC_WIDTH_US.0` wide: real zero-cross pulses, not probe glitches.
static PULSES: AtomicU32 = AtomicU32::new(0);
static LAST_PULSE_US: AtomicU32 = AtomicU32::new(0);
/// Edges whose level did not change after sampling (noise) and pulses rejected as invalid.
static NOISE: AtomicU32 = AtomicU32::new(0);
static INVALID: AtomicU32 = AtomicU32::new(0);
static MISSED: AtomicU32 = AtomicU32::new(0);
/// Extremes over the current one-second window, reset by the main loop.
static WIN_WIDTH: (AtomicU32, AtomicU32) = (AtomicU32::new(u32::MAX), AtomicU32::new(0));
static WIN_HALF: (AtomicU32, AtomicU32) = (AtomicU32::new(u32::MAX), AtomicU32::new(0));
/// Last completed one-second window, as a JSON fragment for /status.
static ZC_STATS: std::sync::Mutex<String> = std::sync::Mutex::new(String::new());
static FIRED: AtomicU32 = AtomicU32::new(0);
static SKIPPED: AtomicU32 = AtomicU32::new(0);

/// The zero crossing the pending firing timer belongs to. A callback that runs after a
/// newer crossing (a delayed esp_timer task) sees a mismatch and does not fire.
static TARGET_ZERO_US: AtomicU32 = AtomicU32::new(0);

static FIRE_TIMER: AtomicPtr<sys::esp_timer> = AtomicPtr::new(ptr::null_mut());

fn now_us() -> u32 {
    // Truncated to 32 bits; all arithmetic below is wrapping, so this wraps safely every 71 min.
    unsafe { sys::esp_timer_get_time() as u32 }
}

fn now_ms() -> u32 {
    (unsafe { sys::esp_timer_get_time() } / 1_000) as u32
}

fn fire(on: bool) {
    unsafe { sys::gpio_set_level(FIRE_GPIO, on as u32) };
}

fn led(on: bool) {
    unsafe { sys::gpio_set_level(LED_GPIO, !on as u32) };
}

fn locked() -> bool {
    GOOD.load(Relaxed) >= LOCK_HALF_CYCLES
}

/// Zero-cross pulses are arriving.
fn mains_present() -> bool {
    let since_pulse = now_us().wrapping_sub(LAST_PULSE_US.load(Relaxed));
    PULSES.load(Relaxed) > 0 && since_pulse < ZC_TIMEOUT_US
}

/// Stops firing immediately and forgets the zero-cross lock.
fn unlock() {
    GOOD.store(0, Relaxed);
    let timer = FIRE_TIMER.load(Relaxed);
    if !timer.is_null() {
        unsafe { sys::esp_timer_stop(timer) };
    }
    fire(false);
}

/// ZC edge interrupt.
unsafe extern "C" fn zc_isr(_: *mut c_void) {
    let now = now_us();
    EDGES.fetch_add(1, Relaxed);

    let mut ones = 0;
    for _ in 0..ZC_SAMPLES {
        ones += sys::gpio_get_level(ZC_GPIO) as u32;
        sys::esp_rom_delay_us(ZC_SAMPLE_US);
    }
    let high = 2 * ones > ZC_SAMPLES;
    if ZC_HIGH.swap(high, Relaxed) == high {
        // The level did not really change: a spike or a bounce on a slow edge.
        NOISE.fetch_add(1, Relaxed);
        return;
    }
    if high {
        RISE_US.store(now, Relaxed);
        return;
    }

    // Falling edge: the pulse just ended; its middle is the zero crossing.
    let width = now.wrapping_sub(RISE_US.load(Relaxed));
    WIN_WIDTH.0.fetch_min(width, Relaxed);
    WIN_WIDTH.1.fetch_max(width, Relaxed);
    if width < ZC_WIDTH_US.0 {
        // Too short to be a zero-cross pulse: switching noise on a slow edge. Ignore it.
        return;
    }
    LAST_PULSE_US.store(now, Relaxed);
    PULSES.fetch_add(1, Relaxed);
    if OPTO_TEST_ON.swap(false, Relaxed) {
        // Mains appeared during the LED test: end it at once.
        fire(false);
    }
    let zero = RISE_US.load(Relaxed).wrapping_add(width / 2);
    let half = zero.wrapping_sub(LAST_ZERO_US.swap(zero, Relaxed));
    WIDTH_US.store(width, Relaxed);
    WIN_HALF.0.fetch_min(half, Relaxed);
    WIN_HALF.1.fetch_max(half, Relaxed);

    // One missed pulse doubles the measured half-period. The zero crossing just seen is
    // still real, so keep the lock and use half of it.
    let in_range = |h: u32| (HALF_PERIOD_US.0..=HALF_PERIOD_US.1).contains(&h);
    let half = if locked() && !in_range(half) && in_range(half / 2) {
        MISSED.fetch_add(1, Relaxed);
        half / 2
    } else {
        half
    };
    HALF_US.store(half, Relaxed);
    let valid = width <= ZC_WIDTH_US.1 && in_range(half);
    if !valid {
        INVALID.fetch_add(1, Relaxed);
        unlock();
        return;
    }
    let good = GOOD.load(Relaxed);
    if good < LOCK_HALF_CYCLES {
        GOOD.store(good + 1, Relaxed);
        fire(false);
        return;
    }

    match FRACTION.load(Relaxed) {
        FRACTION_OFF => fire(false),
        FRACTION_FULL => fire(true),
        fraction => {
            fire(false);
            let delay = ((fraction as u64 * half as u64) >> 16) as u32;
            let delay = delay.clamp(MIN_DELAY_US, half - MIN_TAIL_US);
            let elapsed = now.wrapping_sub(zero);
            if delay > elapsed + 100 {
                TARGET_ZERO_US.store(zero, Relaxed);
                sys::esp_timer_start_once(FIRE_TIMER.load(Relaxed), (delay - elapsed) as u64);
            } else {
                SKIPPED.fetch_add(1, Relaxed);
            }
        }
    }
}

/// Firing timer callback (esp_timer task, high priority).
unsafe extern "C" fn fire_cb(_: *mut c_void) {
    let zero = LAST_ZERO_US.load(Relaxed);
    let since_zero = now_us().wrapping_sub(zero);
    let half = HALF_US.load(Relaxed);
    let fraction = FRACTION.load(Relaxed);
    let stale = zero != TARGET_ZERO_US.load(Relaxed);
    if !locked() || fraction == FRACTION_OFF || stale || since_zero > half.saturating_sub(LATE_LIMIT_US) {
        SKIPPED.fetch_add(1, Relaxed);
        return;
    }
    fire(true);
    sys::esp_rom_delay_us(FIRE_PULSE_US);
    fire(false);
    FIRED.fetch_add(1, Relaxed);
}

/// Power fraction (0..=1) of a resistive load fired at angle `alpha` (radians).
fn power_at(alpha: f64) -> f64 {
    use std::f64::consts::PI;
    1.0 - alpha / PI + (2.0 * alpha).sin() / (2.0 * PI)
}

/// The one place that changes the firing fraction, for both control paths.
fn set_fraction(percent: u32, fraction: u32) {
    // A level change ends the LED test, so the page never shows a test that is not running.
    stop_opto_test();
    LEVEL.store(percent, Relaxed);
    FRACTION.store(fraction, Relaxed);
    if fraction == FRACTION_OFF {
        fire(false);
    }
}

/// Sets the firing angle in 0.01 degree (the I2C unit): 0 = full on, 18000 = off.
fn set_alpha(alpha: u16) {
    let alpha_rad = alpha as f64 / ALPHA_OFF as f64 * std::f64::consts::PI;
    let percent = (power_at(alpha_rad) * 100.0).round().clamp(0.0, 100.0) as u32;
    set_fraction(percent, alpha_to_fraction(alpha));
}

/// Sets the lamp power in percent: 0 = off, 100 = full, otherwise phase control.
fn set_level(percent: u32) {
    let percent = percent.min(100);
    let fraction = match percent {
        0 => FRACTION_OFF,
        100 => FRACTION_FULL,
        p => {
            // Solve power_at(alpha) = p by bisection; power falls as alpha grows.
            let target = p as f64 / 100.0;
            let (mut lo, mut hi) = (0.0, std::f64::consts::PI);
            for _ in 0..40 {
                let mid = (lo + hi) / 2.0;
                if power_at(mid) > target {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            ((lo / std::f64::consts::PI) * 65536.0) as u32
        }
    };
    set_fraction(percent, fraction);
}

fn setup_gpio() -> Result<()> {
    unsafe {
        // FIRE first, as an output driven low, before anything else starts.
        esp!(sys::gpio_config(&sys::gpio_config_t {
            pin_bit_mask: 1 << FIRE_GPIO,
            mode: sys::gpio_mode_t_GPIO_MODE_OUTPUT,
            pull_up_en: sys::gpio_pullup_t_GPIO_PULLUP_DISABLE,
            pull_down_en: sys::gpio_pulldown_t_GPIO_PULLDOWN_ENABLE,
            intr_type: sys::gpio_int_type_t_GPIO_INTR_DISABLE,
        }))?;
        fire(false);

        esp!(sys::gpio_config(&sys::gpio_config_t {
            pin_bit_mask: 1 << LED_GPIO,
            mode: sys::gpio_mode_t_GPIO_MODE_OUTPUT,
            pull_up_en: sys::gpio_pullup_t_GPIO_PULLUP_DISABLE,
            pull_down_en: sys::gpio_pulldown_t_GPIO_PULLDOWN_DISABLE,
            intr_type: sys::gpio_int_type_t_GPIO_INTR_DISABLE,
        }))?;
        led(false);

        esp!(sys::gpio_config(&sys::gpio_config_t {
            pin_bit_mask: 1 << ZC_GPIO,
            mode: sys::gpio_mode_t_GPIO_MODE_INPUT,
            pull_up_en: sys::gpio_pullup_t_GPIO_PULLUP_ENABLE,
            pull_down_en: sys::gpio_pulldown_t_GPIO_PULLDOWN_DISABLE,
            intr_type: sys::gpio_int_type_t_GPIO_INTR_ANYEDGE,
        }))?;
        ZC_HIGH.store(sys::gpio_get_level(ZC_GPIO) == 1, Relaxed);

        let mut timer: sys::esp_timer_handle_t = ptr::null_mut();
        esp!(sys::esp_timer_create(
            &sys::esp_timer_create_args_t {
                callback: Some(fire_cb),
                arg: ptr::null_mut(),
                dispatch_method: sys::esp_timer_dispatch_t_ESP_TIMER_TASK,
                name: c"fire".as_ptr(),
                skip_unhandled_events: true,
            },
            &mut timer,
        ))?;
        FIRE_TIMER.store(timer, Relaxed);

        esp!(sys::gpio_install_isr_service(0))?;
        esp!(sys::gpio_isr_handler_add(ZC_GPIO, Some(zc_isr), ptr::null_mut()))?;
    }
    Ok(())
}

fn status_json() -> String {
    let half = HALF_US.load(Relaxed);
    let since_pulse = now_us().wrapping_sub(LAST_PULSE_US.load(Relaxed));
    let mains = PULSES.load(Relaxed) > 0 && since_pulse < ZC_TIMEOUT_US;
    let fraction = FRACTION.load(Relaxed);
    let delay_us = match fraction {
        FRACTION_OFF | FRACTION_FULL => 0,
        f if mains && half >= HALF_PERIOD_US.0 => {
            (((f as u64 * half as u64) >> 16) as u32).clamp(MIN_DELAY_US, half - MIN_TAIL_US)
        }
        _ => 0,
    };
    let freq = if mains && half > 0 { 500_000.0 / half as f32 } else { 0.0 };
    format!(
        "{{\"level\":{},\"mains\":{},\"locked\":{},\"freq_hz\":{:.2},\"zc_width_us\":{},\"delay_us\":{},\"fired\":{},\"skipped\":{},\"opto_test\":{},{}}}",
        LEVEL.load(Relaxed),
        mains,
        mains && locked(),
        freq,
        if mains { WIDTH_US.load(Relaxed) } else { 0 },
        delay_us,
        FIRED.load(Relaxed),
        SKIPPED.load(Relaxed),
        OPTO_TEST_ON.load(Relaxed),
        match ZC_STATS.lock().unwrap().as_str() {
            "" => "\"zc\":null",
            stats => stats,
        },
    )
}

/// Turns FIRE on for a few seconds to check the MOC3052 LED current, only with no mains.
#[cfg_attr(not(feature = "wifi"), allow(dead_code))]
fn start_opto_test() -> Result<()> {
    let since_pulse = now_us().wrapping_sub(LAST_PULSE_US.load(Relaxed));
    if PULSES.load(Relaxed) > 0 && since_pulse < 1_000_000 {
        bail!("mains detected: the LED test only runs with mains disconnected");
    }
    if OPTO_TEST_ON.load(Relaxed) {
        bail!("the LED test is already running");
    }
    let generation = OPTO_TEST_GEN.fetch_add(1, Relaxed) + 1;
    OPTO_TEST_ON.store(true, Relaxed);
    fire(true);
    thread::spawn(move || {
        thread::sleep(OPTO_TEST);
        if OPTO_TEST_GEN.load(Relaxed) == generation && OPTO_TEST_ON.swap(false, Relaxed) {
            fire(false);
        }
    });
    Ok(())
}

fn stop_opto_test() {
    OPTO_TEST_GEN.fetch_add(1, Relaxed);
    if OPTO_TEST_ON.swap(false, Relaxed) {
        fire(false);
    }
}

#[cfg(feature = "wifi")]
static INDEX_HTML: &str = include_str!("index.html");

/// Commands must carry `X-Dimmer: 1`. Another web page open on the phone cannot add a
/// custom header to a cross-origin request without a CORS preflight, which this server
/// never answers, so it cannot switch the lamp.
#[cfg(feature = "wifi")]
fn from_page(req: &esp_idf_svc::http::server::Request<&mut esp_idf_svc::http::server::EspHttpConnection>) -> bool {
    req.header("X-Dimmer") == Some("1")
}

/// What the master reads after `RequestStatus`.
fn i2c_status() -> Status {
    let half = HALF_US.load(Relaxed);
    let mains = mains_present();
    let mut status_flags = 0;
    if mains {
        status_flags |= flags::MAINS;
    }
    if mains && locked() {
        status_flags |= flags::LOCKED;
    }
    if TIMED_OUT.load(Relaxed) {
        status_flags |= flags::TIMED_OUT;
    }
    Status {
        flags: status_flags,
        alpha_applied: applied_alpha(
            FRACTION.load(Relaxed),
            half,
            mains && locked(),
            MIN_DELAY_US,
            MIN_TAIL_US,
        ),
        freq_centi_hz: if mains && half > 0 { (50_000_000 / half).min(u16::MAX as u32) as u16 } else { 0 },
        bad_frames: BAD_FRAMES.load(Relaxed),
    }
}

fn count_bad_frame() {
    BAD_FRAMES.fetch_add(1, Relaxed);
}

/// Receives command frames. The lamp deadman is not here but in the main loop, so a stalled
/// driver cannot keep the lamp on.
fn i2c_task(mut driver: I2cSlaveDriver<'static>) {
    let timeout = TickType::new_millis(I2C_READ_TIMEOUT_MS).ticks();
    let mut frame = [0u8; COMMAND_LEN];
    let mut len = 0;
    loop {
        match driver.read(&mut frame[len..], timeout) {
            Ok(n) => len += n,
            Err(_) => {
                if len > 0 {
                    count_bad_frame();
                    len = 0;
                }
                continue;
            }
        }
        if len < COMMAND_LEN {
            continue;
        }
        len = 0;
        match decode_command(&frame) {
            Ok(Command::SetAlpha(alpha)) => {
                set_alpha(alpha);
                LAST_COMMAND_MS.store(now_ms(), Relaxed);
                ARMED.store(true, Relaxed);
                TIMED_OUT.store(false, Relaxed);
            }
            Ok(Command::RequestStatus) => {
                // The master reads at least 3 ms later; the frame waits in the TX buffer.
                let _ = driver.write(&encode_status(&i2c_status()), 0);
            }
            Err(_) => count_bad_frame(),
        }
    }
}

fn main() -> Result<()> {
    esp_idf_svc::sys::link_patches();
    // Log with `info!`, never `println!`: without a USB host the USB serial console
    // returns an error, and `println!` panics on it (a reset loop on a phone charger).
    esp_idf_svc::log::EspLogger::initialize_default();

    setup_gpio()?;
    // Three quick flashes mark a boot, so repeated resets (a weak supply) are easy to see.
    for _ in 0..3 {
        led(true);
        thread::sleep(Duration::from_millis(80));
        led(false);
        thread::sleep(Duration::from_millis(120));
    }
    set_level(0);

    let peripherals = Peripherals::take()?;

    // SDA is IO6 and SCL is IO7. The pull-ups are on the Pico board, so the internal ones stay off.
    let i2c = I2cSlaveDriver::new(
        peripherals.i2c0,
        peripherals.pins.gpio6,
        peripherals.pins.gpio7,
        I2C_ADDRESS,
        &I2cSlaveConfig::new()
            .sda_enable_pullup(false)
            .scl_enable_pullup(false)
            .rx_buffer_length(128)
            .tx_buffer_length(128),
    )?;
    thread::Builder::new().stack_size(4096).spawn(move || i2c_task(i2c))?;
    info!("I2C slave at 0x{I2C_ADDRESS:02X} on IO6 (SDA) and IO7 (SCL)");

    #[cfg(feature = "wifi")]
    let _wifi = {
    let sys_loop = EspSystemEventLoop::take()?;
    // No NVS: nothing is written to flash at run time, so the ZC interrupt is never
    // paused by a flash write.
    let mut wifi = BlockingWifi::wrap(EspWifi::new(peripherals.modem, sys_loop.clone(), None)?, sys_loop)?;
    wifi.set_configuration(&Configuration::AccessPoint(AccessPointConfiguration {
        ssid: AP_SSID.try_into().unwrap(),
        password: AP_PASS.try_into().unwrap(),
        auth_method: AuthMethod::WPA2Personal,
        channel: 6,
        max_connections: 4,
        ..Default::default()
    }))?;
    wifi.start()?;
    // Many ESP32-C3 SuperMini boards have a poorly matched antenna and transmit garbage
    // at full power; 8.5 dBm (units of 0.25 dBm) is reliable and plenty for a lab bench.
    esp!(unsafe { sys::esp_wifi_set_max_tx_power(34) })?;
    wifi.wait_netif_up()?;
    let ip = wifi.wifi().ap_netif().get_ip_info()?.ip;
    info!("Access point `{AP_SSID}`: open http://{ip}");

    let mut server = EspHttpServer::new(&HttpConfig {
        stack_size: 8192,
        ..Default::default()
    })?;
    server.fn_handler("/", Method::Get, |req| {
        req.into_response(200, None, &[("Content-Type", "text/html; charset=utf-8")])?
            .write_all(INDEX_HTML.as_bytes())
    })?;
    server.fn_handler("/status", Method::Get, |req| {
        req.into_response(200, None, &[("Content-Type", "application/json"), ("Cache-Control", "no-store")])?
            .write_all(status_json().as_bytes())
    })?;
    // POST /level?p=0..100
    server.fn_handler("/level", Method::Post, |req| {
        if !from_page(&req) {
            return req.into_status_response(403)?.write_all(b"missing X-Dimmer header");
        }
        // One controller at a time: after the first I2C command the Pico owns the lamp.
        if ARMED.load(Relaxed) {
            return req.into_status_response(409)?.write_all(b"I2C control active");
        }
        let query = req.uri().split_once('?').map_or("", |(_, q)| q);
        let level = query.split('&').find_map(|kv| kv.strip_prefix("p=")).and_then(|v| v.parse::<u32>().ok());
        match level {
            Some(p) if p <= 100 => {
                set_level(p);
                req.into_ok_response()?.write_all(b"ok")
            }
            _ => req.into_status_response(400)?.write_all(b"expected p=0..100"),
        }
    })?;
    server.fn_handler("/opto-test", Method::Post, |req| {
        if !from_page(&req) {
            return req.into_status_response(403)?.write_all(b"missing X-Dimmer header");
        }
        match start_opto_test() {
            Ok(()) => req.into_ok_response()?.write_all(b"ok"),
            Err(e) => req.into_status_response(409)?.write_all(e.to_string().as_bytes()),
        }
    })?;
    server.fn_handler("/opto-stop", Method::Post, |req| {
        stop_opto_test();
        req.into_ok_response()?.write_all(b"ok")
    })?;
    (wifi, server)
    };

    // Watchdog: losing the zero-cross signal stops firing within ZC_TIMEOUT_US.
    let mut last_print = 0u32;
    let mut last_window = 0u32;
    let mut counts = [0u32; 5];
    loop {
        let now = now_us();
        // Judged on real pulses: noise edges alone must not keep the lock alive.
        if locked() && now.wrapping_sub(LAST_PULSE_US.load(Relaxed)) > ZC_TIMEOUT_US {
            unlock();
            info!("zero-cross lost: firing stopped");
        }
        // Deadman: here and not in the I2C task, so a stalled I2C driver cannot keep the lamp on.
        // Off sets FRACTION_OFF and drives FIRE low, which also releases full on.
        if command_timed_out(ARMED.load(Relaxed), LAST_COMMAND_MS.load(Relaxed), now_ms(), COMMAND_TIMEOUT_MS)
            && !TIMED_OUT.swap(true, Relaxed)
        {
            set_fraction(0, FRACTION_OFF);
            info!("no I2C command for {COMMAND_TIMEOUT_MS} ms: lamp off");
        }
        if now.wrapping_sub(last_window) >= 1_000_000 {
            last_window = now;
            let total = [
                EDGES.load(Relaxed),
                PULSES.load(Relaxed),
                NOISE.load(Relaxed),
                INVALID.load(Relaxed),
                MISSED.load(Relaxed),
            ];
            let d: Vec<u32> = total.iter().zip(counts).map(|(t, c)| t.wrapping_sub(c)).collect();
            counts = total;
            let ext = |w: &(AtomicU32, AtomicU32)| {
                let (lo, hi) = (w.0.swap(u32::MAX, Relaxed), w.1.swap(0, Relaxed));
                if hi == 0 { (0, 0) } else { (lo, hi) }
            };
            let (w, h) = (ext(&WIN_WIDTH), ext(&WIN_HALF));
            *ZC_STATS.lock().unwrap() = format!(
                "\"zc\":{{\"edges\":{},\"pulses\":{},\"noise\":{},\"invalid\":{},\"missed\":{},\"width_min\":{},\"width_max\":{},\"half_min\":{},\"half_max\":{}}}",
                d[0], d[1], d[2], d[3], d[4], w.0, w.1, h.0, h.1
            );
        }
        // Heartbeat once the access point is up: a short flash every second.
        led(now % 1_000_000 < 50_000);
        if now.wrapping_sub(last_print) > 2_000_000 {
            last_print = now;
            info!("{}", status_json());
        }
        thread::sleep(Duration::from_millis(10));
    }
}
