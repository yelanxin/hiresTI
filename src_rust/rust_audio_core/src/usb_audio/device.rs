//! USB Audio Class device enumeration.
//!
//! Iterates all USB devices via rusb, finds those advertising
//! `bInterfaceClass=0x01 / bInterfaceSubClass=0x02` (Audio Streaming),
//! and parses their descriptor tree into [`UsbAudioDevice`] structs.
//!
//! No interfaces are claimed here — descriptor reading only.

use std::time::Duration;

use rusb::{Device, Direction, TransferType, UsbContext};

use super::descriptor::{
    detect_uac_version, parse_stream_alt, EpInfo, UacStreamAlt, UacVersion,
    USB_CLASS_AUDIO, USB_SUBCLASS_AUDIO_CONTROL, USB_SUBCLASS_AUDIO_STREAMING,
};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// A USB Audio Class device that exposes at least one usable playback stream.
#[derive(Debug, Clone)]
pub struct UsbAudioDevice {
    pub vendor_id: u16,
    pub product_id: u16,
    /// Human-readable product name (from USB string descriptor, best-effort).
    pub name: String,
    /// Serial number string (best-effort; `None` if unavailable or no permission).
    pub serial: Option<String>,
    pub bus: u8,
    pub address: u8,
    /// Audio Control interface number.
    pub ctrl_iface: u8,
    /// Audio Streaming interface number (first OUT-capable one found).
    pub stream_iface: u8,
    pub uac_version: UacVersion,
    /// All usable alt-settings on `stream_iface` (alt 0 excluded).
    pub alts: Vec<UacStreamAlt>,
}

impl UsbAudioDevice {
    /// Stable device ID used as the `device_id` in `rac_set_output_tuned`.
    ///
    /// Format: `usb:VVVV:PPPP` or `usb:VVVV:PPPP:SERIAL`
    pub fn id(&self) -> String {
        match &self.serial {
            Some(s) if !s.is_empty() => {
                format!("usb:{:04x}:{:04x}:{}", self.vendor_id, self.product_id, s)
            }
            _ => format!("usb:{:04x}:{:04x}", self.vendor_id, self.product_id),
        }
    }
}

// ---------------------------------------------------------------------------
// Enumeration
// ---------------------------------------------------------------------------

/// Return all USB Audio Class devices visible to the current user.
///
/// Devices that require elevated permissions to open (for string descriptors)
/// are still included; the name falls back to `"VVVV:PPPP"`.
pub fn enumerate_usb_audio_devices() -> Vec<UsbAudioDevice> {
    let ctx = match rusb::Context::new() {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };
    let devices = match ctx.devices() {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };

    devices
        .iter()
        .filter_map(|d| try_parse_device(&d))
        .collect()
}

// ---------------------------------------------------------------------------
// Per-device parsing
// ---------------------------------------------------------------------------

fn try_parse_device<T: UsbContext>(device: &Device<T>) -> Option<UsbAudioDevice> {
    let dev_desc = device.device_descriptor().ok()?;
    let config = device.config_descriptor(0).ok()?;

    // ---- Step 1: find the Audio Control interface and its UAC version ----

    let mut uac_version: Option<UacVersion> = None;
    let mut ctrl_iface: u8 = 0;

    'ac_search: for iface in config.interfaces() {
        for iface_desc in iface.descriptors() {
            if iface_desc.class_code() == USB_CLASS_AUDIO
                && iface_desc.sub_class_code() == USB_SUBCLASS_AUDIO_CONTROL
            {
                ctrl_iface = iface_desc.interface_number();
                let extra = iface_desc.extra();
                if let Some(ver) = detect_uac_version(extra) {
                    uac_version = Some(ver);
                    break 'ac_search;
                }
            }
        }
    }

    let uac_version = uac_version?;

    // ---- Step 2: find Audio Streaming interfaces and parse alt-settings ----

    let mut stream_iface_num: Option<u8> = None;
    let mut best_alts: Vec<UacStreamAlt> = Vec::new();

    for iface in config.interfaces() {
        let mut iface_num: Option<u8> = None;
        let mut alts: Vec<UacStreamAlt> = Vec::new();

        for iface_desc in iface.descriptors() {
            if iface_desc.class_code() != USB_CLASS_AUDIO
                || iface_desc.sub_class_code() != USB_SUBCLASS_AUDIO_STREAMING
            {
                continue;
            }

            let this_num = iface_desc.interface_number();
            iface_num = Some(this_num);

            // Alt 0 is zero-bandwidth; skip but record the interface number
            if iface_desc.setting_number() == 0 {
                continue;
            }

            let as_extra = iface_desc.extra();
            let endpoints: Vec<EpInfo> = iface_desc
                .endpoint_descriptors()
                .map(|ep| EpInfo {
                    address: ep.address(),
                    is_out: ep.direction() == Direction::Out,
                    is_iso: ep.transfer_type() == TransferType::Isochronous,
                    max_packet: ep.max_packet_size(),
                })
                .collect();

            if let Some(alt) = parse_stream_alt(
                iface_desc.setting_number(),
                as_extra,
                &endpoints,
                uac_version,
            ) {
                alts.push(alt);
            }
        }

        // Take the first AS interface that has at least one usable alt-setting
        if !alts.is_empty() && stream_iface_num.is_none() {
            stream_iface_num = iface_num;
            best_alts = alts;
        }
    }

    let stream_iface = stream_iface_num?;
    if best_alts.is_empty() {
        return None;
    }

    // ---- Step 3: read string descriptors (best-effort) ----

    let (name, serial) = read_string_descs(device, &dev_desc);

    Some(UsbAudioDevice {
        vendor_id: dev_desc.vendor_id(),
        product_id: dev_desc.product_id(),
        name,
        serial,
        bus: device.bus_number(),
        address: device.address(),
        ctrl_iface,
        stream_iface,
        uac_version,
        alts: best_alts,
    })
}

/// Read product name and serial number from USB string descriptors.
///
/// Requires opening the device handle; falls back gracefully if the process
/// lacks permission (common without a udev rule).
fn read_string_descs<T: UsbContext>(
    device: &Device<T>,
    dev_desc: &rusb::DeviceDescriptor,
) -> (String, Option<String>) {
    let fallback_name =
        format!("{:04x}:{:04x}", dev_desc.vendor_id(), dev_desc.product_id());

    let handle = match device.open() {
        Ok(h) => h,
        Err(_) => return (fallback_name, None),
    };

    let timeout = Duration::from_millis(200);
    let lang = match handle.read_languages(timeout) {
        Ok(langs) if !langs.is_empty() => langs[0],
        _ => return (fallback_name, None),
    };

    let name = dev_desc
        .product_string_index()
        .and_then(|i| handle.read_string_descriptor(lang, i, timeout).ok())
        .filter(|s| !s.is_empty())
        .unwrap_or(fallback_name);

    let serial = dev_desc
        .serial_number_string_index()
        .and_then(|i| handle.read_string_descriptor(lang, i, timeout).ok())
        .filter(|s| !s.is_empty());

    (name, serial)
}
