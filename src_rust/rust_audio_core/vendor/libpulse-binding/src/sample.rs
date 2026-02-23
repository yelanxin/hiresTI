// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language binding.
//
// Licensed under the MIT license or the Apache license (version 2.0), at your option. You may not
// copy, modify, or distribute this file except in compliance with said license. You can find copies
// of these licenses either in the LICENSE-MIT and LICENSE-APACHE files, or alternatively at
// <http://opensource.org/licenses/MIT> and <http://www.apache.org/licenses/LICENSE-2.0>
// respectively.
//
// Portions of documentation are copied from the LGPL 2.1+ licensed PulseAudio C headers on a
// fair-use basis, as discussed in the overall project readme (available in the git repository).

//! Constants and routines for sample type handling.
//!
//! # Overview
//!
//! PulseAudio is capable of handling a multitude of sample formats, rates and channels,
//! transparently converting and mixing them as needed.
//!
//! # Sample Formats
//!
//! PulseAudio supports the following sample formats:
//!
//! * `U8` - Unsigned 8 bit integer PCM.
//! * `S16LE` - Signed 16 integer bit PCM, little endian.
//! * `S16BE` - Signed 16 integer bit PCM, big endian.
//! * `FLOAT32LE` - 32 bit IEEE floating point PCM, little endian.
//! * `FLOAT32BE` - 32 bit IEEE floating point PCM, big endian.
//! * `ALAW` - 8 bit a-Law.
//! * `ULAW` - 8 bit mu-Law.
//! * `S32LE` - Signed 32 bit integer PCM, little endian.
//! * `S32BE` - Signed 32 bit integer PCM, big endian.
//! * `S24LE` - Signed 24 bit integer PCM packed, little endian.
//! * `S24BE` - Signed 24 bit integer PCM packed, big endian.
//! * `S24_32LE` - Signed 24 bit integer PCM in LSB of 32 bit words, little endian.
//! * `S24_32BE` - Signed 24 bit integer PCM in LSB of 32 bit words, big endian.
//!
//! The floating point sample formats have the range from `-1.0` to `1.0`.
//!
//! # Sample Rates
//!
//! PulseAudio supports any sample rate between 1 Hz and 192000 Hz. There is no point trying to
//! exceed the sample rate of the output device though as the signal will only get downsampled,
//! consuming CPU on the machine running the server.
//!
//! # Channels
//!
//! PulseAudio supports up to 32 individual channels. The order of the channels is up to the
//! application, but they must be continuous. To map channels to speakers, see
//! [`channelmap`](mod@crate::channelmap).
//!
//! # Calculations
//!
//! The PulseAudio library contains a number of convenience functions to do calculations on sample
//! formats:
//!
//! * [`Spec::bytes_per_second()`]: The number of bytes one second of audio will take given a sample
//!   format.
//! * [`Spec::frame_size()`]: The size, in bytes, of one frame (i.e. one set of samples, one for
//!   each channel).
//! * [`Spec::sample_size()`]: The size, in bytes, of one sample.
//! * [`Spec::bytes_to_usec()`]: Calculate the time it would take to play a buffer of a certain
//!   size.

use std::ffi::{CStr, CString};
use std::borrow::Cow;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::time::MicroSeconds;

/// Sample format.
///
/// Note, native-endian (endian-independent) associated constants are available on this type which
/// should be preferred over direct use of the endian-specific variants, for improved flexibility
/// and avoidance of mistakes.
#[repr(C)]
#[derive(Debug, Default, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum Format {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */
    /// Unsigned 8 Bit PCM.
    U8,
    /// 8 Bit a-Law.
    ALaw,
    /// 8 Bit mu-Law.
    ULaw,
    /// Signed 16 Bit PCM, little endian (PC).
    S16le,
    /// Signed 16 Bit PCM, big endian.
    S16be,
    /// 32 Bit IEEE floating point, little endian (PC), range -1.0 to 1.0.
    F32le,
    /// 32 Bit IEEE floating point, big endian, range -1.0 to 1.0.
    F32be,
    /// Signed 32 Bit PCM, little endian (PC).
    S32le,
    /// Signed 32 Bit PCM, big endian.
    S32be,
    /// Signed 24 Bit PCM packed, little endian (PC).
    S24le,
    /// Signed 24 Bit PCM packed, big endian.
    S24be,
    /// Signed 24 Bit PCM in LSB of 32 Bit words, little endian (PC).
    S24_32le,
    /// Signed 24 Bit PCM in LSB of 32 Bit words, big endian.
    S24_32be,

    /// An invalid value.
    #[default]
    Invalid = -1,
}

