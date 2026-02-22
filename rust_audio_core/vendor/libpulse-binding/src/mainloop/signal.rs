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

//! UNIX signal support for main loops.
//!
//! # Overview
//!
//! In contrast to other main loop event sources such as timer and IO events, UNIX signal support
//! requires modification of the global process environment. Due to this the generic main loop
//! abstraction layer as defined in [`mainloop::api`](mod@crate::mainloop::api) doesn’t have direct
//! support for UNIX signals. However, you may hook signal support into an abstract main loop via
//! the routines defined herein.

use std::os::raw::c_void;
use std::ptr::null_mut;
use capi::pa_signal_event as EventInternal;
use crate::error::PAErr;
use crate::callbacks::MultiUseCallback;
use crate::mainloop::api::{ApiInternal, MainloopInnerType, Mainloop as MainloopTrait};

/// An opaque UNIX signal event source object.
///
/// Note: Saves a copy of the closure callbacks, which it frees on drop.
pub struct Event {
    /// The actual C object.
    ptr: *mut EventInternal,
    /// Saved multi-use state callback closure, for later destruction.
    _signal_cb: SignalCb,
}

type SignalCb = MultiUseCallback<dyn FnMut(i32), extern "C" fn(*const ApiInternal,
    *mut EventInternal, i32, *mut c_void)>;

/// Trait with signal handling, for mainloops.
pub trait MainloopSignals : MainloopTrait {
    /// Initializes the UNIX signal subsystem and bind it to the specified main loop.
    fn init_signals(&mut self) -> Result<(), PAErr> {
        let inner = self.inner();
        let api = inner.get_api();
        match unsafe { capi::pa_signal_init(api.into()) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Cleans up the signal subsystem.
    #[inline]
    fn signals_done(&self) {
        unsafe { capi::pa_signal_done(); }
    }
}

impl Event {
    /// Creates a new UNIX signal event source object.
    ///
    /// The callback must accept an integer which represents the signal.
    pub fn new<F>(sig: i32, callback: F) -> Self
        where F: FnMut(i32) + 'static
    {
        let saved = SignalCb::new(Some(Box::new(callback)));
        let (cb_fn, cb_data) = saved.get_capi_params(signal_cb_proxy);
        let ptr = unsafe { capi::pa_signal_new(sig, cb_fn, cb_data) };
        Self { ptr: ptr, _signal_cb: saved }
    }
}

impl Drop for Event {
    fn drop(&mut self) {
        unsafe { capi::pa_signal_free(self.ptr) };
        self.ptr = null_mut::<EventInternal>();
    }
}

/// Proxy for signal callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn signal_cb_proxy(_api: *const ApiInternal, _e: *mut EventInternal, sig: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        let callback = SignalCb::get_callback(userdata);
        (callback)(sig);
    });
}
