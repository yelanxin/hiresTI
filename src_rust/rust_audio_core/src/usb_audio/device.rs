//! USB Audio Class device enumeration.
//!
//! Iterates all USB devices via rusb, finds those advertising
//! `bInterfaceClass=0x01 / bInterfaceSubClass=0x02` (Audio Streaming),
//! and parses their descriptor tree into [`UsbAudioDevice`] structs.
//!
//! No interfaces are claimed here — descriptor reading only.

use std::time::Duration;

use rusb::{Context, Device, DeviceHandle, Direction, Speed, TransferType, UsbContext};

use super::control::{
    get_cur_sample_rate_uac2, query_sample_rates_uac2, set_sample_rate_uac1, set_sample_rate_uac2,
};
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
    /// `true` when the device is connected at USB High-Speed (480 Mbit/s).
    /// Determines how to interpret `bInterval` on isochronous endpoints:
    /// HS → interval = 2^(bInterval-1) × 125 µs; FS → interval = bInterval ms.
    pub is_high_speed: bool,
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
                    b_interval: ep.interval(),
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

    let is_high_speed = matches!(device.speed(), Speed::High | Speed::Super | Speed::SuperPlus);

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
        is_high_speed,
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
/// Drop is handled entirely by rusb's `DeviceHandle::drop()`, which calls
/// `libusb_release_interface()` for every interface tracked in
/// `DeviceHandle::interfaces`.  With `set_auto_detach_kernel_driver(true)`,
/// the Linux backend's `op_release_interface()` automatically calls
/// `op_attach_kernel_driver()` for each released interface, re-attaching
/// `snd-usb-audio` and restoring ALSA visibility — no manual Drop needed.
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
        let ci = self.dev.ctrl_iface;

        // Auto-detach any kernel driver (e.g. snd-usb-audio) when claiming.
        let _ = self.handle.set_auto_detach_kernel_driver(true);

        // For UAC 2.0 the clock SET_CUR is addressed to the Audio Control
        // interface; claim it first so the kernel driver is detached from it.
        // rusb tracks claimed interfaces internally; its DeviceHandle::drop()
        // will release them all (with auto_detach → snd-usb-audio re-attaches).
        if self.dev.uac_version == UacVersion::V2 && ci != si {
            let _ = self.handle.claim_interface(ci);
        }

        self.handle
            .claim_interface(si)
            .map_err(|e| format!("claim interface {}: {}", si, e))?;

        self.handle
            .set_alternate_setting(si, alt.alt_setting)
            .map_err(|e| format!("set alt-setting {}: {}", alt.alt_setting, e))?;

        // Set sample rate
        match self.dev.uac_version {
            UacVersion::V1 => {
                eprintln!("usb-audio: UAC1 SET_CUR rate={} ep=0x{:02x}", rate, alt.out_ep);
                set_sample_rate_uac1(&self.handle, alt.out_ep, rate)?;
                eprintln!("usb-audio: UAC1 SET_CUR OK");
            }
            UacVersion::V2 => {
                let clock_id = self.dev.clock_id.ok_or_else(|| {
                    "UAC 2.0 device has no clock_id — descriptor parse failed".to_string()
                })?;

                // Query supported rates via GET_RANGE so we pick a rate the
                // device actually supports before issuing SET_CUR.
                let supported = query_sample_rates_uac2(&self.handle, ci, clock_id);
                eprintln!(
                    "usb-audio: UAC2 GET_RANGE clock_id={} supported={:?}",
                    clock_id, supported
                );

                // Choose the best rate: exact match first, then the highest
                // supported rate that does not exceed the requested rate.
                // Avoid jumping to a higher rate than requested — some devices
                // accept SET_CUR at any value but their DAC runs at a fixed
                // lower rate, causing fast playback.
                let chosen_rate = if supported.contains(&rate) {
                    rate
                } else if !supported.is_empty() {
                    supported
                        .iter()
                        .copied()
                        .filter(|&r| r <= rate)
                        .max()
                        .unwrap_or_else(|| *supported.iter().min().unwrap())
                } else {
                    // No GET_RANGE data — try the requested rate as-is.
                    rate
                };
                eprintln!(
                    "usb-audio: UAC2 SET_CUR rate={} (requested={}) clock_id={} ctrl_iface={}",
                    chosen_rate, rate, clock_id, ci
                );

                match set_sample_rate_uac2(&self.handle, ci, clock_id, chosen_rate) {
                    Ok(_) => {
                        // Verify via GET_CUR: some devices silently ignore
                        // SET_CUR and keep their hardware clock at a fixed rate.
                        let verified = get_cur_sample_rate_uac2(&self.handle, ci, clock_id)
                            .filter(|&r| r >= 8_000 && r <= 768_000)
                            .unwrap_or(chosen_rate);
                        eprintln!(
                            "usb-audio: UAC2 SET_CUR OK → chosen={} verified={}",
                            chosen_rate, verified
                        );
                        self.active_alt = Some(alt.clone());
                        self.active_rate = verified;
                        return Ok(());
                    }
                    Err(warn) => {
                        eprintln!("usb-audio: UAC2 SET_CUR failed ({})", warn);

                        // Some devices STALL the very first SET_CUR issued after
                        // the kernel driver (snd-usb-audio) has just been detached
                        // from the interface — the device's clock control path needs
                        // a brief settling period before it becomes responsive.
                        // Retry once after 20 ms; this is enough for the MUSILAND
                        // Monitor 09 (and similar UAC 2.0 devices) to start
                        // accepting frequency commands without falling through to
                        // the rate-probe path.
                        std::thread::sleep(std::time::Duration::from_millis(20));
                        if set_sample_rate_uac2(&self.handle, ci, clock_id, chosen_rate).is_ok() {
                            let verified = get_cur_sample_rate_uac2(&self.handle, ci, clock_id)
                                .filter(|&r| r >= 8_000 && r <= 768_000)
                                .unwrap_or(chosen_rate);
                            eprintln!(
                                "usb-audio: UAC2 SET_CUR retry OK → chosen={} verified={}",
                                chosen_rate, verified
                            );
                            self.active_alt = Some(alt.clone());
                            self.active_rate = verified;
                            return Ok(());
                        }

                        // GET_CUR — device may have a fixed clock.
                        let cur = get_cur_sample_rate_uac2(&self.handle, ci, clock_id);
                        eprintln!("usb-audio: UAC2 GET_CUR={:?}", cur);
                        if let Some(r) = cur.filter(|&r| r >= 8_000 && r <= 768_000) {
                            eprintln!("usb-audio: using fixed clock rate={} Hz", r);
                            self.active_alt = Some(alt.clone());
                            self.active_rate = r;
                            return Ok(());
                        }

                        // GET_RANGE was empty and GET_CUR failed — device may
                        // accept SET_CUR only at specific rates.  Probe common
                        // audio rates (STALL responses are immediate, ~0 ms).
                        const PROBE: &[u32] =
                            &[44_100, 48_000, 88_200, 96_000, 176_400, 192_000];
                        if supported.is_empty() {
                            for &r in PROBE {
                                if r == chosen_rate {
                                    continue;
                                }
                                eprintln!("usb-audio: UAC2 probing rate={}", r);
                                if set_sample_rate_uac2(&self.handle, ci, clock_id, r).is_ok() {
                                    eprintln!("usb-audio: UAC2 probe OK → rate={}", r);
                                    self.active_alt = Some(alt.clone());
                                    self.active_rate = r;
                                    return Ok(());
                                }
                            }
                        }

                        // All UAC 2.0 clock control attempts failed.  Some
                        // devices report UAC 2.0 descriptors but implement rate
                        // control via the UAC 1.0 mechanism (SET_CUR to the ISO
                        // OUT endpoint).  Try that as a last resort.
                        eprintln!("usb-audio: UAC2 clock control failed, trying UAC1 endpoint fallback");
                        for &r in PROBE {
                            eprintln!("usb-audio: UAC1-fallback probing rate={} ep=0x{:02x}", r, alt.out_ep);
                            if set_sample_rate_uac1(&self.handle, alt.out_ep, r).is_ok() {
                                eprintln!("usb-audio: UAC1-fallback OK → rate={}", r);
                                self.active_alt = Some(alt.clone());
                                self.active_rate = r;
                                return Ok(());
                            }
                        }

                        eprintln!(
                            "usb-audio: all rate-setting methods failed, proceeding at requested={}",
                            chosen_rate
                        );
                    }
                }
            }
        }

        eprintln!("usb-audio: configure done — active_rate={}", rate);
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
    ///
    /// For **UAC 2.0** devices the sample rate is set on the Clock Source entity
    /// (not per alt-setting), so all alts are candidates regardless of rate.
    /// Among alts with the same bit depth, the one with the **largest
    /// `max_packet`** is chosen.  Many UAC 2.0 devices expose multiple alts for
    /// different rate families — e.g. alt 1 (`max_packet` ≈ 576) for ≤96 kHz
    /// and alt 2 (`max_packet` ≈ 1158) for ≤192 kHz.  Picking the smaller alt
    /// at 192 kHz would cap each ISO packet at 576 bytes (48 samples instead of
    /// 192), causing `fill_transfer` to advance the clock at ¼ speed and making
    /// playback run 4× too slowly.
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

        if self.dev.uac_version == UacVersion::V2 {
            // For UAC 2.0 prefer the alt with the largest max_packet among
            // those that match the requested bit depth.  This ensures the ISO
            // OUT endpoint has enough bandwidth for high sample rates (e.g.
            // 192 kHz stereo 24-bit needs ≥1152 B/packet).
            if let Some(a) = candidates
                .iter()
                .filter(|a| a.bit_depth == bit_depth)
                .max_by_key(|a| a.max_packet)
            {
                return Some(*a);
            }
            // Bit-depth fallback: highest bit depth, then largest max_packet.
            return candidates
                .into_iter()
                .max_by_key(|a| (a.bit_depth, a.max_packet));
        }

        // UAC 1.0: exact bit-depth match first (any max_packet — already
        // rate-filtered so it is sized correctly for the requested rate).
        if let Some(a) = candidates.iter().find(|a| a.bit_depth == bit_depth) {
            return Some(a);
        }
        // Highest bit-depth fallback
        candidates.into_iter().max_by_key(|a| a.bit_depth)
    }
}
