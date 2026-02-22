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

//! Assorted utility functions.

use std::ffi::CStr;

macro_rules! fn_string_with_buffer {
    ( $fn_call:ident, $l:ident ) => {{
        let mut tmp = Vec::with_capacity($l);
        unsafe {
            // Need to check NULL return here because `get_binary_name` function is not
            // supported on all architectures and so may return NULL, and might as well check
            // NULL return for other uses anyway.
            let ptr = capi::$fn_call(tmp.as_mut_ptr(), $l);
            match ptr.is_null() {
                true => None,
                false => Some(CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()),
            }
        }
    }};
}

/// Gets the current username.
///
/// Returns `None` on failure.
pub fn get_user_name(l: usize) -> Option<String> {
    fn_string_with_buffer!(pa_get_user_name, l)
}

/// Gets the current hostname.
///
/// Returns `None` on failure.
pub fn get_host_name(l: usize) -> Option<String> {
    fn_string_with_buffer!(pa_get_host_name, l)
}

/// Gets the fully qualified domain name.
///
/// Returns `None` on failure.
pub fn get_fqdn(l: usize) -> Option<String> {
    fn_string_with_buffer!(pa_get_fqdn, l)
}

/// Gets the home directory of the current user.
///
/// Returns `None` on failure.
pub fn get_home_dir(l: usize) -> Option<String> {
    fn_string_with_buffer!(pa_get_home_dir, l)
}

/// Gets the binary file name of the current process.
///
/// Returns `None` on failure.
/// This is not supported on all architectures (in which case `NULL` is returned).
pub fn get_binary_name(l: usize) -> Option<String> {
    fn_string_with_buffer!(pa_get_binary_name, l)
}

/// Makes the calling thread realtime if we can.
///
/// On Linux, this uses RealTimeKit if available and POSIX APIs otherwise (the latter applies to
/// other UNIX variants as well). This is also implemented for macOS and Windows.
#[cfg(any(doc, feature = "pa_v13"))]
#[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
pub fn make_thread_realtime(rtprio: i32) -> Result<(), ()> {
    match unsafe { capi::pa_thread_make_realtime(rtprio) } {
        0 => Ok(()),
        _ => Err(()),
    }
}
