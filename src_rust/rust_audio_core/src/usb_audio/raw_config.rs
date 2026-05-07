use super::descriptor::UacFormat;
use super::device::{enumerate_usb_audio_devices, UacAltProfile};
use super::dop;

/// Config payload that the native USB transport (V2) consumes when opening a
/// device. Fields originate from USB descriptor enumeration (see
/// [`enumerate_usb_audio_devices`]) plus the operator-selected clock mode.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UsbRawSinkConfig {
    pub device_id: String,
    pub bit_depth: u8,
    pub alt_profile: UacAltProfile,
    /// PCM format string ("S16LE" / "S24_3LE" / "S32LE" / "F32LE" /
    /// "F64LE"). Historically this was a GStreamer caps format name; it is
    /// retained as a string so existing callers and FFI shims do not change.
    pub gst_format: String,
    pub channels: usize,
    pub clock_mode: u8,
    /// Unique sorted list of bit depths advertised by the device's PCM/Float
    /// alt-settings. Native transport uses this to decide whether the source
    /// bit depth can be passed through verbatim (e.g. 16-bit FLAC → S16LE on
    /// the wire) or must be promoted to a depth the device actually supports
    /// (e.g. Topping Monitor 09 only exposes 32-bit alts → S16LE source must
    /// be promoted to S32LE before slab formatting).
    pub supported_bit_depths: Vec<u8>,
}

/// Outcome of [`build_usb_raw_sink_config`]: the populated config plus a
/// flag indicating whether the device's natural mode is DSD-over-PCM (for
/// 1.5 MHz / 3.0 MHz carriers on a S24_3LE pipe).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UsbRawSinkConfigBuild {
    pub config: UsbRawSinkConfig,
    pub is_dop: bool,
}

/// Resolve a USB audio device by id and pick the best alt-setting + format
/// string given the operator's preferred bit depth (`pref_depth = 0` means
/// "use the device's native depth"). Returns the populated `UsbRawSinkConfig`
/// alongside a `is_dop` flag for DSD-over-PCM detection.
///
/// This mirrors the historical `Engine::build_appsink_usb` enumeration step
/// but has no GStreamer dependency, so V2 native_transport callers can use
/// it without spinning up a GStreamer element.
pub fn build_usb_raw_sink_config(
    device_id: &str,
    pref_depth: u8,
    clock_mode: u8,
) -> Result<UsbRawSinkConfigBuild, String> {
    let dev = enumerate_usb_audio_devices()
        .into_iter()
        .find(|d| d.id() == device_id)
        .ok_or_else(|| format!("USB audio device '{}' not found", device_id))?;

    // Pick the best alt-setting for the requested bit depth.  Among alts
    // that match, prefer the one with the largest `max_packet` so the alt
    // chosen here matches what `best_alt()` selects in the lazy-open path.
    let alt_profile = dev
        .best_alt_profile(pref_depth)
        .ok_or_else(|| "USB device has no usable alt-settings".to_string())?;
    let alt = dev
        .alts
        .iter()
        .filter(|alt| {
            alt.format == alt_profile.format
                && alt.bit_depth == alt_profile.bit_depth
                && alt.subframe_size == alt_profile.subframe_size
                && alt.channels == alt_profile.channels
        })
        .max_by_key(|alt| alt.max_packet)
        .ok_or_else(|| "USB device has no usable alt-settings".to_string())?;

    // Detect DoP mode: device carries DSD-over-PCM at 176400/352800 Hz with
    // a S24_3LE carrier.  Use the highest advertised rate as a heuristic.
    let max_rate: u32 = alt.sample_rates.iter().copied().max().unwrap_or(0);
    let is_dop = dop::is_dsd_rate(max_rate.saturating_mul(16))
        || (alt.subframe_size == 3
            && alt.bit_depth == 24
            && matches!(max_rate, 176_400 | 352_800));

    let gst_format: &'static str = if is_dop {
        "DSDU8"
    } else {
        match (alt.format, alt.subframe_size, alt.bit_depth) {
            (UacFormat::Float32, _, _) => "F32LE",
            (_, 2, 16) | (_, _, 16) => "S16LE",
            (_, 3, 24) => "S24_3LE",
            (_, 4, 24) => "S24LE",
            (_, _, 32) => "S32LE",
            _ => "S32LE",
        }
    };

    let supported_bit_depths: Vec<u8> = {
        let mut depths: Vec<u8> = dev
            .alts
            .iter()
            .filter(|a| matches!(a.format, UacFormat::Pcm | UacFormat::Float32))
            .map(|a| a.bit_depth)
            .collect();
        depths.sort_unstable();
        depths.dedup();
        depths
    };

    Ok(UsbRawSinkConfigBuild {
        config: UsbRawSinkConfig {
            device_id: device_id.to_string(),
            bit_depth: alt.bit_depth,
            alt_profile,
            gst_format: gst_format.to_string(),
            channels: alt.channels as usize,
            clock_mode,
            supported_bit_depths,
        },
        is_dop,
    })
}
