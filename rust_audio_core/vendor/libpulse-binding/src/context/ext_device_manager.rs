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

//! Routines for controlling module-device-manager.

use std::ffi::{CStr, CString};
use std::borrow::Cow;
use std::os::raw::{c_char, c_void};
use std::ptr::{null, null_mut};
use capi::pa_ext_device_manager_info as InfoInternal;
use capi::pa_ext_device_manager_role_priority_info as RolePriorityInfoInternal;
use super::{ContextInternal, Context};
use crate::def;
use crate::callbacks::{ListResult, box_closure_get_capi_ptr, callback_for_list_instance};
use crate::operation::Operation;

/// Role priority information.
#[derive(Debug)]
pub struct RolePriorityInfo<'a> {
    /// Role name
    pub role: Option<Cow<'a, str>>,
    /// Priority
    pub priority: u32,
}

impl RolePriorityInfo<'_> {
    fn new_from_raw(p: *const RolePriorityInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { p.as_ref().unwrap() };
        unsafe {
            RolePriorityInfo {
                role: match src.role.is_null() {
                    false => Some(CStr::from_ptr(src.role).to_string_lossy()),
                    true => None,
                },
                priority: src.priority,
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> RolePriorityInfo<'static> {
        RolePriorityInfo {
            role: self.role.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

/// Stores information about one device in the device database that is maintained by
/// module-device-manager.
#[derive(Debug)]
pub struct Info<'a> {
    /// Identifier string of the device. A string like “sink:” or similar followed by the name of
    /// the device.
    pub name: Option<Cow<'a, str>>,
    /// The description of the device when it was last seen, if applicable and saved.
    pub description: Option<Cow<'a, str>>,
    /// The icon given to the device.
    pub icon: Option<Cow<'a, str>>,
    /// The device index if it is currently available or `None` if invalid.
    pub index: Option<u32>,
    /// A set of role priority structures.
    pub role_priorities: Vec<RolePriorityInfo<'a>>,
}

impl Info<'_> {
    fn new_from_raw(p: *const InfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { p.as_ref().unwrap() };

        let mut rp_vec = Vec::with_capacity(src.n_role_priorities as usize);
        assert!(src.n_role_priorities == 0 || !src.role_priorities.is_null());
        for i in 0..src.n_role_priorities as isize {
            let indexed_ptr = unsafe { src.role_priorities.offset(i) as *mut RolePriorityInfoInternal };
            if !indexed_ptr.is_null() {
                rp_vec.push(RolePriorityInfo::new_from_raw(indexed_ptr));
            }
        }

        unsafe {
            Info {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                icon: match src.icon.is_null() {
                    false => Some(CStr::from_ptr(src.icon).to_string_lossy()),
                    true => None,
                },
                index: match src.index {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                role_priorities: rp_vec,
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> Info<'static> {
        Info {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            icon: self.icon.clone().map(|o| Cow::Owned(o.into_owned())),
            role_priorities: self.role_priorities.iter().map(RolePriorityInfo::to_owned).collect(),
            ..*self
        }
    }
}

/// A wrapper object providing device manager routines to a context.
///
/// Note: Saves a copy of active multi-use closure callbacks, which it frees on drop.
pub struct DeviceManager {
    context: *mut ContextInternal,
    /// Multi-use callback closure pointers
    cb_ptrs: CallbackPointers,
}

unsafe impl Send for DeviceManager {}
unsafe impl Sync for DeviceManager {}

/// Holds copies of callback closure pointers, for those that are “multi-use” (may be fired multiple
/// times), for freeing at the appropriate time.
#[derive(Default)]
struct CallbackPointers {
    subscribe: super::ExtSubscribeCb,
}

impl Context {
    /// Gets a device manager object linked to the current context, giving access to device manager
    /// routines.
    ///
    /// See [`context::ext_device_manager`](mod@crate::context::ext_device_manager).
    pub fn device_manager(&self) -> DeviceManager {
        unsafe { capi::pa_context_ref(self.ptr) };
        DeviceManager::from_raw(self.ptr)
    }
}

impl DeviceManager {
    /// Creates a new `DeviceManager` from an existing [`ContextInternal`] pointer.
    fn from_raw(context: *mut ContextInternal) -> Self {
        Self { context: context, cb_ptrs: Default::default() }
    }

    /// Tests if this extension module is available in the server.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn test<F>(&mut self, callback: F) -> Operation<dyn FnMut(u32)>
        where F: FnMut(u32) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(u32)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_manager_test(self.context,
            Some(super::ext_test_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(u32)>)
    }

    /// Reads all entries from the device database.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn read<F>(&mut self, callback: F) -> Operation<dyn FnMut(ListResult<&Info>)>
        where F: FnMut(ListResult<&Info>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&Info>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_manager_read(self.context, Some(read_list_cb_proxy),
            cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&Info>)>)
    }

    /// Sets the description for a device.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn set_device_description<F>(&mut self, device: &str, description: &str, callback: F)
        -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a
        // variable, leading to as_ptr() giving dangling pointers!
        let c_dev = CString::new(device).unwrap();
        let c_desc = CString::new(description).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe {
            capi::pa_ext_device_manager_set_device_description(self.context, c_dev.as_ptr(),
                c_desc.as_ptr(), Some(super::success_cb_proxy), cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Deletes entries from the device database.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn delete<F>(&mut self, devices: &[&str], callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let mut c_devs: Vec<CString> = Vec::with_capacity(devices.len());
        for device in devices {
            c_devs.push(CString::new(*device).unwrap());
        }

        // Capture array of pointers to the above CString values.
        // We also add a `NULL` pointer entry on the end, as expected by the C function called here.
        let mut c_dev_ptrs: Vec<*const c_char> = Vec::with_capacity(c_devs.len() + 1);
        for c_dev in &c_devs {
            c_dev_ptrs.push(c_dev.as_ptr());
        }
        c_dev_ptrs.push(null());

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_ext_device_manager_delete(self.context, c_dev_ptrs.as_ptr(),
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Enables the role-based device-priority routing mode.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn enable_role_device_priority_routing<F>(&mut self, enable: bool, callback: F)
        -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe {
            capi::pa_ext_device_manager_enable_role_device_priority_routing(self.context,
                enable as i32, Some(super::success_cb_proxy), cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Reorders the position of a given device in the priority list to give preference to it.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn reorder_devices_for_role<F>(&mut self, role: &str, devices: &[&str], callback: F)
        -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_role = CString::new(role).unwrap();
        let mut c_devs: Vec<CString> = Vec::with_capacity(devices.len());
        for device in devices {
            c_devs.push(CString::new(*device).unwrap());
        }

        // Capture array of pointers to the above CString values.
        // We also add a `NULL` pointer entry on the end, as expected by the C function called here.
        let mut c_dev_ptrs: Vec<*const c_char> = Vec::with_capacity(c_devs.len() + 1);
        for c_dev in &c_devs {
            c_dev_ptrs.push(c_dev.as_ptr());
        }
        c_dev_ptrs.push(null());

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe {
            capi::pa_ext_device_manager_reorder_devices_for_role(self.context, c_role.as_ptr(),
                c_dev_ptrs.as_ptr(), Some(super::success_cb_proxy), cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
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
        let ptr = unsafe { capi::pa_ext_device_manager_subscribe(self.context, enable as i32,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the subscription callback that is called when [`subscribe()`](Self::subscribe) was
    /// called.
    pub fn set_subscribe_cb<F>(&mut self, callback: F)
        where F: FnMut() + 'static
    {
        let saved = &mut self.cb_ptrs.subscribe;
        *saved = super::ExtSubscribeCb::new(Some(Box::new(callback)));
        let (cb_fn, cb_data) = saved.get_capi_params(super::ext_subscribe_cb_proxy);
        unsafe { capi::pa_ext_device_manager_set_subscribe_cb(self.context, cb_fn, cb_data) };
    }
}

impl Drop for DeviceManager {
    fn drop(&mut self) {
        unsafe { capi::pa_context_unref(self.context) };
        self.context = null_mut::<ContextInternal>();
    }
}

/// Proxy for read list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn read_list_cb_proxy(_: *mut ContextInternal, i: *const InfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, Info::new_from_raw);
    });
}
