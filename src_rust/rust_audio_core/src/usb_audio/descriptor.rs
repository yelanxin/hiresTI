//! UAC 1.0 / 2.0 Audio Class descriptor parsing.
//!
//! Operates on raw `extra()` byte slices from rusb — no USB control
//! transfers are required for UAC 1.0 (sample rates are in the descriptor).
//! For UAC 2.0, sample rates live in the Clock Source entity and must be
//! queried at open time; [`UacStreamAlt::sample_rates`] is left empty here.

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
const AC_OUTPUT_TERMINAL: u8 = 0x03;

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
                    let bm_formats =
                        u32::from_le_bytes([desc[6], desc[7], desc[8], desc[9]]);
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
                    bit_depth = desc[6];
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
                    bit_depth = desc[5];
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

    // Find ISO OUT endpoint (required) and optional feedback IN endpoint
    let mut out_ep: Option<(u8, u16)> = None;
    let mut feedback_ep: Option<u8> = None;

    for ep in endpoints {
        if !ep.is_iso {
            continue;
        }
        if ep.is_out {
            out_ep = Some((ep.address, ep.max_packet));
        } else {
            // ISO IN on an audio streaming interface = feedback endpoint
            feedback_ep = Some(ep.address);
        }
    }

    let (out_ep_addr, max_packet) = out_ep?;

    Some(UacStreamAlt {
        alt_setting,
        format,
        bit_depth,
        channels,
        sample_rates,
        out_ep: out_ep_addr,
        feedback_ep,
        max_packet,
    })
}

// ---------------------------------------------------------------------------
// UAC 2.0 Clock Source ID extraction
// ---------------------------------------------------------------------------

/// Extract the Clock Source entity ID from the Audio Control interface descriptors.
///
/// Walks `ac_extra` looking for an OUTPUT_TERMINAL (subtype 0x03) and returns
/// its `bCSourceID` field (byte 8), which is the entity ID to use for
/// UAC 2.0 clock frequency control transfers.
///
/// Returns `None` if no OUTPUT_TERMINAL with a valid `bCSourceID` is found
/// (not a UAC 2.0 device, or descriptor too short).
pub fn parse_clock_id_from_ac(ac_extra: &[u8]) -> Option<u8> {
    for desc in CsDescIter::new(ac_extra) {
        // UAC 2.0 OUTPUT_TERMINAL is 12 bytes:
        // [0] bLength, [1] bDescriptorType=0x24, [2] bDescriptorSubtype=0x03,
        // [3] bTerminalID, [4..5] wTerminalType, [6] bAssocTerminal,
        // [7] bSourceID, [8] bCSourceID, [9..10] bmControls, [11] iTerminal
        if desc.len() < 9 {
            continue;
        }
        if desc[1] != CS_INTERFACE || desc[2] != AC_OUTPUT_TERMINAL {
            continue;
        }
        let clock_id = desc[8];
        if clock_id != 0 {
            return Some(clock_id);
        }
    }
    None
}
