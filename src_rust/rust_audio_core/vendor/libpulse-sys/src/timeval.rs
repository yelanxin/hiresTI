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

//! Utility functions for handling timeval calculations.

pub(crate) use libc::timeval;
use crate::sample::pa_usec_t;

pub const PA_MSEC_PER_SEC: pa_usec_t = 1000;
pub const PA_USEC_PER_SEC: pa_usec_t = 1_000_000;
pub const PA_NSEC_PER_SEC: u64 = 1_000_000_000;
pub const PA_USEC_PER_MSEC: pa_usec_t = 1000;
pub const PA_NSEC_PER_MSEC: u64 = 1_000_000;
pub const PA_NSEC_PER_USEC: u64 = 1000;

pub const PA_USEC_INVALID: pa_usec_t = std::u64::MAX;

pub const PA_USEC_MAX: pa_usec_t = std::u64::MAX - 1;

#[link(name = "pulse")]
extern "C" {
    pub fn pa_gettimeofday(tv: *mut timeval) -> *mut timeval;
    pub fn pa_timeval_diff(a: *const timeval, b: *const timeval) -> pa_usec_t;
    pub fn pa_timeval_cmp(a: *const timeval, b: *const timeval) -> i32;
    pub fn pa_timeval_age(tv: *const timeval) -> pa_usec_t;
    pub fn pa_timeval_add(tv: *mut timeval, v: pa_usec_t) -> *mut timeval;
    pub fn pa_timeval_sub(tv: *mut timeval, v: pa_usec_t) -> *mut timeval;
    pub fn pa_timeval_store(tv: *mut timeval, v: pa_usec_t) -> *mut timeval;
    pub fn pa_timeval_load(tv: *const timeval) -> pa_usec_t;
}
