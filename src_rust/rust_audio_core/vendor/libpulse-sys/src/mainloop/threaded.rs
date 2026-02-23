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

//! A variation of the standard main loop implementation, using a background thread.

use std::os::raw::c_char;
#[cfg(any(doc, feature = "pa_v13"))]
use std::os::raw::c_void;
use crate::mainloop::api::pa_mainloop_api;

/// An opaque threaded main loop object.
#[repr(C)] pub struct pa_threaded_mainloop { _private: [u8; 0] }

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_threaded_mainloop_new() -> *mut pa_threaded_mainloop;
    pub fn pa_threaded_mainloop_free(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_start(m: *mut pa_threaded_mainloop) -> i32;
    pub fn pa_threaded_mainloop_stop(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_lock(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_unlock(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_wait(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_signal(m: *mut pa_threaded_mainloop, wait_for_accept: i32);
    pub fn pa_threaded_mainloop_accept(m: *mut pa_threaded_mainloop);
    pub fn pa_threaded_mainloop_get_retval(m: *const pa_threaded_mainloop) -> i32;
    pub fn pa_threaded_mainloop_get_api(m: *const pa_threaded_mainloop) -> *const pa_mainloop_api;
    pub fn pa_threaded_mainloop_in_thread(m: *mut pa_threaded_mainloop) -> i32;
    pub fn pa_threaded_mainloop_set_name(m: *mut pa_threaded_mainloop, name: *const c_char);
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn pa_threaded_mainloop_once_unlocked(m: *mut pa_threaded_mainloop, callback: extern "C" fn(m: *mut pa_threaded_mainloop, userdata: *mut c_void), userdata: *mut c_void);
}
