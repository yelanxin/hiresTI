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

//! Property list constants and functions.

use std::os::raw::{c_char, c_void};
use std::ffi::{CStr, CString};
use std::ptr::{null, null_mut};
use std::marker::PhantomData;
use crate::error::PAErr;

pub(crate) use capi::pa_proplist as ProplistInternal;
pub use capi::pa_update_mode_t as UpdateMode;

/// Common properties.
pub mod properties {
    use capi;

    pub use capi::PA_PROP_MEDIA_NAME as MEDIA_NAME;
    pub use capi::PA_PROP_MEDIA_TITLE as MEDIA_TITLE;
    pub use capi::PA_PROP_MEDIA_ARTIST as MEDIA_ARTIST;
    pub use capi::PA_PROP_MEDIA_COPYRIGHT as MEDIA_COPYRIGHT;
    pub use capi::PA_PROP_MEDIA_SOFTWARE as MEDIA_SOFTWARE;
    pub use capi::PA_PROP_MEDIA_LANGUAGE as MEDIA_LANGUAGE;
    pub use capi::PA_PROP_MEDIA_FILENAME as MEDIA_FILENAME;
    pub use capi::PA_PROP_MEDIA_ICON as MEDIA_ICON;
    pub use capi::PA_PROP_MEDIA_ICON_NAME as MEDIA_ICON_NAME;
    pub use capi::PA_PROP_MEDIA_ROLE as MEDIA_ROLE;
    pub use capi::PA_PROP_FILTER_WANT as FILTER_WANT;
    pub use capi::PA_PROP_EVENT_ID as EVENT_ID;
    pub use capi::PA_PROP_EVENT_DESCRIPTION as EVENT_DESCRIPTION;
    pub use capi::PA_PROP_EVENT_MOUSE_X as EVENT_MOUSE_X;
    pub use capi::PA_PROP_EVENT_MOUSE_Y as EVENT_MOUSE_Y;
    pub use capi::PA_PROP_EVENT_MOUSE_HPOS as EVENT_MOUSE_HPOS;
    pub use capi::PA_PROP_EVENT_MOUSE_VPOS as EVENT_MOUSE_VPOS;
    pub use capi::PA_PROP_EVENT_MOUSE_BUTTON as EVENT_MOUSE_BUTTON;
    pub use capi::PA_PROP_WINDOW_NAME as WINDOW_NAME;
    pub use capi::PA_PROP_WINDOW_ID as WINDOW_ID;
    pub use capi::PA_PROP_WINDOW_ICON as WINDOW_ICON;
    pub use capi::PA_PROP_WINDOW_ICON_NAME as WINDOW_ICON_NAME;
    pub use capi::PA_PROP_WINDOW_X as WINDOW_X;
    pub use capi::PA_PROP_WINDOW_Y as WINDOW_Y;
    pub use capi::PA_PROP_WINDOW_WIDTH as WINDOW_WIDTH;
    pub use capi::PA_PROP_WINDOW_HEIGHT as WINDOW_HEIGHT;
    pub use capi::PA_PROP_WINDOW_HPOS as WINDOW_HPOS;
    pub use capi::PA_PROP_WINDOW_VPOS as WINDOW_VPOS;
    pub use capi::PA_PROP_WINDOW_DESKTOP as WINDOW_DESKTOP;
    pub use capi::PA_PROP_WINDOW_X11_DISPLAY as WINDOW_X11_DISPLAY;
    pub use capi::PA_PROP_WINDOW_X11_SCREEN as WINDOW_X11_SCREEN;
    pub use capi::PA_PROP_WINDOW_X11_MONITOR as WINDOW_X11_MONITOR;
    pub use capi::PA_PROP_WINDOW_X11_XID as WINDOW_X11_XID;
    pub use capi::PA_PROP_APPLICATION_NAME as APPLICATION_NAME;
    pub use capi::PA_PROP_APPLICATION_ID as APPLICATION_ID;
    pub use capi::PA_PROP_APPLICATION_VERSION as APPLICATION_VERSION;
    pub use capi::PA_PROP_APPLICATION_ICON as APPLICATION_ICON;
    pub use capi::PA_PROP_APPLICATION_ICON_NAME as APPLICATION_ICON_NAME;
    pub use capi::PA_PROP_APPLICATION_LANGUAGE as APPLICATION_LANGUAGE;
    pub use capi::PA_PROP_APPLICATION_PROCESS_ID as APPLICATION_PROCESS_ID;
    pub use capi::PA_PROP_APPLICATION_PROCESS_BINARY as APPLICATION_PROCESS_BINARY;
    pub use capi::PA_PROP_APPLICATION_PROCESS_USER as APPLICATION_PROCESS_USER;
    pub use capi::PA_PROP_APPLICATION_PROCESS_HOST as APPLICATION_PROCESS_HOST;
    pub use capi::PA_PROP_APPLICATION_PROCESS_MACHINE_ID as APPLICATION_PROCESS_MACHINE_ID;
    pub use capi::PA_PROP_APPLICATION_PROCESS_SESSION_ID as APPLICATION_PROCESS_SESSION_ID;
    pub use capi::PA_PROP_DEVICE_STRING as DEVICE_STRING;
    pub use capi::PA_PROP_DEVICE_API as DEVICE_API;
    pub use capi::PA_PROP_DEVICE_DESCRIPTION as DEVICE_DESCRIPTION;
    pub use capi::PA_PROP_DEVICE_BUS_PATH as DEVICE_BUS_PATH;
    pub use capi::PA_PROP_DEVICE_SERIAL as DEVICE_SERIAL;
    pub use capi::PA_PROP_DEVICE_VENDOR_ID as DEVICE_VENDOR_ID;
    pub use capi::PA_PROP_DEVICE_VENDOR_NAME as DEVICE_VENDOR_NAME;
    pub use capi::PA_PROP_DEVICE_PRODUCT_ID as DEVICE_PRODUCT_ID;
    pub use capi::PA_PROP_DEVICE_PRODUCT_NAME as DEVICE_PRODUCT_NAME;
    pub use capi::PA_PROP_DEVICE_CLASS as DEVICE_CLASS;
    pub use capi::PA_PROP_DEVICE_FORM_FACTOR as DEVICE_FORM_FACTOR;
    pub use capi::PA_PROP_DEVICE_BUS as DEVICE_BUS;
    pub use capi::PA_PROP_DEVICE_ICON as DEVICE_ICON;
    pub use capi::PA_PROP_DEVICE_ICON_NAME as DEVICE_ICON_NAME;
    pub use capi::PA_PROP_DEVICE_ACCESS_MODE as DEVICE_ACCESS_MODE;
    pub use capi::PA_PROP_DEVICE_MASTER_DEVICE as DEVICE_MASTER_DEVICE;
    pub use capi::PA_PROP_DEVICE_BUFFERING_BUFFER_SIZE as DEVICE_BUFFERING_BUFFER_SIZE;
    pub use capi::PA_PROP_DEVICE_BUFFERING_FRAGMENT_SIZE as DEVICE_BUFFERING_FRAGMENT_SIZE;
    pub use capi::PA_PROP_DEVICE_PROFILE_NAME as DEVICE_PROFILE_NAME;
    pub use capi::PA_PROP_DEVICE_PROFILE_DESCRIPTION as DEVICE_PROFILE_DESCRIPTION;
    pub use capi::PA_PROP_MODULE_AUTHOR as MODULE_AUTHOR;
    pub use capi::PA_PROP_MODULE_DESCRIPTION as MODULE_DESCRIPTION;
    pub use capi::PA_PROP_MODULE_USAGE as MODULE_USAGE;
    pub use capi::PA_PROP_MODULE_VERSION as MODULE_VERSION;
    pub use capi::PA_PROP_FORMAT_RATE as FORMAT_RATE;
    pub use capi::PA_PROP_FORMAT_CHANNELS as FORMAT_CHANNELS;
    #[cfg(any(doc, feature = "pa_v15"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
    pub use capi::PA_PROP_CONTEXT_FORCE_DISABLE_SHM as CONTEXT_FORCE_DISABLE_SHM;
    #[cfg(any(doc, feature = "pa_v15"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
    pub use capi::PA_PROP_BLUETOOTH_CODEC as BLUETOOTH_CODEC;

