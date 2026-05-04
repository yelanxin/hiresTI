//! Output target abstraction for native_transport.
//!
//! V2 native_transport produces decoded PCM slabs and pushes them to one of
//! several output backends. Historically only USB Rawlink V2 (libusb iso)
//! was supported; this module introduces an enum so the same decode path
//! can drive ALSA mmap or other backends without duplicating the loader /
//! decoder / DSP chain.

use crate::usb_audio::UsbRawSinkConfig;

/// Configuration for the ALSA mmap output backend.
///
/// The ALSA device is opened by the V2 worker thread on the first decoded
/// slab so the actual sample rate (which may differ from any caller-provided
/// hint) drives `snd_pcm_hw_params_set_rate_near`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AlsaMmapOutputConfig {
    /// ALSA device name in `hw:CARD,DEV` form (or `default`, `pipewire`, …).
    pub device: String,
    /// Caller-requested ring buffer (microseconds). Hardware may round.
    pub buffer_us: u32,
    /// Caller-requested period size in microseconds.
    pub latency_us: u32,
    /// Operator-selected real-time priority for the writer (0 = unset).
    pub realtime_priority: i32,
    /// Bit-depth/format preference string (`"S16LE"`, `"S24_3LE"`, `"S32LE"`,
    /// `"F32LE"`). Empty = follow source.
    pub preferred_format: String,
    /// Use exclusive (snd-pcm-direct hw:) access where possible.
    pub exclusive: bool,
}

/// Selects which output backend the V2 decode worker should drive.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NativeOutputTarget {
    Usb(UsbRawSinkConfig),
    AlsaMmap(AlsaMmapOutputConfig),
}

impl NativeOutputTarget {
    pub fn is_usb(&self) -> bool {
        matches!(self, Self::Usb(_))
    }

    pub fn is_alsa_mmap(&self) -> bool {
        matches!(self, Self::AlsaMmap(_))
    }

    pub fn usb_cfg(&self) -> Option<&UsbRawSinkConfig> {
        match self {
            Self::Usb(cfg) => Some(cfg),
            _ => None,
        }
    }

    pub fn alsa_cfg(&self) -> Option<&AlsaMmapOutputConfig> {
        match self {
            Self::AlsaMmap(cfg) => Some(cfg),
            _ => None,
        }
    }
}
