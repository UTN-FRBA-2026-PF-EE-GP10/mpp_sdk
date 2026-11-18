//! I2C master for the halogen lamp dimmer. See docs/hardware_v1/dimmer_link.md.
//!
//! The board wires I2C_SDA to GPIO5 and I2C_SCL to GPIO6. Neither RP2040 I2C
//! block can drive that pair, so the bus is bit-banged. The pins are open
//! drain: the output latch stays low, and the pin either drives low or is
//! released to the 4.7 kohm pull-ups. Every wait is a timer await, so the
//! other tasks keep running.

use dimmer_link::master::{alpha_to_send, spi_status_fields};
use dimmer_link::{
    ALPHA_OFF, APPLIED_NONE, COMMAND_LEN, Command, I2C_ADDRESS, KEEPALIVE_MS, STATUS_DELAY_MS,
    STATUS_LEN, decode_status, encode_command,
};
use embassy_rp::gpio::Flex;
use embassy_time::{Duration, Instant, Timer};
use portable_atomic::{AtomicBool, AtomicU8, AtomicU16, AtomicU32, AtomicU64, Ordering};

/// Alpha set by the Pi. Starts off.
static ALPHA_SET: AtomicU16 = AtomicU16::new(ALPHA_OFF);
/// Time (ms since boot) of the last valid `0xD1`, valid only when `HOST_SEEN`.
static HOST_MS: AtomicU32 = AtomicU32::new(0);
static HOST_SEEN: AtomicBool = AtomicBool::new(false);
/// The SPI link to the Pi is down.
static LINK_LOST: AtomicBool = AtomicBool::new(false);

/// Last good status from the dimmer.
static STATUS_FLAGS: AtomicU8 = AtomicU8::new(0);
static STATUS_BUDGET_S: AtomicU8 = AtomicU8::new(0);
static STATUS_APPLIED: AtomicU16 = AtomicU16::new(APPLIED_NONE);
static STATUS_MS: AtomicU64 = AtomicU64::new(0);
static STATUS_SEEN: AtomicBool = AtomicBool::new(false);

const STATUS_PERIOD: Duration = Duration::from_millis(500);
const LOOP_PERIOD: Duration = Duration::from_millis(10);
/// The I2C link counts as ok when a status read worked within this time.
const LINK_OK_MS: u32 = 1_000;
/// Half of one SCL period: about 100 kHz at best, slower with timer overhead.
const HALF_BIT_US: u64 = 5;
/// Longest a slave may hold SCL low.
const STRETCH_TIMEOUT: Duration = Duration::from_millis(2);
const STRETCH_POLL_US: u64 = 10;

fn now_ms() -> u32 {
    Instant::now().as_millis() as u32
}

/// `0xD1`: the Pi sets alpha. A value above `ALPHA_OFF` is ignored.
pub fn host_set_alpha(alpha: u16) {
    if alpha <= ALPHA_OFF {
        ALPHA_SET.store(alpha, Ordering::Relaxed);
        HOST_MS.store(now_ms(), Ordering::Relaxed);
        HOST_SEEN.store(true, Ordering::Relaxed);
    }
}

/// Called by the SPI task: the Pi link is lost, or a valid frame came back.
pub fn set_link_lost(lost: bool) {
    LINK_LOST.store(lost, Ordering::Relaxed);
    if lost {
        // The flag is a level and the task polls it, so a short gap could be
        // missed. Drop the request too: the Pi must send `0xD1` again.
        HOST_SEEN.store(false, Ordering::Relaxed);
        ALPHA_SET.store(ALPHA_OFF, Ordering::Relaxed);
    }
}

/// Fields of the `0xD2` reply.
#[derive(Clone, Copy)]
pub struct StatusReply {
    pub flags: u8,
    pub set: u16,
    pub applied: u16,
    pub age: u8,
    /// Seconds of lamp-on time left, or the cool-down wait when tripped. 0 when unknown.
    pub budget_s: u8,
}

