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

//! Assorted utility functions.

use std::os::raw::{c_char, c_ulong};

#[link(name = "pulse")]
extern "C" {
    pub fn pa_get_user_name(s: *mut c_char, l: usize) -> *mut c_char;
    pub fn pa_get_host_name(s: *mut c_char, l: usize) -> *mut c_char;
    pub fn pa_get_fqdn(s: *mut c_char, l: usize) -> *mut c_char;
    pub fn pa_get_home_dir(s: *mut c_char, l: usize) -> *mut c_char;
    pub fn pa_get_binary_name(s: *mut c_char, l: usize) -> *mut c_char;
    pub fn pa_path_get_filename(p: *const c_char) -> *mut c_char;
    pub fn pa_msleep(t: c_ulong) -> i32;
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn pa_thread_make_realtime(rtprio: i32) -> i32;
}
