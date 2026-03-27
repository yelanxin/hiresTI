//! UAC 1.0 / 2.0 Audio Class descriptor parsing.
//!
//! Operates on raw `extra()` byte slices from rusb — no USB control
//! transfers are required for UAC 1.0 (sample rates are in the descriptor).
//! For UAC 2.0, sample rates live in the Clock Source entity and must be
//! queried at open time; [`UacStreamAlt::sample_rates`] is left empty here.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use rusb::{SyncType, UsageType};

// ---------------------------------------------------------------------------
// USB Audio Class constants
// ---------------------------------------------------------------------------

pub const USB_CLASS_AUDIO: u8 = 0x01;
pub const USB_SUBCLASS_AUDIO_CONTROL: u8 = 0x01;
pub const USB_SUBCLASS_AUDIO_STREAMING: u8 = 0x02;

/// bDescriptorType for class-specific interface/endpoint descriptors.
const CS_INTERFACE: u8 = 0x24;

/// AC interface descriptor subtypes.
const AC_HEADER: u8 = 0x01;
const AC_INPUT_TERMINAL: u8 = 0x02;
const AC_OUTPUT_TERMINAL: u8 = 0x03;
const AC_MIXER_UNIT: u8 = 0x04;
const AC_SELECTOR_UNIT: u8 = 0x05;
const AC_FEATURE_UNIT: u8 = 0x06;
const AC_PROCESSING_UNIT: u8 = 0x07;
const AC_EXTENSION_UNIT: u8 = 0x08;
const AC_CLOCK_SELECTOR: u8 = 0x0B;
const USB_STREAMING_TERMINAL_TYPE: u16 = 0x0101;
const FU_VOLUME_CONTROL: u8 = 0x02;

/// AS interface descriptor subtypes.
const AS_GENERAL: u8 = 0x01;
const AS_FORMAT_TYPE: u8 = 0x02;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// UAC protocol version detected from the Audio Control header descriptor.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UacVersion {
    V1,
    V2,
}

/// PCM format tag / format bitmap.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UacFormat {
    Pcm,
    Pcm8,
    Float32,
    Unknown,
}

/// One active alt-setting on a USB Audio Streaming interface.
///
/// Alt-setting 0 (zero-bandwidth) is excluded; only alt-settings that carry
/// audio data and expose a valid ISO OUT endpoint are included.
#[derive(Debug, Clone)]
pub struct UacStreamAlt {
    /// USB alternate setting number (≥ 1).
    pub alt_setting: u8,
    /// PCM format declared by the device.
    pub format: UacFormat,
    /// Bit resolution (16 / 24 / 32).  Matches `bBitResolution` in the
    /// Format Type I descriptor.
    pub bit_depth: u8,
    /// Container size in bytes per sample per channel.  Matches `bSubFrameSize`
    /// (UAC 1.0) or `bSubSlotSize` (UAC 2.0).
    ///
    /// Critical for 24-bit devices: `subframe_size=3` → packed S24_3LE;
    /// `subframe_size=4` → S24LE (24-bit value in a 32-bit container).
    /// Falls back to `(bit_depth + 7) / 8` when the descriptor omits it.
    pub subframe_size: u8,
    /// Number of audio channels.
    pub channels: u8,
    /// Supported sample rates in Hz.
    /// Populated for UAC 1.0 (from the Format Type descriptor).
    /// Empty for UAC 2.0 (must be queried via Clock Source control transfer).
    pub sample_rates: Vec<u32>,
    /// ISO OUT endpoint address (direction bit already set).
    pub out_ep: u8,
    /// UAC 2.0 feedback (async) IN endpoint address, if present.
    pub feedback_ep: Option<u8>,
    /// `wMaxPacketSize` of the ISO OUT endpoint.
    pub max_packet: u16,
    /// `bInterval` of the ISO OUT endpoint (verbatim from the descriptor).
    /// Interpret together with the bus speed to get the actual packet period.
    pub out_ep_interval: u8,
}

// ---------------------------------------------------------------------------
// Internal: iterate class-specific sub-descriptors inside an `extra()` blob
// ---------------------------------------------------------------------------

pub(crate) struct CsDescIter<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> CsDescIter<'a> {
    pub(crate) fn new(buf: &'a [u8]) -> Self {
        Self { buf, pos: 0 }
    }
}

