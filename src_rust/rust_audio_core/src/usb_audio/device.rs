//! USB Audio Class device enumeration.
//!
//! Iterates all USB devices via rusb, finds those advertising
//! `bInterfaceClass=0x01 / bInterfaceSubClass=0x02` (Audio Streaming),
//! and parses their descriptor tree into [`UsbAudioDevice`] structs.
//!
//! No interfaces are claimed here — descriptor reading only.

use std::time::Duration;

use rusb::{Context, Device, DeviceHandle, Direction, TransferType, UsbContext};

use super::control::{query_sample_rates_uac2, set_sample_rate_uac1, set_sample_rate_uac2};
use super::descriptor::{
    detect_uac_version, parse_clock_id_from_ac, parse_stream_alt, EpInfo, UacStreamAlt,
    UacVersion, USB_CLASS_AUDIO, USB_SUBCLASS_AUDIO_CONTROL, USB_SUBCLASS_AUDIO_STREAMING,
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
    /// UAC 2.0 Clock Source entity ID (from OUTPUT_TERMINAL.bCSourceID).
    /// `None` for UAC 1.0 (sample rate is set via endpoint control transfer).
    pub clock_id: Option<u8>,
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

    let mut ac_extra_bytes: Vec<u8> = Vec::new();

    'ac_search: for iface in config.interfaces() {
        for iface_desc in iface.descriptors() {
            if iface_desc.class_code() == USB_CLASS_AUDIO
                && iface_desc.sub_class_code() == USB_SUBCLASS_AUDIO_CONTROL
            {
                ctrl_iface = iface_desc.interface_number();
                let extra = iface_desc.extra();
                if let Some(ver) = detect_uac_version(extra) {
                    uac_version = Some(ver);
                    ac_extra_bytes = extra.to_vec();
                    break 'ac_search;
                }
            }
        }
    }

    let uac_version = uac_version?;
    let clock_id = if uac_version == UacVersion::V2 {
        parse_clock_id_from_ac(&ac_extra_bytes)
    } else {
        None
    };

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
        clock_id,
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

// ---------------------------------------------------------------------------
// OpenUsbDevice — an opened, claimed, configured USB audio device
// ---------------------------------------------------------------------------

/// An opened USB Audio device, ready to stream.
///
/// Holds the `DeviceHandle` and remembers which alt-setting / sample rate
/// are currently active.  Constructed via [`OpenUsbDevice::open`] and
/// configured via [`OpenUsbDevice::configure`].
///
/// Drop releases the interface and restores the kernel driver.
pub struct OpenUsbDevice {
    pub handle: DeviceHandle<Context>,
    pub dev: UsbAudioDevice,
    /// Currently active alt-setting (set by `configure`).
    pub active_alt: Option<UacStreamAlt>,
    /// Currently configured sample rate.
    pub active_rate: u32,
}

impl OpenUsbDevice {
    /// Open the USB device by matching `vid:pid` (and optionally serial).
    ///
    /// Iterates the bus to find the matching device, then opens a handle.
    /// Does **not** claim any interface yet — call [`configure`] for that.
    pub fn open(dev: &UsbAudioDevice) -> Result<Self, String> {
        let ctx = Context::new().map_err(|e| format!("libusb context: {}", e))?;
        let devices = ctx.devices().map_err(|e| format!("list devices: {}", e))?;

        for d in devices.iter() {
            let dd = match d.device_descriptor() {
                Ok(dd) => dd,
                Err(_) => continue,
            };
            if dd.vendor_id() != dev.vendor_id || dd.product_id() != dev.product_id {
                continue;
            }
            // If we have a serial, verify it matches
            if dev.serial.is_some() {
                let handle = match d.open() {
                    Ok(h) => h,
                    Err(_) => continue,
                };
                let timeout = Duration::from_millis(200);
                let serial_match = handle
                    .read_languages(timeout)
                    .ok()
                    .and_then(|langs| langs.into_iter().next())
                    .and_then(|lang| {
                        dd.serial_number_string_index()
                            .and_then(|i| handle.read_string_descriptor(lang, i, timeout).ok())
                    });
                if serial_match.as_deref() != dev.serial.as_deref() {
                    continue;
                }
                return Ok(OpenUsbDevice {
                    handle,
                    dev: dev.clone(),
                    active_alt: None,
                    active_rate: 0,
                });
            }

            let handle = d.open().map_err(|e| {
                format!(
                    "open {:04x}:{:04x}: {} (try: udev rule or --device=all)",
                    dev.vendor_id, dev.product_id, e
                )
            })?;
            return Ok(OpenUsbDevice {
                handle,
                dev: dev.clone(),
                active_alt: None,
                active_rate: 0,
            });
        }

        Err(format!(
            "device {:04x}:{:04x} not found on bus",
            dev.vendor_id, dev.product_id
        ))
    }

