use super::device::UacAltProfile;

/// Config payload that the native USB transport (V2) consumes when opening a
/// device. Fields originate from USB descriptor enumeration (see
/// [`super::device::enumerate_usb_audio_devices`]) plus the operator-selected
/// clock mode.
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