impl<'a> Iterator for CsDescIter<'a> {
    type Item = &'a [u8];

    fn next(&mut self) -> Option<&'a [u8]> {
        loop {
            let buf = self.buf.get(self.pos..)?;
            if buf.len() < 2 {
                return None;
            }
            let len = buf[0] as usize;
            if len < 2 || len > buf.len() {
                return None;
            }
            self.pos += len;
            return Some(&buf[..len]);
        }
    }
}

// ---------------------------------------------------------------------------
// UAC version detection from the Audio Control interface extra bytes
// ---------------------------------------------------------------------------

/// Returns the UAC version if `ac_extra` contains a valid AC Header descriptor.
///
/// Looks for `[bLength, 0x24, 0x01, bcdADC_lo, bcdADC_hi, ...]` and decodes
/// the BCD version field:
/// - `0x0100` → UAC 1.0
/// - `0x0200` → UAC 2.0
pub fn detect_uac_version(ac_extra: &[u8]) -> Option<UacVersion> {
    for desc in CsDescIter::new(ac_extra) {
        // Need at least: bLength, bDescriptorType, bDescriptorSubtype, bcdADC (2B)
        if desc.len() < 5 {
            continue;
        }
        if desc[1] != CS_INTERFACE || desc[2] != AC_HEADER {
            continue;
        }
        let bcd = u16::from_le_bytes([desc[3], desc[4]]);
        return Some(if bcd >= 0x0200 {
            UacVersion::V2
        } else {
            UacVersion::V1
        });
    }
    None
}

// ---------------------------------------------------------------------------
// Audio Streaming alt-setting parsing
// ---------------------------------------------------------------------------

/// Endpoint metadata extracted from a rusb `EndpointDescriptor`.
pub struct EpInfo {
    pub address: u8,
    pub is_out: bool,
    pub is_iso: bool,
    pub max_packet: u16,
    /// `bInterval` from the endpoint descriptor.
    /// For HS ISO: interval = 2^(bInterval-1) × 125 µs.
    /// For FS ISO: interval = bInterval × 1 ms.
    pub b_interval: u8,
    /// Isochronous synchronisation mode.
    pub sync_type: SyncType,
    /// Isochronous usage type.
    pub usage_type: UsageType,
    /// Audio-only: explicit synch endpoint address advertised by this endpoint.
    pub synch_address: u8,
}

