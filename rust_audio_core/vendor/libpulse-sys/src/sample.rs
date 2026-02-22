// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language linking library.
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

use std::os::raw::c_char;
use num_derive::{FromPrimitive, ToPrimitive};

/// Maximum number of allowed channels.
pub const PA_CHANNELS_MAX: u8 = 32;

/// Maximum allowed sample rate.
pub const PA_RATE_MAX: u32 = 48000 * 16;

/// Sample format.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum pa_sample_format_t {
    U8,
    ALaw,
    ULaw,
    S16le,
    S16be,
    F32le,
    F32be,
    S32le,
    S32be,
    S24le,
    S24be,
    S24_32le,
    S24_32be,

    Invalid = -1,
}

pub const PA_SAMPLE_MAX: usize = 13;

pub const PA_SAMPLE_U8:        pa_sample_format_t = pa_sample_format_t::U8;
pub const PA_SAMPLE_ALAW:      pa_sample_format_t = pa_sample_format_t::ALaw;
pub const PA_SAMPLE_ULAW:      pa_sample_format_t = pa_sample_format_t::ULaw;
pub const PA_SAMPLE_S16LE:     pa_sample_format_t = pa_sample_format_t::S16le;
pub const PA_SAMPLE_S16BE:     pa_sample_format_t = pa_sample_format_t::S16be;
pub const PA_SAMPLE_FLOAT32LE: pa_sample_format_t = pa_sample_format_t::F32le;
pub const PA_SAMPLE_FLOAT32BE: pa_sample_format_t = pa_sample_format_t::F32be;
pub const PA_SAMPLE_S32LE:     pa_sample_format_t = pa_sample_format_t::S32le;
pub const PA_SAMPLE_S32BE:     pa_sample_format_t = pa_sample_format_t::S32be;
pub const PA_SAMPLE_S24LE:     pa_sample_format_t = pa_sample_format_t::S24le;
pub const PA_SAMPLE_S24BE:     pa_sample_format_t = pa_sample_format_t::S24be;
pub const PA_SAMPLE_S24_32LE:  pa_sample_format_t = pa_sample_format_t::S24_32le;
pub const PA_SAMPLE_S24_32BE:  pa_sample_format_t = pa_sample_format_t::S24_32be;
pub const PA_SAMPLE_INVALID:   pa_sample_format_t = pa_sample_format_t::Invalid;

impl Default for pa_sample_format_t {
    fn default() -> Self {
        pa_sample_format_t::Invalid
    }
}

pub use self::ei_formats::*;

/// Endian-independent format identifiers.
#[cfg(target_endian = "big")]
mod ei_formats {
    use super::pa_sample_format_t;

    pub const PA_SAMPLE_S16NE:     pa_sample_format_t = pa_sample_format_t::S16be;
    pub const PA_SAMPLE_FLOAT32NE: pa_sample_format_t = pa_sample_format_t::F32be;
    pub const PA_SAMPLE_S32NE:     pa_sample_format_t = pa_sample_format_t::S32be;
    pub const PA_SAMPLE_S24NE:     pa_sample_format_t = pa_sample_format_t::S24be;
    pub const PA_SAMPLE_S24_32NE:  pa_sample_format_t = pa_sample_format_t::S24_32be;

    pub const PA_SAMPLE_S16RE:     pa_sample_format_t = pa_sample_format_t::S16le;
    pub const PA_SAMPLE_FLOAT32RE: pa_sample_format_t = pa_sample_format_t::F32le;
    pub const PA_SAMPLE_S32RE:     pa_sample_format_t = pa_sample_format_t::S32le;
    pub const PA_SAMPLE_S24RE:     pa_sample_format_t = pa_sample_format_t::S24le;
    pub const PA_SAMPLE_S24_32RE:  pa_sample_format_t = pa_sample_format_t::S24_32le;
}

/// Endian-independent format identifiers.
#[cfg(target_endian = "little")]
mod ei_formats {
    use super::pa_sample_format_t;

