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

//! Routines for controlling module-device-manager.

use std::os::raw::{c_char, c_void};
use super::{pa_context, pa_context_success_cb_t};
use crate::operation::pa_operation;

#[repr(C)]
pub struct pa_ext_device_manager_role_priority_info {
    pub role: *const c_char,
    pub priority: u32,
}

#[repr(C)]
pub struct pa_ext_device_manager_info {
    pub name: *const c_char,
    pub description: *const c_char,
    pub icon: *const c_char,
    pub index: u32,
    pub n_role_priorities: u32,
    pub role_priorities: *mut pa_ext_device_manager_role_priority_info,
}

#[rustfmt::skip]
pub type pa_ext_device_manager_test_cb_t = Option<extern "C" fn(c: *mut pa_context, version: u32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_ext_device_manager_read_cb_t = Option<extern "C" fn(c: *mut pa_context, info: *const pa_ext_device_manager_info, eol: i32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_ext_device_manager_subscribe_cb_t = Option<extern "C" fn(c: *mut pa_context, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_ext_device_manager_test(c: *mut pa_context, cb: pa_ext_device_manager_test_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_read(c: *mut pa_context, cb: pa_ext_device_manager_read_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_set_device_description(c: *mut pa_context, device: *const c_char, description: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_delete(c: *mut pa_context, s: *const *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_enable_role_device_priority_routing(c: *mut pa_context, enable: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_reorder_devices_for_role(c: *mut pa_context, role: *const c_char, devices: *const *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_subscribe(c: *mut pa_context, enable: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_ext_device_manager_set_subscribe_cb(c: *mut pa_context, cb: pa_ext_device_manager_subscribe_cb_t, userdata: *mut c_void);
}