/// Parse one AS interface alt-setting into a [`UacStreamAlt`].
///
/// Returns `None` if the alt-setting does not describe a usable audio stream
/// (wrong format type, missing OUT endpoint, zero bit-depth, etc.).
pub fn parse_stream_alt(
    alt_setting: u8,
    as_extra: &[u8],
    endpoints: &[EpInfo],
    uac_version: UacVersion,
) -> Option<UacStreamAlt> {
    let mut format = UacFormat::Unknown;
    let mut channels: u8 = 2;
    let mut bit_depth: u8 = 0;
    let mut subframe_size: u8 = 0;
    let mut sample_rates: Vec<u32> = Vec::new();
    let mut found_general = false;
    let mut found_format = false;

    for desc in CsDescIter::new(as_extra) {
        if desc.len() < 3 || desc[1] != CS_INTERFACE {
            continue;
        }
        let subtype = desc[2];

        if subtype == AS_GENERAL {
            match uac_version {
                UacVersion::V1 => {
                    // [len, 0x24, 0x01, bTermLink, bDelay, wFormatTag(2B)]
                    if desc.len() < 7 {
                        continue;
                    }
                    let fmt_tag = u16::from_le_bytes([desc[5], desc[6]]);
                    format = match fmt_tag {
                        0x0001 => UacFormat::Pcm,
                        0x0002 => UacFormat::Pcm8,
                        0x0003 => UacFormat::Float32,
                        _ => UacFormat::Unknown,
                    };
                    found_general = true;
                }
                UacVersion::V2 => {
                    // [len, 0x24, 0x01, bTermLink, bmControls, bFormatType,
                    //  bmFormats(4B), bNrChannels, bmChannelConfig(4B), iChannelNames]
                    if desc.len() < 11 {
                        continue;
                    }
                    let bm_formats = u32::from_le_bytes([desc[6], desc[7], desc[8], desc[9]]);
                    format = if bm_formats & 0x01 != 0 {
                        UacFormat::Pcm
                    } else if bm_formats & 0x04 != 0 {
                        UacFormat::Float32
                    } else if bm_formats & 0x02 != 0 {
                        UacFormat::Pcm8
                    } else {
                        UacFormat::Unknown
                    };
                    channels = desc[10];
                    found_general = true;
                }
            }
        } else if subtype == AS_FORMAT_TYPE {
            match uac_version {
                UacVersion::V1 => {
                    // [len, 0x24, 0x02, bFormatType, bNrChannels, bSubFrameSize,
                    //  bBitResolution, bSamFreqType, freqs...]
                    if desc.len() < 8 || desc[3] != 0x01 {
                        // Only FORMAT_TYPE_I (0x01) supported
                        continue;
                    }
                    channels = desc[4];
                    subframe_size = desc[5]; // bSubFrameSize — wire bytes per sample
                    bit_depth = desc[6]; // bBitResolution — used bits
                    let freq_type = desc[7];
                    if freq_type == 0 {
                        // Continuous: tLower(3B) tUpper(3B) — record both endpoints
                        if desc.len() >= 11 {
                            let lo = u32::from_le_bytes([desc[8], desc[9], desc[10], 0]);
                            if lo > 0 {
                                sample_rates.push(lo);
                            }
                        }
                        if desc.len() >= 14 {
                            let hi = u32::from_le_bytes([desc[11], desc[12], desc[13], 0]);
                            if hi > 0 && sample_rates.last() != Some(&hi) {
                                sample_rates.push(hi);
                            }
                        }
                    } else {
                        // Discrete: freq_type × 3-byte frequencies
                        let n = freq_type as usize;
                        for i in 0..n {
                            let off = 8 + i * 3;
                            if off + 3 > desc.len() {
                                break;
                            }
                            let hz =
                                u32::from_le_bytes([desc[off], desc[off + 1], desc[off + 2], 0]);
                            if hz > 0 {
                                sample_rates.push(hz);
                            }
                        }
                    }
                    found_format = true;
                }
                UacVersion::V2 => {
                    // [len, 0x24, 0x02, bFormatType, bSubSlotSize, bBitResolution]
                    if desc.len() < 6 || desc[3] != 0x01 {
                        continue;
                    }
                    subframe_size = desc[4]; // bSubSlotSize — wire bytes per sample
                    bit_depth = desc[5]; // bBitResolution — used bits
                                         // UAC 2.0 sample rates queried at open via Clock Source control transfer
                    found_format = true;
                }
            }
        }
    }

    // Validity check
    if !found_general || !found_format || bit_depth == 0 || format == UacFormat::Unknown {
        return None;
    }

    // Find ISO OUT endpoint (required) and optional feedback IN endpoint.
    // Prefer the OUT endpoint's bSynchAddress (explicit feedback binding).
    let mut out_ep: Option<&EpInfo> = None;
    let mut feedback_ep: Option<u8> = None;

    for ep in endpoints {
        if !ep.is_iso {
            continue;
        }
        if ep.is_out {
            out_ep = Some(ep);
        } else if ep.usage_type == UsageType::Feedback {
            feedback_ep = Some(ep.address);
        }
    }

    let out_ep = out_ep?;
    let out_ep_addr = out_ep.address;
    let max_packet = out_ep.max_packet;
    let out_ep_interval = out_ep.b_interval;
    if out_ep.synch_address != 0 {
        feedback_ep = endpoints
            .iter()
            .find(|ep| !ep.is_out && ep.is_iso && ep.address == out_ep.synch_address)
            .map(|ep| ep.address);
    }

    // Fallback: derive subframe_size from bit_depth when the descriptor did not
    // provide it (should not happen for a well-formed device).
    let subframe_size = if subframe_size > 0 {
        subframe_size
    } else {
        (bit_depth + 7) / 8
    };

    Some(UacStreamAlt {
        alt_setting,
        format,
        bit_depth,
        subframe_size,
        channels,
        sample_rates,
        out_ep: out_ep_addr,
        feedback_ep,
        max_packet,
        out_ep_interval,
    })
}

// ---------------------------------------------------------------------------
// Feature Unit (volume / mute) extraction
// ---------------------------------------------------------------------------

