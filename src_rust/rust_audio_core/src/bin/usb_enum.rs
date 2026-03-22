//! USB audio device enumerator — prints all detected UAC devices and their
//! supported alt-settings.  Run with:
//!
//!   cargo run --bin usb_enum

use rust_audio_core::usb_audio::enumerate_usb_audio_devices;

fn main() {
    let devices = enumerate_usb_audio_devices();

    if devices.is_empty() {
        println!("No USB Audio Class devices found.");
        println!("Check udev rules / group membership (plugdev/audio).");
        return;
    }

    println!("Found {} USB audio device(s):\n", devices.len());

    for dev in &devices {
        let serial = dev.serial.as_deref().unwrap_or("(no serial)");
        println!(
            "  {:04x}:{:04x}  {}  [{}]",
            dev.vendor_id, dev.product_id, dev.name, serial
        );
        println!(
            "  ID string : usb:{:04x}:{:04x}",
            dev.vendor_id, dev.product_id
        );
        println!("  UAC version: {:?}", dev.uac_version);
        println!("  Alt-settings ({}):", dev.alts.len());

        for alt in &dev.alts {
            let rates: Vec<String> = if alt.sample_rates.is_empty() {
                vec!["(query at open)".into()]
            } else {
                alt.sample_rates
                    .iter()
                    .map(|r: &u32| r.to_string())
                    .collect()
            };
            println!(
                "    alt={} {:?} {}ch {}bit (subframe={}B) max_pkt={} ep=0x{:02x} rates=[{}]{}",
                alt.alt_setting,
                alt.format,
                alt.channels,
                alt.bit_depth,
                alt.subframe_size,
                alt.max_packet,
                alt.out_ep,
                rates.join(", "),
                if alt.feedback_ep.is_some() {
                    " +feedback"
                } else {
                    ""
                },
            );
        }
        println!();
    }
}