/// Check is equal to `sys` equivalent
#[test]
fn format_compare_capi() {
    assert_eq!(std::mem::size_of::<Format>(), std::mem::size_of::<capi::pa_sample_format_t>());
    assert_eq!(std::mem::align_of::<Format>(), std::mem::align_of::<capi::pa_sample_format_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(Format::U8,       Format::from(capi::pa_sample_format_t::U8));
    assert_eq!(Format::ALaw,     Format::from(capi::pa_sample_format_t::ALaw));
    assert_eq!(Format::ULaw,     Format::from(capi::pa_sample_format_t::ULaw));
    assert_eq!(Format::S16le,    Format::from(capi::pa_sample_format_t::S16le));
    assert_eq!(Format::S16be,    Format::from(capi::pa_sample_format_t::S16be));
    assert_eq!(Format::F32le,    Format::from(capi::pa_sample_format_t::F32le));
    assert_eq!(Format::F32be,    Format::from(capi::pa_sample_format_t::F32be));
    assert_eq!(Format::S32le,    Format::from(capi::pa_sample_format_t::S32le));
    assert_eq!(Format::S32be,    Format::from(capi::pa_sample_format_t::S32be));
    assert_eq!(Format::S24le,    Format::from(capi::pa_sample_format_t::S24le));
    assert_eq!(Format::S24be,    Format::from(capi::pa_sample_format_t::S24be));
    assert_eq!(Format::S24_32le, Format::from(capi::pa_sample_format_t::S24_32le));
    assert_eq!(Format::S24_32be, Format::from(capi::pa_sample_format_t::S24_32be));
    assert_eq!(Format::Invalid,  Format::from(capi::pa_sample_format_t::Invalid));
}

impl From<Format> for capi::pa_sample_format_t {
    #[inline]
    fn from(f: Format) -> Self {
        unsafe { std::mem::transmute(f) }
    }
}
impl From<capi::pa_sample_format_t> for Format {
    #[inline]
    fn from(f: capi::pa_sample_format_t) -> Self {
        unsafe { std::mem::transmute(f) }
    }
}

/// Endian-independent format identifiers, for big-endian systems.
#[cfg(target_endian = "big")]
mod ei_formats {
    use super::Format;

    pub const SAMPLE_S16NE:     Format = Format::S16be;
    pub const SAMPLE_FLOAT32NE: Format = Format::F32be;
    pub const SAMPLE_S32NE:     Format = Format::S32be;
    pub const SAMPLE_S24NE:     Format = Format::S24be;
    pub const SAMPLE_S24_32NE:  Format = Format::S24_32be;

    pub const SAMPLE_S16RE:     Format = Format::S16le;
    pub const SAMPLE_FLOAT32RE: Format = Format::F32le;
    pub const SAMPLE_S32RE:     Format = Format::S32le;
    pub const SAMPLE_S24RE:     Format = Format::S24le;
    pub const SAMPLE_S24_32RE:  Format = Format::S24_32le;
}

/// Endian-independent format identifiers, for little-endian systems.
#[cfg(target_endian = "little")]
mod ei_formats {
    use super::Format;

    pub const SAMPLE_S16NE:     Format = Format::S16le;
    pub const SAMPLE_FLOAT32NE: Format = Format::F32le;
    pub const SAMPLE_S32NE:     Format = Format::S32le;
    pub const SAMPLE_S24NE:     Format = Format::S24le;
    pub const SAMPLE_S24_32NE:  Format = Format::S24_32le;

    pub const SAMPLE_S16RE:     Format = Format::S16be;
    pub const SAMPLE_FLOAT32RE: Format = Format::F32be;
    pub const SAMPLE_S32RE:     Format = Format::S32be;
    pub const SAMPLE_S24RE:     Format = Format::S24be;
    pub const SAMPLE_S24_32RE:  Format = Format::S24_32be;
}

/// A sample format and attribute specification.
#[repr(C)]
#[derive(Debug, Copy, Clone, Eq)]
pub struct Spec {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */
    /// The sample format.
    pub format: Format,
    /// The sample rate. (e.g. 44100).
    pub rate: u32,
    /// Audio channels. (1 for mono, 2 for stereo, ...).
    pub channels: u8,
}

/// Test size is equal to `sys` equivalent
#[test]
fn spec_compare_capi() {
    assert_eq!(std::mem::size_of::<Spec>(), std::mem::size_of::<capi::pa_sample_spec>());
    assert_eq!(std::mem::align_of::<Spec>(), std::mem::align_of::<capi::pa_sample_spec>());
}

impl AsRef<capi::pa_sample_spec> for Spec {
    #[inline]
    fn as_ref(&self) -> &capi::pa_sample_spec {
        unsafe { &*(self as *const Self as *const capi::pa_sample_spec) }
    }
}
impl AsMut<capi::pa_sample_spec> for Spec {
    #[inline]
    fn as_mut(&mut self) -> &mut capi::pa_sample_spec {
        unsafe { &mut *(self as *mut Self as *mut capi::pa_sample_spec) }
    }
}
impl AsRef<Spec> for capi::pa_sample_spec {
    #[inline]
    fn as_ref(&self) -> &Spec {
        unsafe { &*(self as *const Self as *const Spec) }
    }
}

impl From<capi::pa_sample_spec> for Spec {
    #[inline]
    fn from(s: capi::pa_sample_spec) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}

impl PartialEq for Spec {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        unsafe { capi::pa_sample_spec_equal(self.as_ref(), other.as_ref()) != 0 }
    }
}