/// Information about a playback-path Feature Unit that supports writable volume.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FeatureUnitInfo {
    /// Feature Unit descriptor `bUnitID`.
    pub unit_id: u8,
    /// `true` if volume control is available (master or per-channel).
    pub has_volume: bool,
    /// `true` if mute control is available (master or per-channel).
    pub has_mute: bool,
    /// `true` if volume is on the master channel (channel 0).
    /// When `false`, volume is per-channel only (channel 1, 2, …).
    pub volume_is_master: bool,
    /// Number of per-channel entries that have volume control.
    /// Used to know how many SET_CUR calls are needed for per-channel mode.
    pub volume_channels: u8,
    /// Writable volume channels. `vec![0]` means master; otherwise per-channel IDs.
    pub channels: Vec<u8>,
}

/// Extract the playback-path Feature Unit with writable Volume Control from the
/// Audio Control interface descriptors.
pub fn parse_feature_unit_from_ac(
    ac_extra: &[u8],
    uac_version: UacVersion,
) -> Option<FeatureUnitInfo> {
    let mut playback_roots = Vec::new();
    let mut entity_sources = BTreeMap::<u8, Vec<u8>>::new();
    let mut feature_units = BTreeMap::<u8, FeatureUnitInfo>::new();

    for desc in CsDescIter::new(ac_extra) {
        if desc.len() < 3 || desc[1] != CS_INTERFACE {
            continue;
        }

        if let Some((entity_id, sources)) = parse_entity_sources(desc) {
            entity_sources.insert(entity_id, sources);
        }

        if desc[2] == AC_OUTPUT_TERMINAL {
            if let Some((terminal_type, source_id)) = parse_output_terminal(desc) {
                if source_id != 0 && terminal_type != USB_STREAMING_TERMINAL_TYPE {
                    playback_roots.push(source_id);
                }
            }
        }

        if desc[2] == AC_FEATURE_UNIT {
            if let Some(unit) = parse_feature_unit_desc(desc, uac_version) {
                feature_units.insert(unit.unit_id, unit);
            }
        }
    }

    if playback_roots.is_empty() {
        return None;
    }

    let mut queue = VecDeque::from(playback_roots);
    let mut visited = BTreeSet::new();

    while let Some(entity_id) = queue.pop_front() {
        if entity_id == 0 || !visited.insert(entity_id) {
            continue;
        }

        if let Some(unit) = feature_units.get(&entity_id) {
            return Some(unit.clone());
        }

        if let Some(sources) = entity_sources.get(&entity_id) {
            for &source_id in sources {
                if source_id != 0 {
                    queue.push_back(source_id);
                }
            }
        }
    }

    None
}

fn parse_output_terminal(desc: &[u8]) -> Option<(u16, u8)> {
    if desc.len() < 8 || desc[2] != AC_OUTPUT_TERMINAL {
        return None;
    }
    let terminal_type = u16::from_le_bytes([desc[4], desc[5]]);
    let source_id = desc[7];
    Some((terminal_type, source_id))
}

fn parse_entity_sources(desc: &[u8]) -> Option<(u8, Vec<u8>)> {
    match desc[2] {
        AC_OUTPUT_TERMINAL => {
            let (_, source_id) = parse_output_terminal(desc)?;
            Some((desc[3], vec![source_id]))
        }
        AC_MIXER_UNIT | AC_SELECTOR_UNIT => {
            if desc.len() < 6 {
                return None;
            }
            let entity_id = desc[3];
            let n_pins = desc[4] as usize;
            let start = 5usize;
            let end = start + n_pins;
            let sources = desc.get(start..end)?.to_vec();
            Some((entity_id, sources))
        }
        AC_FEATURE_UNIT => {
            if desc.len() < 5 {
                return None;
            }
            Some((desc[3], vec![desc[4]]))
        }
        AC_PROCESSING_UNIT | AC_EXTENSION_UNIT => {
            if desc.len() < 8 {
                return None;
            }
            let entity_id = desc[3];
            let n_pins = desc[6] as usize;
            let start = 7usize;
            let end = start + n_pins;
            let sources = desc.get(start..end)?.to_vec();
            Some((entity_id, sources))
        }
        AC_INPUT_TERMINAL | AC_CLOCK_SELECTOR | AC_HEADER => None,
        _ => None,
    }
}

