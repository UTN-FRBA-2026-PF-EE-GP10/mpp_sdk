#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_rp::gpio::{Level, Output};
use embassy_time::Timer;
use {defmt_rtt as _, panic_probe as _};

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_rp::init(Default::default());
    let mut led = Output::new(p.PIN_25, Level::Low);

    defmt::info!("mpp-firmware booted");

    loop {
        led.set_high();
        Timer::after_millis(10).await;
        defmt::info!("LED on");
        led.set_low();
        Timer::after_millis(500).await;
        defmt::info!("LED off");
    }
}