    /* These need defining here, rather than `pub use`, in order to correctly link to other things
     * in their doc comments */

    /// For streams: the name of a filter that is desired, e.g. “echo-cancel” or “equalizer-sink”.
    /// Differs from [`FILTER_WANT`] in that it forces PulseAudio to apply the filter, regardless of
    /// whether PulseAudio thinks it makes sense to do so or not. If this is set, [`FILTER_WANT`] is
    /// ignored. In other words, you almost certainly do not want to use this.
    pub const FILTER_APPLY: &str = capi::PA_PROP_FILTER_APPLY;

    /// For streams: the name of a filter that should specifically be suppressed (i.e. overrides
    /// [`FILTER_WANT`]). Useful for the times that [`FILTER_WANT`] is automatically added (e.g.
    /// echo-cancellation for phone streams when $VOIP_APP does its own, internal AEC).
    pub const FILTER_SUPPRESS: &str = capi::PA_PROP_FILTER_SUPPRESS;

    /// For devices: intended use. A space separated list of roles (see [`MEDIA_ROLE`]) this device
    /// is particularly well suited for, due to latency, quality or form factor.
    pub const DEVICE_INTENDED_ROLES: &str = capi::PA_PROP_DEVICE_INTENDED_ROLES;

    /// For PCM formats: the sample format used as returned by
    /// [`Format::to_string()`](crate::sample::Format::to_string).
    pub const FORMAT_SAMPLE_FORMAT: &str = capi::PA_PROP_FORMAT_SAMPLE_FORMAT;

