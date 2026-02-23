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

//! Standard/minimal main loop implementation based on poll().

use std::os::raw::{c_ulong, c_void};
#[cfg(not(windows))]
use libc::pollfd;
#[cfg(windows)]
use winapi::um::winsock2::WSAPOLLFD as pollfd;
use crate::mainloop::api::pa_mainloop_api;

/// An opaque main loop object.
#[repr(C)] pub struct pa_mainloop { _private: [u8; 0] }

#[rustfmt::skip]
pub type pa_poll_func = Option<extern "C" fn(ufds: *mut pollfd, nfds: c_ulong, timeout: i32, userdata: *mut c_void) -> i32>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_mainloop_new() -> *mut pa_mainloop;
    pub fn pa_mainloop_free(m: *mut pa_mainloop);
    pub fn pa_mainloop_prepare(m: *mut pa_mainloop, timeout: i32) -> i32;
    pub fn pa_mainloop_poll(m: *mut pa_mainloop) -> i32;
    pub fn pa_mainloop_dispatch(m: *mut pa_mainloop) -> i32;
    pub fn pa_mainloop_get_retval(m: *const pa_mainloop) -> i32;
    pub fn pa_mainloop_iterate(m: *mut pa_mainloop, block: i32, retval: *mut i32) -> i32;
    pub fn pa_mainloop_run(m: *mut pa_mainloop, retval: *mut i32) -> i32;
    pub fn pa_mainloop_get_api(m: *const pa_mainloop) -> *const pa_mainloop_api;
    pub fn pa_mainloop_quit(m: *mut pa_mainloop, retval: i32);
    pub fn pa_mainloop_wakeup(m: *mut pa_mainloop);

    pub fn pa_mainloop_set_poll_func(m: *mut pa_mainloop, poll_func: pa_poll_func, userdata: *mut c_void);
}
