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

//! UNIX signal support for main loops.

use std::os::raw::c_void;
use crate::mainloop::api::pa_mainloop_api;

/// An opaque UNIX signal event source object.
#[repr(C)] pub struct pa_signal_event { _private: [u8; 0] }

#[rustfmt::skip]
pub type pa_signal_cb_t = Option<extern "C" fn(api: *const pa_mainloop_api, e: *mut pa_signal_event, sig: i32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_signal_destroy_cb_t = Option<extern "C" fn(api: *const pa_mainloop_api, e: *mut pa_signal_event, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_signal_init(api: *const pa_mainloop_api) -> i32;
    pub fn pa_signal_done();
    pub fn pa_signal_new(sig: i32, callback: pa_signal_cb_t, userdata: *mut c_void) -> *mut pa_signal_event;
    pub fn pa_signal_free(e: *mut pa_signal_event);
    pub fn pa_signal_set_destroy(e: *mut pa_signal_event, callback: pa_signal_destroy_cb_t);
}