    /// For PCM formats: the channel map of the stream as returned by
    /// [`Map::print()`](crate::channelmap::Map::print).
    pub const FORMAT_CHANNEL_MAP: &str = capi::PA_PROP_FORMAT_CHANNEL_MAP;
}

/// A property list object. Basically a dictionary with ASCII strings as keys and arbitrary data as
/// values.
pub struct Proplist(pub(crate) ProplistInner);

unsafe impl Send for Proplist {}
unsafe impl Sync for Proplist {}

/// Inner type holding ownership over actual C object, necessary to guard against use-after-free
/// issues with respect to the related `Iterator` object.
pub(crate) struct ProplistInner {
    /// The actual C object.
    pub(crate) ptr: *mut ProplistInternal,
    /// Used to avoid freeing the internal object when used as a weak wrapper in callbacks.
    weak: bool,
}

impl std::fmt::Debug for Proplist {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "[{}]", self.to_string_sep(", ").unwrap())
    }
}

/// Proplist iterator, used for iterating over the list’s keys. Returned by the
/// [`Proplist::iter()`] method.
///
/// Note, lifetime `'a` is used to tie an instance of this struct to the associated `Proplist`, and
/// thus prevent a use-after-free issue that would otherwise occur should the `Proplist` be
/// destroyed first. Conversion from a `Proplist` via `into_iter` is okay though as responsibility
/// for destruction is transfered to it.
//XXX: Do **NOT** derive `Clone` for this, it will introduce a use-afer-free. To implement `Clone` properly would require an `Rc` wrapper around `ProplistInner`, but then if that would apply to `Proplist` also, that affects the `Send`+`Sync` properties of `Proplist` and anything using it.
pub struct Iterator<'a> {
    /// The actual C proplist object.
    pl_ref: ProplistInner,
    /// State tracker, used by underlying C function.
    state: *mut c_void,
    /// Use lifetime `'a`.
    phantom: PhantomData<&'a ProplistInner>,
}

