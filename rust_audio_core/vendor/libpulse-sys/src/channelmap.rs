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

//! Constants and routines for handing channel mapping.

use std::os::raw::c_char;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::sample::pa_sample_spec;

pub type pa_channel_position_mask_t = u64;

#[inline(always)]
pub const fn pa_channel_position_mask(pos: pa_channel_position_t) -> pa_channel_position_mask_t {
    1u64 << (pos as pa_channel_position_mask_t)
}

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_channel_position_t {
    Invalid = -1,
    Mono = 0,

    FrontLeft,
    FrontRight,
    FrontCenter,

    RearCenter,
    RearLeft,
    RearRight,

    Lfe,

    FrontLeftOfCenter,
    FrontRightOfCenter,

    SideLeft,
    SideRight,

    Aux0,
    Aux1,
    Aux2,
    Aux3,
    Aux4,
    Aux5,
    Aux6,
    Aux7,
    Aux8,
    Aux9,
    Aux10,
    Aux11,
    Aux12,
    Aux13,
    Aux14,
    Aux15,
    Aux16,
    Aux17,
    Aux18,
    Aux19,
    Aux20,
    Aux21,
    Aux22,
    Aux23,
    Aux24,
    Aux25,
    Aux26,
    Aux27,
    Aux28,
    Aux29,
    Aux30,
    Aux31,

    TopCenter,

    TopFrontLeft,
    TopFrontRight,
    TopFrontCenter,

    TopRearLeft,
    TopRearRight,
    TopRearCenter,
}

pub const PA_CHANNEL_POSITION_MAX: usize = 51;