    /// Claim the streaming interface, select `alt`, set `rate`.
    ///
    /// For UAC 2.0, queries supported sample rates from the Clock Source if
    /// `alt.sample_rates` is empty, then fills them in.
    ///
    /// Steps:
    /// 1. Auto-detach kernel driver on claim
    /// 2. `claim_interface(stream_iface)`
    /// 3. `set_alternate_setting(stream_iface, alt.alt_setting)`
    /// 4. Control transfer to set sample rate
    pub fn configure(&mut self, alt: &UacStreamAlt, rate: u32) -> Result<(), String> {
        let si = self.dev.stream_iface;

        // Auto-detach any kernel driver (e.g. snd-usb-audio) when claiming
        let _ = self.handle.set_auto_detach_kernel_driver(true);

        self.handle
            .claim_interface(si)
            .map_err(|e| format!("claim interface {}: {}", si, e))?;

        self.handle
            .set_alternate_setting(si, alt.alt_setting)
            .map_err(|e| format!("set alt-setting {}: {}", alt.alt_setting, e))?;

        // Set sample rate
        match self.dev.uac_version {
            UacVersion::V1 => {
                set_sample_rate_uac1(&self.handle, alt.out_ep, rate)?;
            }
            UacVersion::V2 => {
                let clock_id = self.dev.clock_id.ok_or_else(|| {
                    "UAC 2.0 device has no clock_id — descriptor parse failed".to_string()
                })?;
                set_sample_rate_uac2(&self.handle, self.dev.ctrl_iface, clock_id, rate)?;
            }
        }

        self.active_alt = Some(alt.clone());
        self.active_rate = rate;
        Ok(())
    }

    /// Query UAC 2.0 sample rates from the Clock Source entity.
    ///
    /// Returns an empty Vec for UAC 1.0 (rates come from the descriptor).
    pub fn query_uac2_rates(&self) -> Vec<u32> {
        if self.dev.uac_version != UacVersion::V2 {
            return Vec::new();
        }
        match self.dev.clock_id {
            Some(clock_id) => {
                query_sample_rates_uac2(&self.handle, self.dev.ctrl_iface, clock_id)
            }
            None => Vec::new(),
        }
    }

    /// Select the best alt-setting for the requested `rate` and `bit_depth`.
    ///
    /// Prefers exact bit-depth match; falls back to the highest available
    /// bit depth if none matches exactly.
    pub fn best_alt(&self, rate: u32, bit_depth: u8) -> Option<&UacStreamAlt> {
        // For UAC 1.0: only consider alts that advertise the rate
        // For UAC 2.0: all alts are candidates (rate set via clock source)
        let candidates: Vec<&UacStreamAlt> = self
            .dev
            .alts
            .iter()
            .filter(|a| {
                if self.dev.uac_version == UacVersion::V1 {
                    a.sample_rates.contains(&rate)
                } else {
                    true
                }
            })
            .collect();

        // Exact bit-depth match first
        if let Some(a) = candidates.iter().find(|a| a.bit_depth == bit_depth) {
            return Some(a);
        }
        // Highest bit-depth fallback
        candidates.into_iter().max_by_key(|a| a.bit_depth)
    }
}
