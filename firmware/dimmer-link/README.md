# dimmer-link

The I2C wire format and the lamp rules shared by the Pico firmware
(master) and the ESP32-C3 dimmer firmware (slave).
It is `no_std` with no dependencies, so the tests run on the PC.

- `lib.rs`: frames, CRC, flags and the exposure constants.
- `exposure.rs`: the exposure limiter (leaky bucket and trip latch).
- `master.rs`, `slave.rs`: the Pico and dimmer decisions.
- Test: `cargo test` in this directory.
