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

//! Main loop abstraction layer API.

use std::os::raw::c_void;
use crate::timeval::timeval;

pub type pa_io_event_flags_t = u32;

pub use self::io_event_flags::*;

pub mod io_event_flags {
    use super::pa_io_event_flags_t;

    pub const PA_IO_EVENT_NULL:   pa_io_event_flags_t = 0;
    pub const PA_IO_EVENT_INPUT:  pa_io_event_flags_t = 1;
    pub const PA_IO_EVENT_OUTPUT: pa_io_event_flags_t = 2;
    pub const PA_IO_EVENT_HANGUP: pa_io_event_flags_t = 4;
    pub const PA_IO_EVENT_ERROR:  pa_io_event_flags_t = 8;
}

/// An opaque IO event source object.
#[repr(C)] pub struct pa_io_event { _private: [u8; 0] }
#[rustfmt::skip]
pub type pa_io_event_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_io_event, fd: i32, events: pa_io_event_flags_t, userdata: *mut c_void)>;
#[rustfmt::skip]
pub type pa_io_event_destroy_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_io_event, userdata: *mut c_void)>;

/// An opaque timer event source object.
#[repr(C)] pub struct pa_time_event { _private: [u8; 0] }
#[rustfmt::skip]
pub type pa_time_event_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_time_event, tv: *const timeval, userdata: *mut c_void)>;
#[rustfmt::skip]
pub type pa_time_event_destroy_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_time_event, userdata: *mut c_void)>;

/// An opaque deferred event source object.
///
/// Events of this type are triggered once in every main loop iteration.
#[repr(C)] pub struct pa_defer_event { _private: [u8; 0] }
#[rustfmt::skip]
pub type pa_defer_event_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_defer_event, userdata: *mut c_void)>;
#[rustfmt::skip]
pub type pa_defer_event_destroy_cb_t = Option<extern "C" fn(a: *const pa_mainloop_api, e: *mut pa_defer_event, userdata: *mut c_void)>;

#[rustfmt::skip]
#[repr(C)]
pub struct pa_mainloop_api {
    pub userdata: *mut c_void,

    pub io_new: Option<extern "C" fn(a: *const pa_mainloop_api, fd: i32, events: pa_io_event_flags_t, cb: pa_io_event_cb_t, userdata: *mut c_void) -> *mut pa_io_event>,
    pub io_enable: Option<extern "C" fn(e: *mut pa_io_event, events: pa_io_event_flags_t)>,
    pub io_free: Option<extern "C" fn(e: *mut pa_io_event)>,
    pub io_set_destroy: Option<extern "C" fn(e: *mut pa_io_event, cb: pa_io_event_destroy_cb_t)>,

    pub time_new: Option<extern "C" fn(a: *const pa_mainloop_api, tv: *const timeval, cb: pa_time_event_cb_t, userdata: *mut c_void) -> *mut pa_time_event>,
    pub time_restart: Option<extern "C" fn(e: *mut pa_time_event, tv: *const timeval)>,
    pub time_free: Option<extern "C" fn(e: *mut pa_time_event)>,
    pub time_set_destroy: Option<extern "C" fn(e: *mut pa_time_event, cb: pa_time_event_destroy_cb_t)>,

    pub defer_new: Option<extern "C" fn(a: *const pa_mainloop_api, cb: pa_defer_event_cb_t, userdata: *mut c_void) -> *mut pa_defer_event>,
    pub defer_enable: Option<extern "C" fn(e: *mut pa_defer_event, b: i32)>,
    pub defer_free: Option<extern "C" fn(e: *mut pa_defer_event)>,
    pub defer_set_destroy: Option<extern "C" fn(e: *mut pa_defer_event, cb: pa_defer_event_destroy_cb_t)>,

    pub quit: Option<extern "C" fn(a: *const pa_mainloop_api, retval: i32)>,
}

#[rustfmt::skip]
pub type pa_mainloop_api_once_cb = Option<extern "C" fn(m: *const pa_mainloop_api, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_mainloop_api_once(m: *const pa_mainloop_api, callback: pa_mainloop_api_once_cb, userdata: *mut c_void);
}