pub fn status_reply() -> StatusReply {
    let age_ms = if STATUS_SEEN.load(Ordering::Relaxed) {
        Instant::now()
            .as_millis()
            .saturating_sub(STATUS_MS.load(Ordering::Relaxed))
    } else {
        u64::MAX
    };
    let (flags, budget_s) = spi_status_fields(
        STATUS_FLAGS.load(Ordering::Relaxed),
        STATUS_BUDGET_S.load(Ordering::Relaxed),
        age_ms < LINK_OK_MS as u64,
    );
    StatusReply {
        flags,
        set: ALPHA_SET.load(Ordering::Relaxed),
        applied: STATUS_APPLIED.load(Ordering::Relaxed),
        age: (age_ms / 100).min(255) as u8,
        budget_s,
    }
}

#[derive(Clone, Copy, defmt::Format)]
enum Fault {
    Nack,
    /// A slave held SCL low too long.
    Stretch,
    /// SDA stayed low when the bus should be free.
    Busy,
}

struct Bus<'d> {
    sda: Flex<'d>,
    scl: Flex<'d>,
}

impl<'d> Bus<'d> {
    fn new(mut sda: Flex<'d>, mut scl: Flex<'d>) -> Self {
        sda.set_low();
        scl.set_low();
        Self { sda, scl }
    }

    async fn half_bit() {
        Timer::after_micros(HALF_BIT_US).await;
    }

    fn sda_low(&mut self) {
        self.sda.set_as_output();
    }

    fn sda_release(&mut self) {
        self.sda.set_as_input();
    }

    fn scl_low(&mut self) {
        self.scl.set_as_output();
    }

    /// Releases SCL and waits for it to rise: a slave may stretch the clock.
    async fn scl_release(&mut self) -> Result<(), Fault> {
        self.scl.set_as_input();
        let start = Instant::now();
        while self.scl.is_low() {
            if start.elapsed() >= STRETCH_TIMEOUT {
                return Err(Fault::Stretch);
            }
            Timer::after_micros(STRETCH_POLL_US).await;
        }
        Ok(())
    }

    async fn start(&mut self) -> Result<(), Fault> {
        self.sda_release();
        self.scl_release().await?;
        Self::half_bit().await;
        if self.sda.is_low() {
            return Err(Fault::Busy);
        }
        self.sda_low();
        Self::half_bit().await;
        self.scl_low();
        Ok(())
    }

    async fn stop(&mut self) -> Result<(), Fault> {
        self.sda_low();
        Self::half_bit().await;
        self.scl_release().await?;
        Self::half_bit().await;
        self.sda_release();
        Self::half_bit().await;
        Ok(())
    }

    async fn write_bit(&mut self, bit: bool) -> Result<(), Fault> {
        if bit {
            self.sda_release();
        } else {
            self.sda_low();
        }
        Self::half_bit().await;
        self.scl_release().await?;
        Self::half_bit().await;
        self.scl_low();
        Ok(())
    }

    async fn read_bit(&mut self) -> Result<bool, Fault> {
        self.sda_release();
        Self::half_bit().await;
        self.scl_release().await?;
        Self::half_bit().await;
        let bit = self.sda.is_high();
        self.scl_low();
        Ok(bit)
    }

    async fn write_byte(&mut self, byte: u8) -> Result<(), Fault> {
        for i in (0..8).rev() {
            self.write_bit(byte & (1 << i) != 0).await?;
        }
        // A slave pulls SDA low on the ACK bit.
        if self.read_bit().await? {
            return Err(Fault::Nack);
        }
        Ok(())
    }

    async fn read_byte(&mut self, ack: bool) -> Result<u8, Fault> {
        let mut byte = 0;
        for _ in 0..8 {
            byte = (byte << 1) | self.read_bit().await? as u8;
        }
        self.write_bit(!ack).await?;
        Ok(byte)
    }

    async fn write(&mut self, bytes: &[u8]) -> Result<(), Fault> {
        self.start().await?;
        self.write_byte(I2C_ADDRESS << 1).await?;
        for &b in bytes {
            self.write_byte(b).await?;
        }
        self.stop().await
    }

    async fn read(&mut self, out: &mut [u8]) -> Result<(), Fault> {
        self.start().await?;
        self.write_byte((I2C_ADDRESS << 1) | 1).await?;
        let last = out.len() - 1;
        for (i, slot) in out.iter_mut().enumerate() {
            *slot = self.read_byte(i != last).await?;
        }
        self.stop().await
    }

