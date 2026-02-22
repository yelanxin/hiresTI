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

//! Utility functions for direction.

#[cfg(any(doc, feature = "pa_v6"))]
use std::os::raw::c_char;

/// Direction bitfield.
///
/// While we currently do not expose anything bidirectional, one should test against the bit instead
/// of the value because we might add bidirectional stuff in the future.
pub type pa_direction_t = i32;

pub const PA_DIRECTION_OUTPUT: pa_direction_t = 0x1;
pub const PA_DIRECTION_INPUT:  pa_direction_t = 0x2;

#[link(name = "pulse")]
extern "C" {
    #[cfg(any(doc, feature = "pa_v6"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v6")))]
    pub fn pa_direction_valid(direction: pa_direction_t) -> i32;
    #[cfg(any(doc, feature = "pa_v6"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v6")))]
    pub fn pa_direction_to_string(direction: pa_direction_t) -> *const c_char;
}