pub const PA_CHANNEL_POSITION_INVALID:               pa_channel_position_t = pa_channel_position_t::Invalid;
pub const PA_CHANNEL_POSITION_MONO:                  pa_channel_position_t = pa_channel_position_t::Mono;
pub const PA_CHANNEL_POSITION_LEFT:                  pa_channel_position_t = pa_channel_position_t::FrontLeft;
pub const PA_CHANNEL_POSITION_RIGHT:                 pa_channel_position_t = pa_channel_position_t::FrontRight;
pub const PA_CHANNEL_POSITION_CENTER:                pa_channel_position_t = pa_channel_position_t::FrontCenter;
pub const PA_CHANNEL_POSITION_FRONT_LEFT:            pa_channel_position_t = pa_channel_position_t::FrontLeft;
pub const PA_CHANNEL_POSITION_FRONT_RIGHT:           pa_channel_position_t = pa_channel_position_t::FrontRight;
pub const PA_CHANNEL_POSITION_FRONT_CENTER:          pa_channel_position_t = pa_channel_position_t::FrontCenter;
pub const PA_CHANNEL_POSITION_REAR_CENTER:           pa_channel_position_t = pa_channel_position_t::RearCenter;
pub const PA_CHANNEL_POSITION_REAR_LEFT:             pa_channel_position_t = pa_channel_position_t::RearLeft;
pub const PA_CHANNEL_POSITION_REAR_RIGHT:            pa_channel_position_t = pa_channel_position_t::RearRight;
pub const PA_CHANNEL_POSITION_LFE:                   pa_channel_position_t = pa_channel_position_t::Lfe;
pub const PA_CHANNEL_POSITION_SUBWOOFER:             pa_channel_position_t = pa_channel_position_t::Lfe;
pub const PA_CHANNEL_POSITION_FRONT_LEFT_OF_CENTER:  pa_channel_position_t = pa_channel_position_t::FrontLeftOfCenter;
pub const PA_CHANNEL_POSITION_FRONT_RIGHT_OF_CENTER: pa_channel_position_t = pa_channel_position_t::FrontRightOfCenter;
pub const PA_CHANNEL_POSITION_SIDE_LEFT:             pa_channel_position_t = pa_channel_position_t::SideLeft;
pub const PA_CHANNEL_POSITION_SIDE_RIGHT:            pa_channel_position_t = pa_channel_position_t::SideRight;
pub const PA_CHANNEL_POSITION_AUX0:                  pa_channel_position_t = pa_channel_position_t::Aux0;
pub const PA_CHANNEL_POSITION_AUX1:                  pa_channel_position_t = pa_channel_position_t::Aux1;
pub const PA_CHANNEL_POSITION_AUX2:                  pa_channel_position_t = pa_channel_position_t::Aux2;
pub const PA_CHANNEL_POSITION_AUX3:                  pa_channel_position_t = pa_channel_position_t::Aux3;
pub const PA_CHANNEL_POSITION_AUX4:                  pa_channel_position_t = pa_channel_position_t::Aux4;
pub const PA_CHANNEL_POSITION_AUX5:                  pa_channel_position_t = pa_channel_position_t::Aux5;
pub const PA_CHANNEL_POSITION_AUX6:                  pa_channel_position_t = pa_channel_position_t::Aux6;
pub const PA_CHANNEL_POSITION_AUX7:                  pa_channel_position_t = pa_channel_position_t::Aux7;
pub const PA_CHANNEL_POSITION_AUX8:                  pa_channel_position_t = pa_channel_position_t::Aux8;
pub const PA_CHANNEL_POSITION_AUX9:                  pa_channel_position_t = pa_channel_position_t::Aux9;
pub const PA_CHANNEL_POSITION_AUX10:                 pa_channel_position_t = pa_channel_position_t::Aux10;
pub const PA_CHANNEL_POSITION_AUX11:                 pa_channel_position_t = pa_channel_position_t::Aux11;
pub const PA_CHANNEL_POSITION_AUX12:                 pa_channel_position_t = pa_channel_position_t::Aux12;
pub const PA_CHANNEL_POSITION_AUX13:                 pa_channel_position_t = pa_channel_position_t::Aux13;
pub const PA_CHANNEL_POSITION_AUX14:                 pa_channel_position_t = pa_channel_position_t::Aux14;
pub const PA_CHANNEL_POSITION_AUX15:                 pa_channel_position_t = pa_channel_position_t::Aux15;
pub const PA_CHANNEL_POSITION_AUX16:                 pa_channel_position_t = pa_channel_position_t::Aux16;
pub const PA_CHANNEL_POSITION_AUX17:                 pa_channel_position_t = pa_channel_position_t::Aux17;
pub const PA_CHANNEL_POSITION_AUX18:                 pa_channel_position_t = pa_channel_position_t::Aux18;
pub const PA_CHANNEL_POSITION_AUX19:                 pa_channel_position_t = pa_channel_position_t::Aux19;
pub const PA_CHANNEL_POSITION_AUX20:                 pa_channel_position_t = pa_channel_position_t::Aux20;
pub const PA_CHANNEL_POSITION_AUX21:                 pa_channel_position_t = pa_channel_position_t::Aux21;
pub const PA_CHANNEL_POSITION_AUX22:                 pa_channel_position_t = pa_channel_position_t::Aux22;
pub const PA_CHANNEL_POSITION_AUX23:                 pa_channel_position_t = pa_channel_position_t::Aux23;
pub const PA_CHANNEL_POSITION_AUX24:                 pa_channel_position_t = pa_channel_position_t::Aux24;
pub const PA_CHANNEL_POSITION_AUX25:                 pa_channel_position_t = pa_channel_position_t::Aux25;
pub const PA_CHANNEL_POSITION_AUX26:                 pa_channel_position_t = pa_channel_position_t::Aux26;
pub const PA_CHANNEL_POSITION_AUX27:                 pa_channel_position_t = pa_channel_position_t::Aux27;
pub const PA_CHANNEL_POSITION_AUX28:                 pa_channel_position_t = pa_channel_position_t::Aux28;
pub const PA_CHANNEL_POSITION_AUX29:                 pa_channel_position_t = pa_channel_position_t::Aux29;
pub const PA_CHANNEL_POSITION_AUX30:                 pa_channel_position_t = pa_channel_position_t::Aux30;
pub const PA_CHANNEL_POSITION_AUX31:                 pa_channel_position_t = pa_channel_position_t::Aux31;
pub const PA_CHANNEL_POSITION_TOP_CENTER:            pa_channel_position_t = pa_channel_position_t::TopCenter;
pub const PA_CHANNEL_POSITION_TOP_FRONT_LEFT:        pa_channel_position_t = pa_channel_position_t::TopFrontLeft;
pub const PA_CHANNEL_POSITION_TOP_FRONT_RIGHT:       pa_channel_position_t = pa_channel_position_t::TopFrontRight;
pub const PA_CHANNEL_POSITION_TOP_FRONT_CENTER:      pa_channel_position_t = pa_channel_position_t::TopFrontCenter;
pub const PA_CHANNEL_POSITION_TOP_REAR_LEFT:         pa_channel_position_t = pa_channel_position_t::TopRearLeft;
pub const PA_CHANNEL_POSITION_TOP_REAR_RIGHT:        pa_channel_position_t = pa_channel_position_t::TopRearRight;
pub const PA_CHANNEL_POSITION_TOP_REAR_CENTER:       pa_channel_position_t = pa_channel_position_t::TopRearCenter;

impl Default for pa_channel_position_t {
    fn default() -> Self {
        pa_channel_position_t::Invalid
    }
}

