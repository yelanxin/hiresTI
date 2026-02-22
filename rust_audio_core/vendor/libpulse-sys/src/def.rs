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

//! Global definitions.

use std::os::raw::c_void;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::timeval::timeval;
use crate::sample::pa_usec_t;

/// An invalid index.
pub const PA_INVALID_INDEX: u32 = std::u32::MAX;

pub type pa_free_cb_t = Option<extern "C" fn(p: *mut c_void)>;

/// Device type, source or sink.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_device_type_t {
    /// A sink.
    Sink,
    /// A source.
    Source,
}

pub const PA_DEVICE_TYPE_SINK:   pa_device_type_t = pa_device_type_t::Sink;
pub const PA_DEVICE_TYPE_SOURCE: pa_device_type_t = pa_device_type_t::Source;

#[repr(C)]
pub struct pa_buffer_attr {
    pub maxlength: u32,
    pub tlength: u32,
    pub prebuf: u32,
    pub minreq: u32,
    pub fragsize: u32,
}

#[repr(C)]
pub struct pa_timing_info {
    pub timestamp: timeval,
    pub synchronized_clocks: i32,
    pub sink_usec: pa_usec_t,
    pub source_usec: pa_usec_t,
    pub transport_usec: pa_usec_t,
    pub playing: i32,
    pub write_index_corrupt: i32,
    pub write_index: i64,
    pub read_index_corrupt: i32,
    pub read_index: i64,
    pub configured_sink_usec: pa_usec_t,
    pub configured_source_usec: pa_usec_t,
    pub since_underrun: i64,
}

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct pa_spawn_api {
    pub prefork: Option<extern "C" fn()>,
    pub postfork: Option<extern "C" fn()>,
    pub atfork: Option<extern "C" fn()>,
}

pub type pa_sink_flags_t = u32;

pub use self::sink_flags::*;

/// Special sink flags.
pub mod sink_flags {
    use super::pa_sink_flags_t;

    pub const PA_SINK_NOFLAGS:         pa_sink_flags_t = 0;
    pub const PA_SINK_HW_VOLUME_CTRL:  pa_sink_flags_t = 1 << 0;
    pub const PA_SINK_LATENCY:         pa_sink_flags_t = 1 << 1;
    pub const PA_SINK_HARDWARE:        pa_sink_flags_t = 1 << 2;
    pub const PA_SINK_NETWORK:         pa_sink_flags_t = 1 << 3;
    pub const PA_SINK_HW_MUTE_CTRL:    pa_sink_flags_t = 1 << 4;
    pub const PA_SINK_DECIBEL_VOLUME:  pa_sink_flags_t = 1 << 5;
    pub const PA_SINK_FLAT_VOLUME:     pa_sink_flags_t = 1 << 6;
    pub const PA_SINK_DYNAMIC_LATENCY: pa_sink_flags_t = 1 << 7;
    pub const PA_SINK_SET_FORMATS:     pa_sink_flags_t = 1 << 8;
}

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_sink_state_t {
    Invalid   = -1,
    Running   = 0,
    Idle      = 1,
    Suspended = 2,
}

pub const PA_SINK_INVALID_STATE: pa_sink_state_t = pa_sink_state_t::Invalid;
pub const PA_SINK_RUNNING:       pa_sink_state_t = pa_sink_state_t::Running;
pub const PA_SINK_IDLE:          pa_sink_state_t = pa_sink_state_t::Idle;
pub const PA_SINK_SUSPENDED:     pa_sink_state_t = pa_sink_state_t::Suspended;

/// Checks if state is playing, i.e. running or idle (returns `true` if so).
#[inline(always)]
pub fn pa_sink_is_opened(state: pa_sink_state_t) -> bool {
    state == pa_sink_state_t::Running || state == pa_sink_state_t::Idle
}

/// Checks if state is running (returns `true` if so).
#[inline(always)]
pub fn pa_sink_is_running(state: pa_sink_state_t) -> bool {
    state == pa_sink_state_t::Running
}

pub type pa_source_flags_t = u32;

pub use self::source_flags::*;

/// Special source flags.
pub mod source_flags {
    use super::pa_source_flags_t;

    pub const PA_SOURCE_NOFLAGS:         pa_source_flags_t = 0;
    pub const PA_SOURCE_HW_VOLUME_CTRL:  pa_source_flags_t = 1 << 0;
    pub const PA_SOURCE_LATENCY:         pa_source_flags_t = 1 << 1;
    pub const PA_SOURCE_HARDWARE:        pa_source_flags_t = 1 << 2;
    pub const PA_SOURCE_NETWORK:         pa_source_flags_t = 1 << 3;
    pub const PA_SOURCE_HW_MUTE_CTRL:    pa_source_flags_t = 1 << 4;
    pub const PA_SOURCE_DECIBEL_VOLUME:  pa_source_flags_t = 1 << 5;
    pub const PA_SOURCE_DYNAMIC_LATENCY: pa_source_flags_t = 1 << 6;
    pub const PA_SOURCE_FLAT_VOLUME:     pa_source_flags_t = 1 << 7;
}

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_source_state_t {
    Invalid   = -1,
    Running   = 0,
    Idle      = 1,
    Suspended = 2,
}

pub const PA_SOURCE_INVALID_STATE: pa_source_state_t = pa_source_state_t::Invalid;
pub const PA_SOURCE_RUNNING:       pa_source_state_t = pa_source_state_t::Running;
pub const PA_SOURCE_IDLE:          pa_source_state_t = pa_source_state_t::Idle;
pub const PA_SOURCE_SUSPENDED:     pa_source_state_t = pa_source_state_t::Suspended;