fn parse_feature_unit_desc(desc: &[u8], uac_version: UacVersion) -> Option<FeatureUnitInfo> {
    let unit_id = *desc.get(3)?;
    let (channels, has_mute) = match uac_version {
        UacVersion::V1 => parse_uac1_feature_unit_channels(desc),
        UacVersion::V2 => parse_uac2_feature_unit_channels(desc),
    };
    if channels.is_empty() {
        return None;
    }
    let volume_is_master = channels == [0];
    Some(FeatureUnitInfo {
        unit_id,
        has_volume: true,
        has_mute,
        volume_is_master,
        volume_channels: if volume_is_master {
            0
        } else {
            channels.len() as u8
        },
        channels,
    })
}

fn parse_uac1_feature_unit_channels(desc: &[u8]) -> (Vec<u8>, bool) {
    if desc.len() < 8 {
        return (Vec::new(), false);
    }
    let control_size = desc[5] as usize;
    if control_size == 0 {
        return (Vec::new(), false);
    }
    let payload = match desc.get(6..desc.len().saturating_sub(1)) {
        Some(payload) if !payload.is_empty() => payload,
        _ => return (Vec::new(), false),
    };
    let control_count = payload.len() / control_size;
    if control_count == 0 {
        return (Vec::new(), false);
    }

    let mut master_has_volume = false;
    let mut any_mute = false;
    let mut per_channel = Vec::new();
    for index in 0..control_count {
        let off = index * control_size;
        let control = decode_bitmap(payload.get(off..off + control_size).unwrap_or_default());
        if control & 0x01 != 0 {
            any_mute = true;
        }
        if control & (1 << (FU_VOLUME_CONTROL - 1)) == 0 {
            continue;
        }
        if index == 0 {
            master_has_volume = true;
        } else {
            per_channel.push(index as u8);
        }
    }

    if master_has_volume {
        (vec![0], any_mute)
    } else {
        (per_channel, any_mute)
    }
}

fn parse_uac2_feature_unit_channels(desc: &[u8]) -> (Vec<u8>, bool) {
    if desc.len() < 10 {
        return (Vec::new(), false);
    }
    let payload = match desc.get(5..desc.len().saturating_sub(1)) {
        Some(payload) if !payload.is_empty() => payload,
        _ => return (Vec::new(), false),
    };
    let control_count = payload.len() / 4;
    if control_count == 0 {
        return (Vec::new(), false);
    }

    let mut master_has_volume = false;
    let mut any_mute = false;
    let mut per_channel = Vec::new();
    for index in 0..control_count {
        let off = index * 4;
        let Some(raw) = payload.get(off..off + 4) else {
            break;
        };
        let bitmap = u32::from_le_bytes(raw.try_into().unwrap());
        if (bitmap & 0x03) >= 1 {
            any_mute = true;
        }
        if !uac2_control_writable(bitmap, FU_VOLUME_CONTROL) {
            continue;
        }
        if index == 0 {
            master_has_volume = true;
        } else {
            per_channel.push(index as u8);
        }
    }

    if master_has_volume {
        (vec![0], any_mute)
    } else {
        (per_channel, any_mute)
    }
}

fn decode_bitmap(bytes: &[u8]) -> u32 {
    bytes
        .iter()
        .take(4)
        .enumerate()
        .fold(0u32, |acc, (index, byte)| {
            acc | ((*byte as u32) << (index * 8))
        })
}

