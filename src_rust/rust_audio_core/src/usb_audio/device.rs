//! USB Audio Class device enumeration.
//!
//! Iterates all USB devices via rusb, finds those advertising
//! `bInterfaceClass=0x01 / bInterfaceSubClass=0x02` (Audio Streaming),
//! and parses their descriptor tree into [`UsbAudioDevice`] structs.
//!
//! No interfaces are claimed here — descriptor reading only.

use std::time::Duration;

use rusb::{
    Context, Device, DeviceHandle, Direction, Speed, SyncType, TransferType, UsageType, UsbContext,
};

use super::control::{
    get_cur_sample_rate_uac2, query_sample_rates_uac2, set_sample_rate_uac1, set_sample_rate_uac2,
};
use super::control::{
    get_volume_cur, get_volume_range_uac1, get_volume_range_uac2, set_volume_cur,
};
use super::descriptor::{
    detect_uac_version, parse_clock_id_from_ac, parse_feature_unit_from_ac, parse_stream_alt,
    EpInfo, FeatureUnitInfo, UacStreamAlt, UacVersion, USB_CLASS_AUDIO, USB_SUBCLASS_AUDIO_CONTROL,
    USB_SUBCLASS_AUDIO_STREAMING,
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
    /// Feature Unit with volume control (if present in the Audio Control descriptors).
    pub feature_unit: Option<FeatureUnitInfo>,
}

/// Stable stream-profile fields used to keep appsink caps and lazy-open
/// alt-selection aligned across rate changes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UacAltProfile {
    pub format: super::descriptor::UacFormat,
    pub bit_depth: u8,
    pub subframe_size: u8,
    pub channels: u8,
}

impl From<&UacStreamAlt> for UacAltProfile {
    fn from(alt: &UacStreamAlt) -> Self {
        Self {
            format: alt.format,
            bit_depth: alt.bit_depth,
            subframe_size: alt.subframe_size,
            channels: alt.channels,
        }
    }
}

impl UacAltProfile {
    fn matches(&self, alt: &UacStreamAlt) -> bool {
        self.format == alt.format
            && self.bit_depth == alt.bit_depth
            && self.subframe_size == alt.subframe_size
            && self.channels == alt.channels
    }
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

    fn alt_selection_score(
        alt: &UacStreamAlt,
        bit_depth: u8,
    ) -> (u8, u8, u8, u8, u8, u8, u8, u16) {
        let format_rank = match alt.format {
            super::descriptor::UacFormat::Pcm => 3,
            super::descriptor::UacFormat::Float32 => 2,
            super::descriptor::UacFormat::Pcm8 => 1,
            super::descriptor::UacFormat::Unknown => 0,
        };
        let stereo_rank = (alt.channels == 2) as u8;
        let mono_rank = (alt.channels == 1) as u8;
        let fewer_channels_rank = u8::MAX - alt.channels;
        let compact_subframe_rank = u8::MAX - alt.subframe_size;
        (
            (alt.bit_depth == bit_depth) as u8,
            alt.bit_depth,
            stereo_rank,
            mono_rank,
            format_rank,
            fewer_channels_rank,
            compact_subframe_rank,
            alt.max_packet,
        )
    }

    fn best_alt_internal(
        &self,
        rate: Option<u32>,
        bit_depth: u8,
        profile: Option<UacAltProfile>,
    ) -> Option<&UacStreamAlt> {
        let candidates: Vec<&UacStreamAlt> = self
            .alts
            .iter()
            .filter(|alt| {
                if self.uac_version == UacVersion::V1 {
                    rate.map_or(true, |r| alt.sample_rates.contains(&r))
                } else {
                    true
                }
            })
            .filter(|alt| profile.map_or(true, |p| p.matches(alt)))
            .collect();

        if candidates.is_empty() {
            return None;
        }

        if profile.is_some() {
            return candidates.into_iter().max_by_key(|alt| alt.max_packet);
        }

        candidates
            .into_iter()
            .max_by_key(|alt| Self::alt_selection_score(alt, bit_depth))
    }