#[inline(always)]
pub fn pa_source_is_opened(state: pa_source_state_t) -> bool {
    state == pa_source_state_t::Running || state == pa_source_state_t::Idle
}

#[inline(always)]
pub fn pa_source_is_running(state: pa_source_state_t) -> bool {
    state == pa_source_state_t::Running
}

/// Port availability.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_port_available_t {
    /// This port does not support jack detection.
    Unknown = 0,
    /// This port is not available, likely because the jack is not plugged in.
    No      = 1,
    /// This port is available, likely because the jack is plugged in.
    Yes     = 2,
}

pub const PA_PORT_AVAILABLE_UNKNOWN: pa_port_available_t = pa_port_available_t::Unknown;
pub const PA_PORT_AVAILABLE_NO:      pa_port_available_t = pa_port_available_t::No;
pub const PA_PORT_AVAILABLE_YES:     pa_port_available_t = pa_port_available_t::Yes;

/// Port type.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum pa_device_port_type_t {
    /// Unknown.
    Unknown    = 0,
    /// Auxillary.
    Aux        = 1,
    /// Speaker.
    Speaker    = 2,
    /// Headphones.
    Headphones = 3,
    /// Line.
    Line       = 4,
    /// Mic.
    Mic        = 5,
    /// Headset.
    Headset    = 6,
    /// Handset.
    Handset    = 7,
    /// Earpiece.
    Earpiece   = 8,
    /// SPDIF.
    SPDIF      = 9,
    /// HDMI.
    HDMI       = 10,
    /// TV.
    TV         = 11,
    /// Radio.
    Radio      = 12,
    /// Video.
    Video      = 13,
    /// USB.
    USB        = 14,
    /// Bluetooth.
    Bluetooth  = 15,
    /// Portable.
    Portable   = 16,
    /// Handsfree.
    Handsfree  = 17,
    /// Car.
    Car        = 18,
    /// HiFi.
    HiFi       = 19,
    /// Phone.
    Phone      = 20,
    /// Network.
    Network    = 21,
    /// Analog.
    Analog     = 22,
}

pub const PA_DEVICE_PORT_TYPE_UNKNOWN:    pa_device_port_type_t = pa_device_port_type_t::Unknown;
pub const PA_DEVICE_PORT_TYPE_AUX:        pa_device_port_type_t = pa_device_port_type_t::Aux;
pub const PA_DEVICE_PORT_TYPE_SPEAKER:    pa_device_port_type_t = pa_device_port_type_t::Speaker;
pub const PA_DEVICE_PORT_TYPE_HEADPHONES: pa_device_port_type_t = pa_device_port_type_t::Headphones;
pub const PA_DEVICE_PORT_TYPE_LINE:       pa_device_port_type_t = pa_device_port_type_t::Line;
pub const PA_DEVICE_PORT_TYPE_MIC:        pa_device_port_type_t = pa_device_port_type_t::Mic;
pub const PA_DEVICE_PORT_TYPE_HEADSET:    pa_device_port_type_t = pa_device_port_type_t::Headset;
pub const PA_DEVICE_PORT_TYPE_HANDSET:    pa_device_port_type_t = pa_device_port_type_t::Handset;
pub const PA_DEVICE_PORT_TYPE_EARPIECE:   pa_device_port_type_t = pa_device_port_type_t::Earpiece;
pub const PA_DEVICE_PORT_TYPE_SPDIF:      pa_device_port_type_t = pa_device_port_type_t::SPDIF;
pub const PA_DEVICE_PORT_TYPE_HDMI:       pa_device_port_type_t = pa_device_port_type_t::HDMI;
pub const PA_DEVICE_PORT_TYPE_TV:         pa_device_port_type_t = pa_device_port_type_t::TV;
pub const PA_DEVICE_PORT_TYPE_RADIO:      pa_device_port_type_t = pa_device_port_type_t::Radio;
pub const PA_DEVICE_PORT_TYPE_VIDEO:      pa_device_port_type_t = pa_device_port_type_t::Video;
pub const PA_DEVICE_PORT_TYPE_USB:        pa_device_port_type_t = pa_device_port_type_t::USB;
pub const PA_DEVICE_PORT_TYPE_BLUETOOTH:  pa_device_port_type_t = pa_device_port_type_t::Bluetooth;
pub const PA_DEVICE_PORT_TYPE_PORTABLE:   pa_device_port_type_t = pa_device_port_type_t::Portable;
pub const PA_DEVICE_PORT_TYPE_HANDSFREE:  pa_device_port_type_t = pa_device_port_type_t::Handsfree;
pub const PA_DEVICE_PORT_TYPE_CAR:        pa_device_port_type_t = pa_device_port_type_t::Car;
pub const PA_DEVICE_PORT_TYPE_HIFI:       pa_device_port_type_t = pa_device_port_type_t::HiFi;
pub const PA_DEVICE_PORT_TYPE_PHONE:      pa_device_port_type_t = pa_device_port_type_t::Phone;
pub const PA_DEVICE_PORT_TYPE_NETWORK:    pa_device_port_type_t = pa_device_port_type_t::Network;
pub const PA_DEVICE_PORT_TYPE_ANALOG:     pa_device_port_type_t = pa_device_port_type_t::Analog;
