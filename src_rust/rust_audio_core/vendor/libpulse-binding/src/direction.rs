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

//! Utilities for direction.

#[cfg(any(doc, feature = "pa_v6"))]
use std::ffi::CStr;
use bitflags::bitflags;

bitflags! {
    /// Flag set.
    #[derive(Debug, Copy, Clone, PartialEq, Eq)]
    #[repr(transparent)]
    pub struct FlagSet: i32 {
        /// Output flag.
        const OUTPUT = capi::PA_DIRECTION_OUTPUT;
        /// Input flag.
        const INPUT = capi::PA_DIRECTION_INPUT;
    }
}

impl FlagSet {
    /// Checks whether direction is valid (either input, output or bidirectional).
    #[inline]
    #[cfg(any(doc, feature = "pa_v6"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v6")))]
    pub fn is_valid(self) -> bool {
        unsafe { capi::pa_direction_valid(self.bits()) != 0 }
    }

    /// Gets a textual representation of the direction.
    #[inline]
    #[cfg(any(doc, feature = "pa_v6"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v6")))]
    pub fn to_string(self) -> String {
        unsafe {
            CStr::from_ptr(capi::pa_direction_to_string(self.bits())).to_string_lossy().into_owned()
        }
    }
}