    /// Frees a bus that is stuck: release both lines, clock out up to 9
    /// pulses until the slave releases SDA, then send a STOP.
    async fn recover(&mut self) {
        self.sda_release();
        self.scl.set_as_input();
        Self::half_bit().await;
        for _ in 0..9 {
            if self.sda.is_high() {
                break;
            }
            self.scl_low();
            Self::half_bit().await;
            self.scl.set_as_input();
            Self::half_bit().await;
        }
        self.sda_low();
        Self::half_bit().await;
        self.scl.set_as_input();
        Self::half_bit().await;
        self.sda_release();
    }

    async fn transact_write(&mut self, bytes: &[u8]) -> Result<(), Fault> {
        let result = self.write(bytes).await;
        if result.is_err() {
            self.recover().await;
        }
        result
    }

    async fn transact_read(&mut self, out: &mut [u8]) -> Result<(), Fault> {
        let result = self.read(out).await;
        if result.is_err() {
            self.recover().await;
        }
        result
    }
}

async fn send(bus: &mut Bus<'_>, command: Command) -> bool {
    let frame: [u8; COMMAND_LEN] = encode_command(command);
    bus.transact_write(&frame).await.is_ok()
}

async fn read_status(bus: &mut Bus<'_>) -> bool {
    if !send(bus, Command::RequestStatus).await {
        return false;
    }
    Timer::after_millis(STATUS_DELAY_MS as u64).await;
    let mut frame = [0u8; STATUS_LEN];
    if bus.transact_read(&mut frame).await.is_err() {
        return false;
    }
    match decode_status(&frame) {
        Ok(status) => {
            STATUS_FLAGS.store(status.flags, Ordering::Relaxed);
            STATUS_BUDGET_S.store(status.budget_s, Ordering::Relaxed);
            STATUS_APPLIED.store(status.alpha_applied, Ordering::Relaxed);
            STATUS_MS.store(Instant::now().as_millis(), Ordering::Relaxed);
            STATUS_SEEN.store(true, Ordering::Relaxed);
            true
        }
        Err(_) => false,
    }
}

#[embassy_executor::task]
pub async fn dimmer_task(sda: Flex<'static>, scl: Flex<'static>) {
    let mut bus = Bus::new(sda, scl);
    let mut last_sent: Option<u16> = None;
    let mut last_send_at = Instant::now();
    let mut last_status_at = Instant::now();
    let mut bus_ok = true;

    loop {
        let requested = ALPHA_SET.load(Ordering::Relaxed);
        let host_age = HOST_SEEN
            .load(Ordering::Relaxed)
            .then(|| now_ms().wrapping_sub(HOST_MS.load(Ordering::Relaxed)));
        let alpha = alpha_to_send(requested, host_age, LINK_LOST.load(Ordering::Relaxed));
        if alpha == ALPHA_OFF && requested != ALPHA_OFF {
            // Drop the stale request, so it cannot come back after the
            // host age counter wraps.
            ALPHA_SET.store(ALPHA_OFF, Ordering::Relaxed);
            HOST_SEEN.store(false, Ordering::Relaxed);
        }

        let due = last_send_at.elapsed() >= Duration::from_millis(KEEPALIVE_MS as u64);
        // A failed send is retried at the keepalive rhythm, so a missing
        // dimmer is not polled in a tight loop.
        if last_sent != Some(alpha) || due {
            let ok = send(&mut bus, Command::SetAlpha(alpha)).await;
            last_sent = Some(alpha);
            last_send_at = Instant::now();
            if ok != bus_ok {
                bus_ok = ok;
                if ok {
                    defmt::info!("dimmer: I2C link recovered");
                } else {
                    defmt::warn!("dimmer: I2C write failed");
                }
            }
        }

        if last_status_at.elapsed() >= STATUS_PERIOD {
            let _ = read_status(&mut bus).await;
            last_status_at = Instant::now();
        }

        Timer::after(LOOP_PERIOD).await;
    }
}
