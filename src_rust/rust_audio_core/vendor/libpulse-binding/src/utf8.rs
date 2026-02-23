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

//! UTF-8 validation functions.
//!
//! Bindings are not provided here for most of the PulseAudio UTF-8 functions since Rust has built
//! in UTF-8 handling and thus they should be entirely unnecessary.

use std::os::raw::{c_char, c_void};
use std::ffi::{CStr, CString};

/// Converts a UTF-8 string to the current locale.
pub fn utf8_to_locale(s: &str) -> Option<String> {
    // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
    // as_ptr() giving dangling pointers!
    let c_str = CString::new(s).unwrap();
    let tmp_ptr: *const c_char = unsafe { capi::pa_utf8_to_locale(c_str.as_ptr()) };
    if tmp_ptr.is_null() {
        return None;
    }
    unsafe {
        let ret = Some(CStr::from_ptr(tmp_ptr).to_string_lossy().into_owned());
        capi::pa_xfree(tmp_ptr as *mut c_void);
        ret
    }
}
