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

//! Asynchronous operations.

use std::os::raw::c_void;
use std::ptr::null_mut;
use crate::callbacks;

use capi::pa_operation as OperationInternal;
pub use capi::pa_operation_state_t as State;

/// An asynchronous operation object.
///
/// Note: Saves a copy of active multi-use closure callbacks, which it frees on drop.
pub struct Operation<ClosureProto: ?Sized> {
    /// The actual C object.
    ptr: *mut OperationInternal,
    /// The operation’s associated closure callback.
    /// This is a copy of the callback userdata pointer given in the C API function call that
    /// generated the operation instance (except not cast to void). It is saved here in case the
    /// user tries to cancel execution of the callback (with the `cancel` method), in which case we
    /// need this in order to release the memory.
    saved_cb: Option<*mut Box<ClosureProto>>,
    /// Saved multi-use state callback closure, for later destruction.
    state_cb: NotifyCb,
}

unsafe impl<ClosureProto: ?Sized> Send for Operation<ClosureProto> {}
unsafe impl<ClosureProto: ?Sized> Sync for Operation<ClosureProto> {}

type NotifyCb = callbacks::MultiUseCallback<dyn FnMut(),
    extern "C" fn(*mut OperationInternal, *mut c_void)>;

impl<ClosureProto: ?Sized> Operation<ClosureProto> {
    /// Creates a new `Operation` from an existing [`OperationInternal`] pointer.
    ///
    /// We also take a copy of the closure callback pointer, in order to free the memory on
    /// cancellation.
    pub(crate) fn from_raw(ptr: *mut OperationInternal, saved_cb: *mut Box<ClosureProto>) -> Self {
        assert!(!ptr.is_null());
        let saved_cb_actual = match saved_cb.is_null() {
            true => Some(saved_cb),
            false => None,
        };
        Self { ptr: ptr, saved_cb: saved_cb_actual, state_cb: Default::default() }
    }

    /// Cancels the operation.
    ///
    /// Beware! This will not necessarily cancel the execution of the operation on the server side.
    /// However it will make sure that the callback associated with this operation will not be
    /// called any more, effectively disabling the operation from the client side’s view.
    ///
    /// **Warning**, you should **never** attempt to use this to cancel a callback from within the
    /// execution of that callback itself. This should go without saying, since it makes absolutely
    /// no sense to try and do this, but be aware that this is not supported by the C API and
    /// **will** break things.
    pub fn cancel(&mut self) {
        unsafe { capi::pa_operation_cancel(self.ptr); }
        // Release the memory allocated for the closure.
        // Note, we `take()` here to help avoid issues if this function is mistakenly called more
        // than once.
        let callback = self.saved_cb.take();
        if let Some(ptr) = callback {
            if !ptr.is_null() {
                drop(unsafe { Box::from_raw(ptr as *mut Box<ClosureProto>) });
            }
        }
    }

    /// Gets the current status of the operation.
    #[inline]
    pub fn get_state(&self) -> State {
        unsafe { capi::pa_operation_get_state(self.ptr) }
    }

    /// Sets the callback function that is called when the operation state changes.
    ///
    /// Usually this is not necessary, since the functions that create `Operation` objects already
    /// take a callback that is called when the operation finishes. Registering a state change
    /// callback is mainly useful, if you want to get called back also if the operation gets
    /// cancelled.
    pub fn set_state_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.state_cb;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_operation_set_state_callback(self.ptr, cb_fn, cb_data); }
    }
}

impl<ClosureProto: ?Sized> Drop for Operation<ClosureProto> {
    fn drop(&mut self) {
        // Note, we deliberately do not destroy the `saved_cb` closure here. That should only be
        // destroyed either separately by a callback proxy, or by the `Operation`’s `cancel` method.
        unsafe { capi::pa_operation_unref(self.ptr) };
        self.ptr = null_mut::<OperationInternal>();
    }
}

/// Proxy for notification callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn notify_cb_proxy(_: *mut OperationInternal, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        let callback = NotifyCb::get_callback(userdata);
        (callback)();
    });
}