/// Channel map definition standards.
///
/// Used in having a channel map automatically setup per number of channels and a specific standard.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_channel_map_def_t {
    /// The mapping from RFC3551, which is based on AIFF-C.
    AIFF,
    /// The default mapping used by ALSA. This mapping is probably not too useful since ALSA’s
    /// default channel mapping depends on the device string used.
    ALSA,
    /// Only aux channels.
    Aux,
    /// Microsoft’s WAVEFORMATEXTENSIBLE mapping. This mapping works as if all LSBs of dwChannelMask
    /// are set.
    WAVEEx,
    /// The default channel mapping used by OSS as defined in the OSS 4.0 API specs. This mapping is
    /// probably not too useful since the OSS API has changed in this respect and no longer knows a
    /// default channel mapping based on the number of channels.
    OSS,
}

pub const PA_CHANNEL_MAP_DEF_MAX: usize = 5;

pub const PA_CHANNEL_MAP_AIFF:    pa_channel_map_def_t = pa_channel_map_def_t::AIFF;
pub const PA_CHANNEL_MAP_ALSA:    pa_channel_map_def_t = pa_channel_map_def_t::ALSA;
pub const PA_CHANNEL_MAP_AUX:     pa_channel_map_def_t = pa_channel_map_def_t::Aux;
pub const PA_CHANNEL_MAP_WAVEEX:  pa_channel_map_def_t = pa_channel_map_def_t::WAVEEx;
pub const PA_CHANNEL_MAP_OSS:     pa_channel_map_def_t = pa_channel_map_def_t::OSS;
pub const PA_CHANNEL_MAP_DEFAULT: pa_channel_map_def_t = pa_channel_map_def_t::AIFF;

impl Default for pa_channel_map_def_t {
    fn default() -> Self {
        PA_CHANNEL_MAP_DEFAULT
    }
}

#[repr(C)]
#[derive(Default, Debug, Copy, Clone)]
pub struct pa_channel_map {
    pub channels: u8,
    pub map: [pa_channel_position_t; crate::sample::PA_CHANNELS_MAX as usize],
}

pub const PA_CHANNEL_MAP_SNPRINT_MAX: usize = 336;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_channel_map_init(m: *mut pa_channel_map) -> *mut pa_channel_map;
    pub fn pa_channel_map_init_mono(m: *mut pa_channel_map) -> *mut pa_channel_map;
    pub fn pa_channel_map_init_stereo(m: *mut pa_channel_map) -> *mut pa_channel_map;
    pub fn pa_channel_map_init_auto(m: *mut pa_channel_map, channels: u32, def: pa_channel_map_def_t) -> *mut pa_channel_map;
    pub fn pa_channel_map_init_extend(m: *mut pa_channel_map, channels: u32, def: pa_channel_map_def_t) -> *mut pa_channel_map;
    pub fn pa_channel_position_to_string(pos: pa_channel_position_t) -> *const c_char;
    pub fn pa_channel_position_from_string(s: *const c_char) -> pa_channel_position_t;
    pub fn pa_channel_position_to_pretty_string(pos: pa_channel_position_t) -> *const c_char;
    pub fn pa_channel_map_snprint(s: *mut c_char, l: usize, map: *const pa_channel_map) -> *mut c_char;
    pub fn pa_channel_map_parse(map: *mut pa_channel_map, s: *const c_char) -> *mut pa_channel_map;
    pub fn pa_channel_map_equal(a: *const pa_channel_map, b: *const pa_channel_map) -> i32;
    pub fn pa_channel_map_valid(map: *const pa_channel_map) -> i32;
    pub fn pa_channel_map_compatible(map: *const pa_channel_map, ss: *const pa_sample_spec) -> i32;
    pub fn pa_channel_map_superset(a: *const pa_channel_map, b: *const pa_channel_map) -> i32;
    pub fn pa_channel_map_can_balance(map: *const pa_channel_map) -> i32;
    pub fn pa_channel_map_can_fade(map: *const pa_channel_map) -> i32;
    #[cfg(any(doc, feature = "pa_v8"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v8")))]
    pub fn pa_channel_map_can_lfe_balance(map: *const pa_channel_map) -> i32;
    pub fn pa_channel_map_to_name(map: *const pa_channel_map) -> *const c_char;
    pub fn pa_channel_map_to_pretty_name(map: *const pa_channel_map) -> *const c_char;
    pub fn pa_channel_map_has_position(map: *const pa_channel_map, p: pa_channel_position_t) -> i32;
    pub fn pa_channel_map_mask(map: *const pa_channel_map) -> pa_channel_position_mask_t;
}
