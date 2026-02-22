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

//! Sample cache mechanism.

use std::os::raw::{c_char, c_void};
use crate::{operation::pa_operation, proplist::pa_proplist, volume::pa_volume_t};

#[rustfmt::skip]
pub type pa_context_play_sample_cb_t = Option<extern "C" fn(c: *mut super::pa_context, idx: u32, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_context_remove_sample(c: *mut super::pa_context, name: *const c_char, cb: super::pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_play_sample(c: *mut super::pa_context, name: *const c_char, dev: *const c_char, volume: pa_volume_t, cb: super::pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_play_sample_with_proplist(c: *mut super::pa_context, name: *const c_char, dev: *const c_char, volume: pa_volume_t, proplist: *const pa_proplist, cb: pa_context_play_sample_cb_t, userdata: *mut c_void) -> *mut pa_operation;
}