    pub fn best_alt_profile(&self, bit_depth: u8) -> Option<UacAltProfile> {
        self.best_alt_internal(None, bit_depth, None)
            .map(UacAltProfile::from)
    }

    pub fn best_alt_for_profile(
        &self,
        rate: u32,
        bit_depth: u8,
        profile: Option<UacAltProfile>,
    ) -> Option<&UacStreamAlt> {
        if let Some(profile) = profile {
            if let Some(alt) = self.best_alt_internal(Some(rate), bit_depth, Some(profile)) {
                return Some(alt);
            }
        }
        self.best_alt_internal(Some(rate), bit_depth, None)
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
    let feature_unit = parse_feature_unit_from_ac(&ac_extra_bytes, uac_version);

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
                    sync_type: if ep.transfer_type() == TransferType::Isochronous {
                        ep.sync_type()
                    } else {
                        SyncType::NoSync
                    },
                    usage_type: if ep.transfer_type() == TransferType::Isochronous {
                        ep.usage_type()
                    } else {
                        UsageType::Data
                    },
                    synch_address: ep.synch_address(),
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

    let is_high_speed = matches!(
        device.speed(),
        Speed::High | Speed::Super | Speed::SuperPlus
    );

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
        feature_unit,
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
    let fallback_name = format!("{:04x}:{:04x}", dev_desc.vendor_id(), dev_desc.product_id());

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
/// On drop, the streaming interface is explicitly reset to alt-setting 0
/// (zero-bandwidth) before the interfaces are released.  This is required
/// for `snd-usb-audio` to re-attach cleanly: if the interface is left in a
/// non-zero alt-setting with an active isochronous endpoint, some devices
/// refuse the kernel driver probe and never re-appear in ALSA.
pub struct OpenUsbDevice {
    pub handle: DeviceHandle<Context>,
    pub dev: UsbAudioDevice,
    /// Currently active alt-setting (set by `configure`).
    pub active_alt: Option<UacStreamAlt>,
    /// Currently configured sample rate.
    pub active_rate: u32,
    /// When true, `drop()` skips `release_interface` and `set_alternate_setting(0)`.
    /// This keeps the kernel driver detached so the system cannot reclaim the
    /// device (and lock it to 48 kHz) between track switches.
    pub skip_release_on_drop: bool,
}

impl Drop for OpenUsbDevice {
    fn drop(&mut self) {
        let si = self.dev.stream_iface;
        let ci = self.dev.ctrl_iface;

        if self.skip_release_on_drop {
            eprintln!(
                "usb-audio: OpenUsbDevice drop — skip_release_on_drop=true, \
                 keeping interfaces claimed (si={} ci={})",
                si, ci
            );
            return;
        }

        // Reset the streaming interface to alt-setting 0 (zero-bandwidth)
        // BEFORE releasing it.  snd-usb-audio expects alt 0 when it probes the
        // device on re-attach; leaving an active ISO alt causes its probe to fail
        // on many DACs, preventing the ALSA device from appearing.
        let _ = self.handle.set_alternate_setting(si, 0);

        // Explicitly release interfaces before the handle closes.
        // With set_auto_detach_kernel_driver(true) already set in configure(),
        // release_interface() automatically calls attach_kernel_driver() inside
        // libusb's Linux backend — no explicit attach_kernel_driver() call needed
        // (calling it again after release would double-attach and trigger repeated
        // snd-usb-audio probe/remove udev events).
        let _ = self.handle.release_interface(si);
        if ci != si {
            let _ = self.handle.release_interface(ci);
        }

        eprintln!(
            "usb-audio: OpenUsbDevice drop — alt reset to 0, interfaces released (si={} ci={})",
            si, ci
        );
    }
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
                    skip_release_on_drop: false,
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
                skip_release_on_drop: false,
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

        // Claim the Audio Control interface first so class-specific control
        // transfers (sample-rate / hardware volume) have the kernel detached.
        if ci != si {
            let _ = self.handle.claim_interface(ci);
        }

        // claim_interface may return BUSY if already claimed (e.g. reconfigure
        // after track switch without releasing).  That is fine — proceed.
        if let Err(e) = self.handle.claim_interface(si) {
            if e == rusb::Error::Busy {
                eprintln!("usb-audio: interface {} already claimed — continuing", si);
            } else {
                return Err(format!("claim interface {}: {}", si, e));
            }
        }

        self.handle
            .set_alternate_setting(si, alt.alt_setting)
            .map_err(|e| format!("set alt-setting {}: {}", alt.alt_setting, e))?;

        // Set sample rate
        match self.dev.uac_version {
            UacVersion::V1 => {
                eprintln!(
                    "usb-audio: UAC1 SET_CUR rate={} ep=0x{:02x}",
                    rate, alt.out_ep
                );
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

                        // PLL clock-domain switch can take 50–200 ms on some DACs
                        // (e.g. NXP/Freescale-class USB audio when PipeWire last
                        // used the device at 48 kHz and we are requesting 44.1 kHz
                        // or vice-versa).  Try once more with a longer settle window
                        // before reading GET_CUR / falling through to the probe path.
                        eprintln!(
                            "usb-audio: UAC2 long-delay retry for rate={} (PLL settle)",
                            chosen_rate
                        );
                        std::thread::sleep(std::time::Duration::from_millis(150));
                        if set_sample_rate_uac2(&self.handle, ci, clock_id, chosen_rate).is_ok() {
                            let verified = get_cur_sample_rate_uac2(&self.handle, ci, clock_id)
                                .filter(|&r| r >= 8_000 && r <= 768_000)
                                .unwrap_or(chosen_rate);
                            eprintln!(
                                "usb-audio: UAC2 long-delay retry OK → verified={}",
                                verified
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
                        const PROBE: &[u32] = &[44_100, 48_000, 88_200, 96_000, 176_400, 192_000];
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
                        eprintln!(
                            "usb-audio: UAC2 clock control failed, trying UAC1 endpoint fallback"
                        );
                        for &r in PROBE {
                            eprintln!(
                                "usb-audio: UAC1-fallback probing rate={} ep=0x{:02x}",
                                r, alt.out_ep
                            );
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
            Some(clock_id) => query_sample_rates_uac2(&self.handle, self.dev.ctrl_iface, clock_id),
            None => Vec::new(),
        }
    }

    /// Query hardware volume range from the Feature Unit.
    ///
    /// Returns `(min_raw, max_raw, res_raw)` in 1/256 dB units, or `None` if the
    /// device has no Feature Unit with volume control.
    ///
    /// For per-channel devices (no master volume), queries the first writable
    /// playback-path channel.
    pub fn get_hw_volume_range(&self) -> Option<(i16, i16, i16)> {
        let fu = self.dev.feature_unit.as_ref().filter(|f| f.has_volume)?;
        let &ch = fu.channels.first()?;
        match self.dev.uac_version {
            UacVersion::V1 => {
                get_volume_range_uac1(&self.handle, self.dev.ctrl_iface, fu.unit_id, ch)
            }
            UacVersion::V2 => {
                get_volume_range_uac2(&self.handle, self.dev.ctrl_iface, fu.unit_id, ch)
            }
        }
    }

    /// Read the current hardware volume (1/256 dB).
    pub fn get_hw_volume(&self) -> Option<i16> {
        let fu = self.dev.feature_unit.as_ref().filter(|f| f.has_volume)?;
        let &ch = fu.channels.first()?;
        get_volume_cur(&self.handle, self.dev.ctrl_iface, fu.unit_id, ch)
    }

    /// Set the hardware volume (1/256 dB).
    ///
    /// For master-channel devices: sets channel 0.
    /// For per-channel devices: sets all channels with volume support to the same value.
    pub fn set_hw_volume(&self, value_raw: i16) -> Result<(), String> {
        let fu = self
            .dev
            .feature_unit
            .as_ref()
            .filter(|f| f.has_volume)
            .ok_or_else(|| "device has no volume Feature Unit".to_string())?;
        if fu.channels.is_empty() {
            return Err("device has no writable volume channels".to_string());
        }
        for &ch in &fu.channels {
            set_volume_cur(&self.handle, self.dev.ctrl_iface, fu.unit_id, ch, value_raw)?;
        }
        Ok(())
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
        self.dev.best_alt_for_profile(rate, bit_depth, None)
    }

    pub fn best_alt_for_profile(
        &self,
        rate: u32,
        bit_depth: u8,
        profile: Option<UacAltProfile>,
    ) -> Option<&UacStreamAlt> {
        self.dev.best_alt_for_profile(rate, bit_depth, profile)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::usb_audio::UacFormat;

    fn alt(
        alt_setting: u8,
        format: UacFormat,
        bit_depth: u8,
        subframe_size: u8,
        channels: u8,
        max_packet: u16,
        sample_rates: &[u32],
    ) -> UacStreamAlt {
        UacStreamAlt {
            alt_setting,
            format,
            bit_depth,
            subframe_size,
            channels,
            sample_rates: sample_rates.to_vec(),
            out_ep: 0x01,
            feedback_ep: None,
            max_packet,
            out_ep_interval: 1,
        }
    }

    fn mock_device(uac_version: UacVersion, alts: Vec<UacStreamAlt>) -> UsbAudioDevice {
        UsbAudioDevice {
            vendor_id: 0x1234,
            product_id: 0x5678,
            name: "Mock".into(),
            serial: None,
            bus: 1,
            address: 1,
            ctrl_iface: 0,
            stream_iface: 1,
            uac_version,
            clock_id: Some(1),
            alts,
            is_high_speed: true,
            feature_unit: None,
        }
    }

    #[test]
    fn best_alt_profile_prefers_stereo_profile_over_multichannel_bandwidth() {
        let dev = mock_device(
            UacVersion::V2,
            vec![
                alt(1, UacFormat::Pcm, 24, 3, 6, 1152, &[]),
                alt(2, UacFormat::Pcm, 24, 3, 2, 576, &[]),
            ],
        );

        let profile = dev.best_alt_profile(24).expect("profile");

        assert_eq!(
            profile,
            UacAltProfile {
                format: UacFormat::Pcm,
                bit_depth: 24,
                subframe_size: 3,
                channels: 2,
            }
        );
    }

    #[test]
    fn best_alt_for_profile_reuses_selected_profile_and_picks_largest_packet() {
        let dev = mock_device(
            UacVersion::V2,
            vec![
                alt(1, UacFormat::Pcm, 24, 3, 2, 576, &[]),
                alt(2, UacFormat::Pcm, 24, 3, 2, 1152, &[]),
                alt(3, UacFormat::Pcm, 24, 3, 6, 2048, &[]),
            ],
        );
        let profile = dev.best_alt_profile(24).expect("profile");

        let chosen = dev
            .best_alt_for_profile(192_000, 24, Some(profile))
            .expect("alt");

        assert_eq!(chosen.channels, 2);
        assert_eq!(chosen.max_packet, 1152);
    }

    #[test]
    fn best_alt_for_profile_falls_back_when_profile_missing_for_requested_rate() {
        let dev = mock_device(
            UacVersion::V1,
            vec![
                alt(1, UacFormat::Pcm, 24, 3, 2, 288, &[44_100]),
                alt(2, UacFormat::Pcm, 32, 4, 2, 384, &[96_000]),
            ],
        );
        let profile = dev.best_alt_profile(24).expect("profile");

        let chosen = dev
            .best_alt_for_profile(96_000, 24, Some(profile))
            .expect("fallback alt");

        assert_eq!(chosen.bit_depth, 32);
        assert_eq!(chosen.sample_rates, vec![96_000]);
    }
}