impl Iterator<'_> {
    fn new(pl: *mut ProplistInternal) -> Self {
        Self {
            pl_ref: ProplistInner { ptr: pl, weak: true },
            state: null_mut::<c_void>(),
            phantom: PhantomData,
        }
    }
}

impl std::iter::Iterator for Iterator<'_> {
    type Item = String;
    fn next(&mut self) -> Option<Self::Item> {
        let state_actual = &mut self.state as *mut *mut c_void;
        let key_ptr = unsafe { capi::pa_proplist_iterate(self.pl_ref.ptr, state_actual) };
        if key_ptr.is_null() {
            return None;
        }
        // We assume key_ptr will never be null at this point
        Some(unsafe { CStr::from_ptr(key_ptr).to_string_lossy().into_owned() })
    }
}

impl IntoIterator for Proplist {
    type Item = String;
    type IntoIter = Iterator<'static>;

    fn into_iter(mut self) -> Self::IntoIter {
        assert_eq!(false, self.0.weak);
        let mut iter = Iterator::new(self.0.ptr);
        // Move responsibility for destruction
        iter.pl_ref.weak = false;
        self.0.weak = true;
        iter
    }
}

impl PartialEq for Proplist {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        unsafe { capi::pa_proplist_equal(self.0.ptr, other.0.ptr) != 0 }
    }
}