impl Spec {
    /// Maximum number of allowed channels.
    pub const CHANNELS_MAX: u8 = capi::PA_CHANNELS_MAX;
    /// Maximum allowed sample rate.
    pub const RATE_MAX: u32 = capi::PA_RATE_MAX;

    /// Initializes the specified sample spec.
    ///
    /// The sample spec will have a defined state but [`is_valid()`](Self::is_valid) will fail for
    /// it.
    #[inline]
    pub fn init(&mut self) {
        unsafe { capi::pa_sample_spec_init(self.as_mut()); }
    }

    /// Checks if the whole sample type specification is valid.
    #[inline]
    pub fn is_valid(&self) -> bool {
        unsafe { capi::pa_sample_spec_valid(self.as_ref()) != 0 }
    }

    /// Checks only if the format attribute is valid.
    ///
    /// Or in other words that the client library running on the end user system accepts it.
    #[inline]
    pub fn format_is_valid(&self) -> bool {
        unsafe { capi::pa_sample_format_valid(self.format as u32) != 0 }
    }

    /// Checks only if the rate is within the supported range.
    #[inline]
    pub fn rate_is_valid(&self) -> bool {
        unsafe { capi::pa_sample_rate_valid(self.rate) != 0 }
    }

    /// Checks only if the channel count is within the supported range.
    #[inline]
    pub fn channels_are_valid(&self) -> bool {
        unsafe { capi::pa_channels_valid(self.channels) != 0 }
    }

    /// Gets the amount of bytes that constitute playback of one second of audio, with the specified
    /// sample type.
    #[inline]
    pub fn bytes_per_second(&self) -> usize {
        unsafe { capi::pa_bytes_per_second(self.as_ref()) }
    }

    /// Gets the size of a frame.
    #[inline]
    pub fn frame_size(&self) -> usize {
        unsafe { capi::pa_frame_size(self.as_ref()) }
    }

    /// Gets the size of a sample.
    #[inline]
    pub fn sample_size(&self) -> usize {
        unsafe { capi::pa_sample_size(self.as_ref()) }
    }

    /// Calculates the time it would take to play a buffer of the specified size.
    ///
    /// The return value will always be rounded down for non-integral return values.
    ///
    /// Note, the underlying calculation may overflow for very large values.
    #[inline]
    pub fn bytes_to_usec(&self, length: u64) -> MicroSeconds {
        MicroSeconds(unsafe { capi::pa_bytes_to_usec(length, self.as_ref()) })
    }

    /// Calculates the size of a buffer required, for playback duration of the time specified.
    ///
    /// The return value will always be rounded down for non-integral return values.
    ///
    /// Note, the underlying calculation may overflow for very large values.
    #[inline]
    pub fn usec_to_bytes(&self, t: MicroSeconds) -> usize {
        unsafe { capi::pa_usec_to_bytes(t.0, self.as_ref()) }
    }

