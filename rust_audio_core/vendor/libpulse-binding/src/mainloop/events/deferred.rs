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

//! Main loop deferred events.

use std::os::raw::c_void;
use std::rc::Rc;
use crate::mainloop::api::{MainloopApi, MainloopInnerType};
use crate::callbacks::MultiUseCallback;

pub use capi::pa_defer_event as DeferEventInternal;

/// A deferred event source.
pub struct DeferEvent<T>
    where T: MainloopInnerType
{
    /// Internal object pointer
    ptr: *mut DeferEventInternal,
    /// Source mainloop.
    owner: Rc<T>,
    /// Saved callback closure, for later destruction.
    _saved_cb: EventCb,
}

/// A reference to a deferred event source, provided to the callback, allowing modification within
/// the callback itself.
pub struct DeferEventRef<T: 'static>
    where T: MainloopInnerType
{
    /// Internal object pointer
    ptr: *mut DeferEventInternal,
    /// Source mainloop.
    owner: Rc<T>,
}

pub(crate) type EventCb = MultiUseCallback<dyn FnMut(*mut DeferEventInternal),
    extern "C" fn(a: *const MainloopApi, e: *mut DeferEventInternal, userdata: *mut c_void)>;

impl<T> DeferEvent<T>
    where T: MainloopInnerType
{
    #[inline]
    pub(crate) fn from_raw(ptr: *mut DeferEventInternal, mainloop_inner: Rc<T>, callback: EventCb)
        -> Self
    {
        assert_eq!(false, ptr.is_null());
        Self { ptr: ptr, owner: mainloop_inner, _saved_cb: callback }
    }

    /// Enables this event source temporarily.
    #[inline]
    pub fn enable(&mut self) {
        let fn_ptr = (*self.owner).get_api().defer_enable.unwrap();
        fn_ptr(self.ptr, 1);
    }

    /// Disables this event source temporarily.
    #[inline]
    pub fn disable(&mut self) {
        let fn_ptr = (*self.owner).get_api().defer_enable.unwrap();
        fn_ptr(self.ptr, 0);
    }
}

impl<T> DeferEventRef<T>
    where T: MainloopInnerType
{
    #[inline]
    pub(crate) fn from_raw(ptr: *mut DeferEventInternal, mainloop_inner: Rc<T>) -> Self {
        assert_eq!(false, ptr.is_null());
        Self { ptr: ptr, owner: mainloop_inner }
    }

    /// Enables this event source temporarily.
    #[inline]
    pub fn enable(&mut self) {
        let fn_ptr = (*self.owner).get_api().defer_enable.unwrap();
        fn_ptr(self.ptr, 1);
    }

    /// Disables this event source temporarily.
    #[inline]
    pub fn disable(&mut self) {
        let fn_ptr = (*self.owner).get_api().defer_enable.unwrap();
        fn_ptr(self.ptr, 0);
    }
}

impl<T> Drop for DeferEvent<T>
    where T: MainloopInnerType
{
    fn drop(&mut self) {
        let fn_ptr = (*self.owner).get_api().defer_free.unwrap();
        fn_ptr(self.ptr);
    }
}

/// Proxy for the event callback.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
pub(crate)
extern "C"
fn event_cb_proxy(_: *const MainloopApi, e: *mut DeferEventInternal, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        let callback = EventCb::get_callback(userdata);
        (callback)(e);
    });
}