impl Proplist {
    /// Allocates a property list.
    pub fn new() -> Option<Self> {
        let ptr = unsafe { capi::pa_proplist_new() };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr)),
            true => None,
        }
    }

    /// Allocates a new property list and assigns key/value from a human readable string.
    pub fn new_from_string(s: &str) -> Option<Self> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_str = CString::new(s).unwrap();
        let ptr = unsafe { capi::pa_proplist_from_string(c_str.as_ptr()) };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr)),
            true => None,
        }
    }

    /// Creates a new `Proplist` from an existing [`ProplistInternal`] pointer.
    #[inline]
    pub(crate) fn from_raw(ptr: *mut ProplistInternal) -> Self {
        assert_eq!(false, ptr.is_null());
        Proplist(ProplistInner { ptr: ptr, weak: false })
    }

    /// Creates a new `Proplist` from an existing [`ProplistInternal`] pointer.
    ///
    /// This is the ‘weak’ version, which avoids destroying the internal object when dropped.
    #[inline]
    pub(crate) fn from_raw_weak(ptr: *mut ProplistInternal) -> Self {
        assert_eq!(false, ptr.is_null());
        Proplist(ProplistInner { ptr: ptr, weak: true })
    }

    /// Allocates a new property list and copies over every single entry from the specified list.
    ///
    /// If this is called on a ‘weak’ instance, a non-weak object is returned.
    #[inline]
    pub(crate) fn to_owned(&self) -> Self {
        Self::from_raw(unsafe { capi::pa_proplist_copy(self.0.ptr) })
    }

    /// Checks if the key is valid.
    pub fn key_is_valid(key: &str) -> bool {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        unsafe { capi::pa_proplist_key_valid(c_key.as_ptr()) != 0 }
    }

    /// Appends a new string entry to the property list, possibly overwriting an already existing
    /// entry with the same key.
    ///
    /// An internal copy is made of the provided string.
    pub fn set_str(&mut self, key: &str, value: &str) -> Result<(), ()> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let c_value = CString::new(value).unwrap();
        match unsafe { capi::pa_proplist_sets(self.0.ptr, c_key.as_ptr(), c_value.as_ptr()) } {
            0 => Ok(()),
            _ => Err(()),
        }
    }

    /// Appends a new string entry to the property list, possibly overwriting an already existing
    /// entry with the same key.
    ///
    /// This is similar to [`set_str()`](Self::set_str), however here the provided key and value
    /// are combined into a single string, separated by an `=`. An internal copy is made of the
    /// provided string.
    pub fn set_pl(&mut self, pair: &str) -> Result<(), ()> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_pair = CString::new(pair).unwrap();
        match unsafe { capi::pa_proplist_setp(self.0.ptr, c_pair.as_ptr()) } {
            0 => Ok(()),
            _ => Err(()),
        }
    }

    /// Appends a new arbitrary data entry to the property list, possibly overwriting an already
    /// existing entry with the same key.
    ///
    /// An internal copy of the provided data is made.
    pub fn set(&mut self, key: &str, data: &[u8]) -> Result<(), ()> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        //  as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        match unsafe { capi::pa_proplist_set(self.0.ptr, c_key.as_ptr(),
            data.as_ptr() as *mut c_void, data.len()) }
        {
            0 => Ok(()),
            _ => Err(()),
        }
    }

    /// Gets a string entry for the specified key.
    ///
    /// Will return `None` if the key does not exist or if data is not valid UTF-8.
    pub fn get_str(&self, key: &str) -> Option<String> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let ptr = unsafe { capi::pa_proplist_gets(self.0.ptr, c_key.as_ptr()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }),
            true => None,
        }
    }

    /// Gets the value for the specified key.
    ///
    /// For string entries, the value store will be NUL-terminated.
    ///
    /// The caller should make a copy of the data before any subsequent modification or destruction
    /// of the property list.
    ///
    /// Returns a slice formed from the data pointer and the length of the data.
    /// Returns `None` if key does not exist.
    pub fn get(&self, key: &str) -> Option<&[u8]> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let mut data_ptr = null::<c_void>();
        let mut nbytes: usize = 0;
        if unsafe { capi::pa_proplist_get(self.0.ptr, c_key.as_ptr(), &mut data_ptr, &mut nbytes) }
            != 0
        {
            return None;
        }
        if data_ptr.is_null() {
            return None;
        }
        Some(unsafe { std::slice::from_raw_parts(data_ptr as *const u8, nbytes) })
    }

    /// Merges property list “other” into self, adhering to the merge mode specified.
    #[inline]
    pub fn merge(&mut self, other: &Self, mode: UpdateMode) {
        unsafe { capi::pa_proplist_update(self.0.ptr, mode, other.0.ptr); }
    }

    /// Removes a single entry from the property list, identified by the specified key name.
    pub fn unset(&mut self, key: &str) -> Result<(), PAErr> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        match unsafe { capi::pa_proplist_unset(self.0.ptr, c_key.as_ptr()) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Similar to [`unset()`](Self::unset) but takes an array of keys to remove.
    ///
    /// Returns `None` on failure, otherwise the number of entries actually removed (which might
    /// even be 0, if there were no matching entries to remove).
    pub fn unset_many(&mut self, keys: &[&str]) -> Option<u32> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let mut c_keys: Vec<CString> = Vec::with_capacity(keys.len());
        for k in keys {
            c_keys.push(CString::new(*k).unwrap());
        }

        // Capture array of pointers to the above CString values.
        // We also add a NULL pointer entry on the end, as expected by the C function called here.
        let mut c_keys_ptrs: Vec<*const c_char> = Vec::with_capacity(c_keys.len() + 1);
        for k in &c_keys {
            c_keys_ptrs.push(k.as_ptr());
        }
        c_keys_ptrs.push(null());

        match unsafe { capi::pa_proplist_unset_many(self.0.ptr, c_keys_ptrs.as_ptr()) } {
            r if r < 0 => None,
            r => Some(r as u32),
        }
    }

    /// Gets an immutable iterator over the list’s keys.
    ///
    /// The property list should not be modified during iteration through the list, with the
    /// exception of deleting the current entry. The keys in the property list do not have any
    /// particular order.
    ///
    /// ```rust
    /// # extern crate libpulse_binding as pulse;
    /// # use pulse::proplist::Proplist;
    /// #
    /// # fn main() {
    /// #     let mut my_props = Proplist::new().unwrap();
    /// #     my_props.set_str(pulse::proplist::properties::APPLICATION_NAME, "FooApp").unwrap();
    /// #
    /// for key in my_props.iter() {
    ///     //do something with it
    ///     println!("key: {}", key);
    /// }
    /// # }
    /// ```
    #[inline]
    pub fn iter(&self) -> Iterator<'_> {
        Iterator::new(self.0.ptr)
    }

    /// Formats the property list nicely as a human readable string.
    ///
    /// This works very much like [`to_string_sep()`](Self::to_string_sep) and uses a newline as
    /// separator and appends one final one.
    pub fn to_string(&self) -> Option<String> {
        let ptr = unsafe { capi::pa_proplist_to_string(self.0.ptr) };
        if ptr.is_null() {
            return None;
        }
        // Note, copying string on behalf of user here, and freeing that returned by PA, as
        // documentation instructs, saving the user from having to remember.
        unsafe {
            let ret = Some(CStr::from_ptr(ptr).to_string_lossy().into_owned());
            capi::pa_xfree(ptr as *mut c_void);
            ret
        }
    }

    /// Formats the property list nicely as a human readable string, choosing the separator used.
    pub fn to_string_sep(&self, sep: &str) -> Option<String> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_sep = CString::new(sep).unwrap();
        let ptr = unsafe { capi::pa_proplist_to_string_sep(self.0.ptr, c_sep.as_ptr()) };
        if ptr.is_null() {
            return None;
        }
        // Note, copying string on behalf of user here, and freeing that returned by PA, as
        // documentation instructs, saving the user from having to remember.
        unsafe {
            let ret = Some(CStr::from_ptr(ptr).to_string_lossy().into_owned());
            capi::pa_xfree(ptr as *mut c_void);
            ret
        }
    }

    /// Checks if this contains an entry with the given key.
    ///
    /// Returns `true` if an entry for the specified key exists in the property list. Returns `None`
    /// on error.
    pub fn contains(&self, key: &str) -> Option<bool> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        match unsafe { capi::pa_proplist_contains(self.0.ptr, c_key.as_ptr()) } {
            0 => Some(false),
            1 => Some(true),
            _ => None,
        }
    }

    /// Removes all entries from the property list object.
    #[inline]
    pub fn clear(&mut self) {
        unsafe { capi::pa_proplist_clear(self.0.ptr); }
    }

    /// Gets the number of entries in the property list.
    #[inline]
    pub fn len(&self) -> u32 {
        unsafe { capi::pa_proplist_size(self.0.ptr) }
    }

    /// Checks if the proplist is empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        unsafe { capi::pa_proplist_isempty(self.0.ptr) == 0 }
    }
}

impl Drop for ProplistInner {
    fn drop(&mut self) {
        if !self.weak {
            unsafe { capi::pa_proplist_free(self.ptr) };
        }
        self.ptr = null_mut::<ProplistInternal>();
    }
}

impl Clone for Proplist {
    /// Allocates a new property list and copy over every single entry from the specified list.
    ///
    /// If this is called on a ‘weak’ instance, a non-weak object is returned.
    #[inline]
    fn clone(&self) -> Self {
        self.to_owned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
/*
    /// Test that you cannot create a use-after-free situation by destroying a `Proplist` before an
    /// associated `Iterator` (we avoid `Rc`/`Arc`).
    #[test]
    fn proplist_iter_lifetime() {
        let iter = {
            let my_props = Proplist::new().unwrap();
            my_props.iter() //Returning this should not compile!
        };

        for key in iter {
            //do something with it
            println!("key: {}", key);
        }
    }
*/
    /// Test that you can however return an iterator if you convert the `Proplist` into one
    #[test]
    fn proplist_iter_lifetime_conv() {
        let iter = {
            let my_props = Proplist::new().unwrap();
            my_props.into_iter()
        };

        for key in iter {
            //do something with it
            println!("key: {}", key);
        }
    }
}