fn uac2_control_writable(bitmap: u32, selector: u8) -> bool {
    let shift = (selector.saturating_sub(1) as u32) * 2;
    ((bitmap >> shift) & 0b11) == 0b11
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_uac1_master_volume_on_playback_path() {
        let ac = [
            0x09, 0x24, 0x02, 0x01, 0x01, 0x01, 0x00, 0x02, 0x00, 0x0A, 0x24, 0x06, 0x05, 0x01,
            0x01, 0x03, 0x03, 0x00, 0x00, 0x09, 0x24, 0x03, 0x06, 0x01, 0x03, 0x00, 0x05, 0x00,
        ];

        assert_eq!(
            parse_feature_unit_from_ac(&ac, UacVersion::V1),
            Some(FeatureUnitInfo {
                unit_id: 0x05,
                has_volume: true,
                has_mute: true,
                volume_is_master: true,
                volume_channels: 0,
                channels: vec![0],
            })
        );
    }

    #[test]
    fn prefers_playback_path_feature_unit_over_unrelated_first_unit() {
        let ac = [
            0x09, 0x24, 0x02, 0x01, 0x01, 0x01, 0x00, 0x02, 0x00, 0x0A, 0x24, 0x06, 0x05, 0x01,
            0x01, 0x03, 0x03, 0x00, 0x00, 0x0A, 0x24, 0x06, 0x09, 0x02, 0x01, 0x03, 0x03, 0x00,
            0x00, 0x09, 0x24, 0x03, 0x0A, 0x01, 0x03, 0x00, 0x09, 0x00,
        ];

        assert_eq!(
            parse_feature_unit_from_ac(&ac, UacVersion::V1).map(|fu| fu.unit_id),
            Some(0x09)
        );
    }

    #[test]
    fn falls_back_to_per_channel_uac2_volume() {
        let ac = [
            0x09, 0x24, 0x02, 0x01, 0x01, 0x01, 0x00, 0x02, 0x00, 0x12, 0x24, 0x06, 0x09, 0x02,
            0x01, 0x00, 0x00, 0x00, 0x0C, 0x00, 0x00, 0x00, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x09,
            0x24, 0x03, 0x0A, 0x01, 0x03, 0x00, 0x09, 0x00,
        ];

        assert_eq!(
            parse_feature_unit_from_ac(&ac, UacVersion::V2),
            Some(FeatureUnitInfo {
                unit_id: 0x09,
                has_volume: true,
                has_mute: true,
                volume_is_master: false,
                volume_channels: 2,
                channels: vec![1, 2],
            })
        );
    }
}

// ---------------------------------------------------------------------------
// UAC 2.0 Clock Source ID extraction
// ---------------------------------------------------------------------------

/// Extract the Clock Source entity ID from the Audio Control interface descriptors.
///
/// UAC 2.0 OUTPUT_TERMINAL carries a `bCSourceID` field (byte 8) that may point
/// to either a Clock Source (subtype 0x0A) directly, or to a Clock Selector
/// (subtype 0x0B).  Control transfers for sample rate (SET_CUR / GET_RANGE) must
/// target a Clock **Source**, not a Selector — addressing a Selector is ignored
/// by most devices, causing SET_CUR to fail silently and the device to play at
/// an incorrect rate (wrong pitch / crackling).
///
/// This function resolves the chain:
///   OUTPUT_TERMINAL.bCSourceID
///     → if Clock Selector: follow baCSourceID[0] to reach the Clock Source
///     → if already a Clock Source: return as-is
///
/// Returns `None` if no OUTPUT_TERMINAL with a valid `bCSourceID` is found.
pub fn parse_clock_id_from_ac(ac_extra: &[u8]) -> Option<u8> {
    // Pass 1: find bCSourceID from the (first) OUTPUT_TERMINAL.
    let mut initial_id: Option<u8> = None;
    for desc in CsDescIter::new(ac_extra) {
        // UAC 2.0 OUTPUT_TERMINAL (12 bytes):
        // [0] bLength, [1] 0x24, [2] 0x03 (OUTPUT_TERMINAL),
        // [3] bTerminalID, [4..5] wTerminalType, [6] bAssocTerminal,
        // [7] bSourceID, [8] bCSourceID, [9..10] bmControls, [11] iTerminal
        if desc.len() < 9 || desc[1] != CS_INTERFACE || desc[2] != AC_OUTPUT_TERMINAL {
            continue;
        }
        let id = desc[8]; // bCSourceID
        if id != 0 {
            initial_id = Some(id);
            break;
        }
    }
    let initial_id = initial_id?;

    // Pass 2: if initial_id is a Clock Selector, follow it to the Clock Source.
    // UAC 2.0 Clock Selector descriptor:
    // [0] bLength, [1] 0x24, [2] 0x0B (CLOCK_SELECTOR),
    // [3] bClockID, [4] bNrInPins, [5..] baCSourceID[0..bNrInPins-1], ...
    for desc in CsDescIter::new(ac_extra) {
        if desc.len() < 6 || desc[1] != CS_INTERFACE || desc[2] != AC_CLOCK_SELECTOR {
            continue;
        }
        if desc[3] != initial_id {
            continue; // not the selector we're looking for
        }
        let n_pins = desc[4] as usize;
        if n_pins > 0 && desc.len() >= 6 {
            // Return the first (and normally only) input pin — the programmable
            // Clock Source that accepts SET_CUR frequency commands.
            return Some(desc[5]); // baCSourceID[0]
        }
    }

    // initial_id was not a Clock Selector — it is the Clock Source itself.
    Some(initial_id)
}
