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

//! Routines for controlling module-stream-restore.

use std::os::raw::{c_char, c_void};
use super::{pa_context, pa_context_success_cb_t};
use crate::{operation::pa_operation, proplist::pa_update_mode_t};
use crate::{volume::pa_cvolume, channelmap::pa_channel_map};

#[repr(C)]
pub struct pa_ext_stream_restore_info {
    pub name: *const c_char,
    pub channel_map: pa_channel_map,
    pub volume: pa_cvolume,
    pub device: *const c_char,
    pub mute: i32,
}

#[rustfmt::skip]
pub type pa_ext_stream_restore_test_cb_t = Option<extern "C" fn(c: *mut pa_context, version: u32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_ext_stream_restore_read_cb_t = Option<extern "C" fn(c: *mut pa_context, info: *const pa_ext_stream_restore_info, eol: i32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_ext_stream_restore_subscribe_cb_t = Option<extern "C" fn(c: *mut pa_context, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_ext_stream_restore_test(c: *mut pa_context, cb: pa_ext_stream_restore_test_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_stream_restore_read(c: *mut pa_context, cb: pa_ext_stream_restore_read_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_stream_restore_write(c: *mut pa_context, mode: pa_update_mode_t, data: *const *const pa_ext_stream_restore_info, n: u32, apply_immediately: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_stream_restore_delete(c: *mut pa_context, s: *const *const c_char, b: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_stream_restore_subscribe(c: *mut pa_context, enable: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_stream_restore_set_subscribe_cb(c: *mut pa_context, cb: pa_ext_stream_restore_subscribe_cb_t, userdata: *mut c_void);
}
