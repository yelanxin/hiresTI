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

//! Routines for controlling module-device-restore.

use std::os::raw::c_void;
use std::ptr::null_mut;
use std::mem;
use capi::pa_ext_device_restore_info as InfoInternal;
use super::{ContextInternal, Context};
use crate::{def, format};
use crate::callbacks::{
    ListResult, box_closure_get_capi_ptr, callback_for_list_instance, MultiUseCallback
};
use crate::operation::Operation;

/// Stores information about one device in the device database that is maintained by
/// module-device-manager.
#[derive(Debug)]
pub struct Info {
    /// Device type sink or source?
    pub dtype: def::Device,
    /// The device index.
    pub index: u32,
    /// A set of formats.
    pub formats: Vec<format::Info>,
}

impl Info {
    fn new_from_raw(p: *const InfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { p.as_ref().unwrap() };

        let mut formats_vec = Vec::with_capacity(src.n_formats as usize);
        assert!(src.n_formats == 0 || !src.formats.is_null());
        for i in 0..src.n_formats as isize {
            let indexed_ptr = unsafe { (*src.formats.offset(i)) as *mut format::InfoInternal };
            if !indexed_ptr.is_null() {
                formats_vec.push(format::Info::from_raw_weak(indexed_ptr));
            }
        }

        Info { dtype: src.dtype, index: src.index, formats: formats_vec }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> Self {
        Info {
            formats: self.formats.iter().map(format::Info::to_owned).collect(),
            ..*self
        }
    }
}

/// A wrapper object providing device restore routines to a context.
///
/// Note: Saves a copy of active multi-use closure callbacks, which it frees on drop.
pub struct DeviceRestore {
    context: *mut ContextInternal,
    /// Multi-use callback closure pointers
    cb_ptrs: CallbackPointers,
}

unsafe impl Send for DeviceRestore {}
unsafe impl Sync for DeviceRestore {}

/// Holds copies of callback closure pointers, for those that are “multi-use” (may be fired multiple
/// times), for freeing at the appropriate time.
#[derive(Default)]
struct CallbackPointers {
    subscribe: SubscribeCb,
}

type SubscribeCb = MultiUseCallback<dyn FnMut(def::Device, u32),
    extern "C" fn(*mut ContextInternal, def::Device, u32, *mut c_void)>;

impl Context {
    /// Gets a device restore object linked to the current context, giving access to device restore
    /// routines.
    ///
    /// See [`context::ext_device_restore`](mod@crate::context::ext_device_restore).
    pub fn device_restore(&self) -> DeviceRestore {
        unsafe { capi::pa_context_ref(self.ptr) };
        DeviceRestore::from_raw(self.ptr)
    }
}

impl DeviceRestore {
    /// Creates a new `DeviceRestore` from an existing [`ContextInternal`] pointer.
    fn from_raw(context: *mut ContextInternal) -> Self {
        Self { context: context, cb_ptrs: Default::default() }
    }

    /// Tests if this extension module is available in the server.
    ///
    /// The callback must accept an integer, which indicates version.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn test<F>(&mut self, callback: F) -> Operation<dyn FnMut(u32)>
        where F: FnMut(u32) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(u32)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_restore_test(self.context,
            Some(super::ext_test_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(u32)>)
    }

    /// Subscribes to changes in the device database.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn subscribe<F>(&mut self, enable: bool, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_restore_subscribe(self.context, enable as i32,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the subscription callback that is called when [`subscribe()`](Self::subscribe) was
    /// called.
    ///
    /// The callback must accept two parameters, firstly a [`Device`] variant, and secondly an
    /// integer index.
    ///
    /// [`Device`]: crate::def::Device
    pub fn set_subscribe_cb<F>(&mut self, callback: F)
        where F: FnMut(def::Device, u32) + 'static
    {
        let saved = &mut self.cb_ptrs.subscribe;
        *saved = SubscribeCb::new(Some(Box::new(callback)));
        let (cb_fn, cb_data) = saved.get_capi_params(ext_subscribe_cb_proxy);
        unsafe { capi::pa_ext_device_restore_set_subscribe_cb(self.context, cb_fn, cb_data); }
    }

    /// Reads the formats for all present devices from the device database.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn read_formats_all<F>(&mut self, callback: F) -> Operation<dyn FnMut(ListResult<&Info>)>
        where F: FnMut(ListResult<&Info>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&Info>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_restore_read_formats_all(self.context,
            Some(read_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&Info>)>)
    }

    /// Reads an entry from the device database.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn read_formats<F>(&mut self, type_: def::Device, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&Info>)>
        where F: FnMut(ListResult<&Info>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&Info>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_restore_read_formats(self.context, type_, index,
            Some(read_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&Info>)>)
    }

    /// Reads an entry from the device database.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn save_formats<F>(&mut self, type_: def::Device, index: u32,
        formats: &mut [&mut format::Info], callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Capture array of pointers to the above `format::InfoInternal` objects
        let mut format_ptrs: Vec<*mut capi::pa_format_info> = Vec::with_capacity(formats.len());
        for format in formats {
            format_ptrs.push(unsafe { mem::transmute(&format.ptr) });
        }

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe {
            capi::pa_ext_device_restore_save_formats(self.context, type_, index,
                format_ptrs.len() as u8, format_ptrs.as_ptr(), Some(super::success_cb_proxy),
                cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

impl Drop for DeviceRestore {
    fn drop(&mut self) {
        unsafe { capi::pa_context_unref(self.context) };
        self.context = null_mut::<ContextInternal>();
    }
}

/// Proxy for the extension subscribe callback.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn ext_subscribe_cb_proxy(_: *mut ContextInternal, type_: def::Device, index: u32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        let callback = SubscribeCb::get_callback(userdata);
        (callback)(type_, index);
    });
}

/// Proxy for read list callbacks.
///
/// Warning: This is for list cases only! On EOL or error it destroys the actual closure callback.
extern "C"
fn read_list_cb_proxy(_: *mut ContextInternal, i: *const InfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, Info::new_from_raw);
    });
}
