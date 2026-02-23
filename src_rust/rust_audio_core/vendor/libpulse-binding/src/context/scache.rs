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

//! Sample cache mechanism.
//!
//! # Overview
//!
//! The sample cache provides a simple way of overcoming high network latencies and reducing
//! bandwidth. Instead of streaming a sound precisely when it should be played, it is stored on the
//! server and only the command to start playing it needs to be sent.
//!
//! # Creation
//!
//! To create a sample, the normal stream API is used (see [`stream`]). The function
//! [`Stream::connect_upload()`] will make sure the stream is stored as a sample on the server.
//!
//! To complete the upload, [`Stream::finish_upload()`] is called and the sample will receive the
//! same name as the stream. If the upload should be aborted, simply call [`Stream::disconnect()`].
//!
//! # Playing samples
//!
//! To play back a sample, simply call [`Context::play_sample()`]:
//!
//! ```rust,ignore
//! extern crate libpulse_binding as pulse;
//!
//! use pulse::volume;
//!
//! //...
//!
//! let o = my_context.play_sample(
//!     "sample2",            // Name of my sample
//!     None,                 // Use default sink
//!     volume::VOLUME_NORM,  // Full volume
//!     None                  // Don’t need a callback
//! );
//! ```
//!
//! # Removing samples
//!
//! When a sample is no longer needed, it should be removed on the server to save resources. The
//! sample is deleted using [`Context::remove_sample()`].
//!
//! [`stream`]: mod@crate::stream
//! [`Stream::connect_upload()`]: crate::stream::Stream::connect_upload
//! [`Stream::finish_upload()`]: crate::stream::Stream::finish_upload
//! [`Stream::disconnect()`]: crate::stream::Stream::disconnect

use std::os::raw::{c_char, c_void};
use std::ffi::CString;
use std::ptr::null;
use super::{ContextInternal, Context};
use crate::def;
use crate::callbacks::{box_closure_get_capi_ptr, get_su_capi_params, get_su_callback};
use crate::{operation::Operation, volume::Volume, proplist::Proplist};

impl Context {
    /// Removes a sample from the sample cache.
    ///
    /// Returns an operation object which may be used to cancel the operation while it is running.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn remove_sample<F>(&mut self, name: &str, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_remove_sample(self.ptr, c_name.as_ptr(),
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Plays a sample from the sample cache to the specified device.
    ///
    /// If the specified device is `None` use the default sink.
    ///
    /// # Params
    ///
    /// * `name`: Name of the sample to play.
    /// * `dev`: Sink to play this sample on, or `None` for default.
    /// * `volume`: Volume to play this sample with, or `None` to leave the decision about the
    ///   volume to the server side which is a good idea. [`Volume::INVALID`] has the same meaning
    ///   as `None.
    /// * `callback`: Optional success callback. It must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn play_sample(&mut self, name: &str, dev: Option<&str>, volume: Option<Volume>,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_dev = match dev {
            Some(dev) => CString::new(dev).unwrap(),
            None => CString::new("").unwrap(),
        };

        let p_dev = dev.map_or(null::<c_char>(), |_| c_dev.as_ptr() as *const c_char);
        let vol = volume.unwrap_or(Volume::INVALID);

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe {
            capi::pa_context_play_sample(self.ptr, c_name.as_ptr(), p_dev, vol.0, cb_fn, cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Plays a sample from the sample cache to the specified device, allowing specification of a
    /// property list for the playback stream.
    ///
    /// If the device is `None` use the default sink.
    ///
    /// # Params
    ///
    /// * `name`: Name of the sample to play.
    /// * `dev`: Sink to play this sample on, or `None` for default.
    /// * `volume`: Volume to play this sample with, or `None` to leave the decision about the
    ///   volume to the server side which is a good idea. [`Volume::INVALID`] has the same meaning
    ///   as `None.
    /// * `proplist`: Property list for this sound. The property list of the cached entry will have
    ///   this merged into it.
    /// * `callback`: Optional success callback. It must accept an `u32` index value wrapper in a
    ///   `Result`. The index is the index of the sink input object. `Err` is given instead on
    ///   failure.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn play_sample_with_proplist(&mut self, name: &str, dev: Option<&str>,
        volume: Option<Volume>, proplist: &Proplist,
        callback: Option<Box<dyn FnMut(Result<u32, ()>) + 'static>>)
        -> Operation<dyn FnMut(Result<u32, ()>)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a
        // variable, leading to as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_dev = match dev {
            Some(dev) => CString::new(dev).unwrap(),
            None => CString::new("").unwrap(),
        };

        let p_dev = dev.map_or(null::<c_char>(), |_| c_dev.as_ptr() as *const c_char);
        let vol = volume.unwrap_or(Volume::INVALID);

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, play_sample_success_cb_proxy);
        let ptr = unsafe {
            capi::pa_context_play_sample_with_proplist(self.ptr, c_name.as_ptr(), p_dev, vol.0,
                proplist.0.ptr, cb_fn, cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(Result<u32, ()>)>)
    }
}

/// Proxy for completion success callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn play_sample_success_cb_proxy(_: *mut ContextInternal, index: u32, userdata: *mut c_void) {
    let index_actual = match index { def::INVALID_INDEX => Err(()), i => Ok(i) };
    let _ = std::panic::catch_unwind(|| {
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(Result<u32, ()>)>(userdata);
        (callback)(index_actual);
    });
}