    /// Pretty prints a sample type specification to a string.
    pub fn print(&self) -> String {
        const PRINT_MAX: usize = capi::PA_SAMPLE_SPEC_SNPRINT_MAX;
        let mut tmp = Vec::with_capacity(PRINT_MAX);
        unsafe {
            capi::pa_sample_spec_snprint(tmp.as_mut_ptr(), PRINT_MAX, self.as_ref());
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }
}

/// Pretty print a byte size value (i.e. “2.5 MiB”).
pub fn bytes_print(bytes: u32) -> String {
    const PRINT_MAX: usize = capi::PA_BYTES_SNPRINT_MAX;
    let mut tmp = Vec::with_capacity(PRINT_MAX);
    unsafe {
        capi::pa_bytes_snprint(tmp.as_mut_ptr(), PRINT_MAX, bytes);
        CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
    }
}

impl Format {
    /// Signed 16-bit PCM, native endian.
    pub const S16NE:     Self = self::ei_formats::SAMPLE_S16NE;
    /// 32-bit IEEE floating point, native endian.
    pub const FLOAT32NE: Self = self::ei_formats::SAMPLE_FLOAT32NE;
    /// Signed 32-bit PCM, native endian.
    pub const S32NE:     Self = self::ei_formats::SAMPLE_S32NE;
    /// Signed 24-bit PCM packed, native endian.
    pub const S24NE:     Self = self::ei_formats::SAMPLE_S24NE;
    /// Signed 24-bit PCM in LSB of 32-bit words, native endian.
    pub const S24_32NE:  Self = self::ei_formats::SAMPLE_S24_32NE;

    /// Signed 16-bit PCM reverse endian.
    pub const S16RE:     Self = self::ei_formats::SAMPLE_S16RE;
    /// 32-bit IEEE floating point, reverse endian.
    pub const FLOAT32RE: Self = self::ei_formats::SAMPLE_FLOAT32RE;
    /// Signed 32-bit PCM, reverse endian.
    pub const S32RE:     Self = self::ei_formats::SAMPLE_S32RE;
    /// Signed 24-bit PCM, packed reverse endian.
    pub const S24RE:     Self = self::ei_formats::SAMPLE_S24RE;
    /// Signed 24-bit PCM, in LSB of 32-bit words, reverse endian.
    pub const S24_32RE:  Self = self::ei_formats::SAMPLE_S24_32RE;

    /// Similar to [`Spec::sample_size()`] but take a sample format instead of full sample spec.
    #[inline]
    pub fn size(&self) -> usize {
        unsafe { capi::pa_sample_size_of_format((*self).into()) }
    }

    /// Gets a descriptive string for the specified sample format.
    pub fn to_string(&self) -> Option<Cow<'static, str>> {
        let ptr = unsafe { capi::pa_sample_format_to_string((*self).into()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy() }),
            true => None,
        }
    }

    /// Parses a sample format text. Inverse of [`to_string()`](Self::to_string).
    pub fn parse(format: &str) -> Self {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_format = CString::new(format).unwrap();
        unsafe { capi::pa_parse_sample_format(c_format.as_ptr()).into() }
    }

    /// Checks if format is little endian.
    ///
    /// Returns `true` when the specified format is little endian, `false` if big endian. Returns
    /// `None` when endianness does not apply to this format, or if unknown.
    pub fn is_le(&self) -> Option<bool> {
        match unsafe { capi::pa_sample_format_is_le((*self).into()) } {
            0 => Some(false),
            1 => Some(true),
            _ => None,
        }
    }

    /// Checks if format is big endian.
    ///
    /// Returns `true` when the specified format is big endian, `false` if little endian. Returns
    /// `None` when endianness does not apply to this format, or if unknown.
    pub fn is_be(&self) -> Option<bool> {
        match unsafe { capi::pa_sample_format_is_be((*self).into()) } {
            0 => Some(false),
            1 => Some(true),
            _ => None,
        }
    }

    /// Checks if format is native endian.
    ///
    /// Returns `true` when the specified format is native endian, `false` when not. Returns `None`
    /// when endianness does not apply to the specified format, or endianness is unknown.
    #[inline]
    pub fn is_ne(&self) -> Option<bool> {
        #[cfg(target_endian = "big")]
        { Format::is_be(self) }
        #[cfg(target_endian = "little")]
        { Format::is_le(self) }
    }

    /// Checks if format is reverse of native endian.
    ///
    /// Returns `true` when the specified format is reverse endian, `false` when not. Returns `None`
    /// when endianness does not apply to the specified format, or endianness is unknown.
    #[inline]
    pub fn is_re(&self) -> Option<bool> {
        self.is_ne().and_then(|b| Some(!b))
    }
}
