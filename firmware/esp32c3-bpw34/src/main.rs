use anyhow::Result;
use esp_idf_svc::hal::adc::oneshot::{AdcChannelDriver, AdcDriver};
use esp_idf_svc::hal::adc::{attenuation, Resolution};
use esp_idf_svc::hal::adc::oneshot::config::AdcChannelConfig;
use esp_idf_svc::hal::peripherals::Peripherals;
use esp_idf_svc::sys;

use std::thread;
use std::time::Duration;

fn main() -> Result<()> {
    esp_idf_svc::sys::link_patches();

    let peripherals = Peripherals::take().unwrap();

    let adc = AdcDriver::new(peripherals.adc1)?;

    let mut pin = AdcChannelDriver::new(
        &adc,
        peripherals.pins.gpio2,
        &AdcChannelConfig {
            attenuation: attenuation::DB_12,
            resolution: Resolution::Resolution12Bit,
            ..Default::default()
        },
    )?;

    unsafe {
        let mut cali_handle: sys::adc_cali_handle_t = std::ptr::null_mut();

        let config = sys::adc_cali_curve_fitting_config_t {
            unit_id: sys::adc_unit_t_ADC_UNIT_1,
            chan: sys::adc_channel_t_ADC_CHANNEL_2,
            atten: sys::adc_atten_t_ADC_ATTEN_DB_12,
            bitwidth: sys::adc_bitwidth_t_ADC_BITWIDTH_12,
        };

        sys::adc_cali_create_scheme_curve_fitting(
            &config,
            &mut cali_handle,
        );

        loop {
            let raw = adc.read_raw(&mut pin)?;

            let mut voltage_mv = 0;

            sys::adc_cali_raw_to_voltage(
                cali_handle,
                raw as i32,
                &mut voltage_mv,
            );

            println!(
                "raw={} voltage={}mV",
                raw,
                voltage_mv
            );

            thread::sleep(Duration::from_millis(500));
        }
    }
}