    pub const PA_SAMPLE_S16NE:     pa_sample_format_t = pa_sample_format_t::S16le;
    pub const PA_SAMPLE_FLOAT32NE: pa_sample_format_t = pa_sample_format_t::F32le;
    pub const PA_SAMPLE_S32NE:     pa_sample_format_t = pa_sample_format_t::S32le;
    pub const PA_SAMPLE_S24NE:     pa_sample_format_t = pa_sample_format_t::S24le;
    pub const PA_SAMPLE_S24_32NE:  pa_sample_format_t = pa_sample_format_t::S24_32le;

    pub const PA_SAMPLE_S16RE:     pa_sample_format_t = pa_sample_format_t::S16be;
    pub const PA_SAMPLE_FLOAT32RE: pa_sample_format_t = pa_sample_format_t::F32be;
    pub const PA_SAMPLE_S32RE:     pa_sample_format_t = pa_sample_format_t::S32be;
    pub const PA_SAMPLE_S24RE:     pa_sample_format_t = pa_sample_format_t::S24be;
    pub const PA_SAMPLE_S24_32RE:  pa_sample_format_t = pa_sample_format_t::S24_32be;
}

/// A shortcut for [`PA_SAMPLE_FLOAT32NE`].
pub const PA_SAMPLE_FLOAT32: pa_sample_format_t = PA_SAMPLE_FLOAT32NE;

/// A sample format and attribute specification.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct pa_sample_spec {
    /// The sample format.
    pub format: pa_sample_format_t,

    /// The sample rate. (e.g. 44100).
    pub rate: u32,

    /// Audio channels. (1 for mono, 2 for stereo, ...).
    pub channels: u8,
}

/// Type for usec specifications (unsigned). Always 64 bit.
pub type pa_usec_t = u64;

/// The maximum length of strings returned by [`pa_sample_spec_snprint()`].
///
/// Please note that this value can change with any release without warning and without being
/// considered API or ABI breakage. You should not use this definition anywhere where it might
/// become part of an ABI.
pub const PA_SAMPLE_SPEC_SNPRINT_MAX: usize = 32;

/// The maximum length of strings returned by [`pa_bytes_snprint()`].
///
/// Please note that this value can change with any release without warning and without being
/// considered API or ABI breakage. You should not use this definition anywhere where it might
/// become part of an ABI.
pub const PA_BYTES_SNPRINT_MAX: usize = 11;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_bytes_per_second(spec: *const pa_sample_spec) -> usize;
    pub fn pa_frame_size(spec: *const pa_sample_spec) -> usize;
    pub fn pa_sample_size(spec: *const pa_sample_spec) -> usize;
    pub fn pa_sample_size_of_format(f: pa_sample_format_t) -> usize;
    pub fn pa_bytes_to_usec(length: u64, spec: *const pa_sample_spec) -> pa_usec_t;
    pub fn pa_usec_to_bytes(t: pa_usec_t, spec: *const pa_sample_spec) -> usize;
    pub fn pa_sample_spec_init(spec: *mut pa_sample_spec) -> *mut pa_sample_spec;
    pub fn pa_sample_format_valid(format: u32) -> i32;
    pub fn pa_sample_rate_valid(rate: u32) -> i32;
    pub fn pa_channels_valid(channels: u8) -> i32;
    pub fn pa_sample_spec_valid(spec: *const pa_sample_spec) -> i32;
    pub fn pa_sample_spec_equal(a: *const pa_sample_spec, b: *const pa_sample_spec) -> i32;
    pub fn pa_sample_format_to_string(f: pa_sample_format_t) -> *const c_char;
    pub fn pa_parse_sample_format(format: *const c_char) -> pa_sample_format_t;

    pub fn pa_sample_spec_snprint(s: *mut c_char, l: usize, spec: *const pa_sample_spec) -> *mut c_char;

    pub fn pa_bytes_snprint(s: *mut c_char, l: usize, v: u32) -> *mut c_char;
    pub fn pa_sample_format_is_le(f: pa_sample_format_t) -> i32;
    pub fn pa_sample_format_is_be(f: pa_sample_format_t) -> i32;
}
