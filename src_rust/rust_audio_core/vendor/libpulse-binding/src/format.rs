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

//! Utility functions for handling a stream or sink format.
//!
//! # Note
//!
//! Clients using an [`Info`] structure must remember to at least set the encoding attribute, which
//! can be done through the [`Info::set_encoding()`] method.

use std::os::raw::{c_char, c_void};
use std::ffi::{CStr, CString};
use std::ptr::{null, null_mut};
use std::borrow::Cow;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::{sample, channelmap};
use crate::error::PAErr;
use crate::proplist::{Proplist, ProplistInternal};

pub use capi::pa_prop_type_t as PropType;

/// Represents the type of encoding used in a stream or accepted by a sink.
#[repr(C)]
#[non_exhaustive]
#[derive(Debug, Default, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum Encoding {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */
    /// Any encoding format, PCM or compressed.
    Any,
    /// Any PCM format.
    PCM,
    /// AC3 data encapsulated in IEC 61937 header/padding.
    AC3_IEC61937,
    /// EAC3 data encapsulated in IEC 61937 header/padding.
    EAC3_IEC61937,
    /// MPEG-1 or MPEG-2 (Part 3, not AAC) data encapsulated in IEC 61937 header/padding.
    MPEG_IEC61937,
    /// DTS data encapsulated in IEC 61937 header/padding.
    DTS_IEC61937,
    /// MPEG-2 AAC data encapsulated in IEC 61937 header/padding.
    MPEG2_AAC_IEC61937,
    /// Dolby TrueHD data encapsulated in IEC 61937 header/padding.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    TRUEHD_IEC61937,
    /// DTS-HD Master Audio encapsulated in IEC 61937 header/padding.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    DTSHD_IEC61937,

    /// Represents an invalid encoding.
    #[default]
    Invalid = -1,
}

/// Check is equal to `sys` equivalent
#[test]
fn enc_compare_capi() {
    assert_eq!(std::mem::size_of::<Encoding>(), std::mem::size_of::<capi::pa_encoding_t>());
    assert_eq!(std::mem::align_of::<Encoding>(), std::mem::align_of::<capi::pa_encoding_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(Encoding::Any,                Encoding::from(capi::pa_encoding_t::Any));
    assert_eq!(Encoding::PCM,                Encoding::from(capi::pa_encoding_t::PCM));
    assert_eq!(Encoding::AC3_IEC61937,       Encoding::from(capi::pa_encoding_t::AC3_IEC61937));
    assert_eq!(Encoding::EAC3_IEC61937,      Encoding::from(capi::pa_encoding_t::EAC3_IEC61937));
    assert_eq!(Encoding::MPEG_IEC61937,      Encoding::from(capi::pa_encoding_t::MPEG_IEC61937));
    assert_eq!(Encoding::DTS_IEC61937,       Encoding::from(capi::pa_encoding_t::DTS_IEC61937));
    assert_eq!(Encoding::MPEG2_AAC_IEC61937, Encoding::from(capi::pa_encoding_t::MPEG2_AAC_IEC61937));
    #[cfg(any(doc, feature = "pa_v13"))]
    assert_eq!(Encoding::TRUEHD_IEC61937,    Encoding::from(capi::pa_encoding_t::TRUEHD_IEC61937));
    #[cfg(any(doc, feature = "pa_v13"))]
    assert_eq!(Encoding::DTSHD_IEC61937,     Encoding::from(capi::pa_encoding_t::DTSHD_IEC61937));
    assert_eq!(Encoding::Invalid,            Encoding::from(capi::pa_encoding_t::Invalid));
}

impl From<Encoding> for capi::pa_encoding_t {
    #[inline]
    fn from(e: Encoding) -> Self {
        unsafe { std::mem::transmute(e) }
    }
}
impl From<capi::pa_encoding_t> for Encoding {
    #[inline]
    fn from(e: capi::pa_encoding_t) -> Self {
        unsafe { std::mem::transmute(e) }
    }
}

/// Represents the format of data provided in a stream or processed by a sink.
pub struct Info {
    /// The actual C object.
    pub(crate) ptr: *mut InfoInternal,
    /// A nicely wrapped copy of it’s property list pointer, for convenience.
    properties: Proplist,
    /// Used to avoid freeing the internal object when used as a weak wrapper in callbacks.
    weak: bool,
}

unsafe impl Send for Info {}
unsafe impl Sync for Info {}

/// The raw C structure (with documentation).
#[repr(C)]
pub(crate) struct InfoInternal {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */
    /// The encoding used for the format.
    pub encoding: Encoding,
    /// Additional encoding-specific properties such as sample rate, bitrate, etc.
    pub list: *mut ProplistInternal,
}

/// Test size is equal to `sys` equivalent (duplicated here for different documentation)
#[test]
fn info_compare_capi() {
    assert_eq!(std::mem::size_of::<InfoInternal>(), std::mem::size_of::<capi::pa_format_info>());
    assert_eq!(std::mem::align_of::<InfoInternal>(), std::mem::align_of::<capi::pa_format_info>());
}

impl std::fmt::Debug for Info {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Info {{ encoding: {:?}, properties: {:?} }}", self.get_encoding(),
            *self.get_properties())
    }
}

impl Encoding {
    /// Returns a printable string representing the given encoding type.
    pub fn to_string(e: Self) -> Option<Cow<'static, str>> {
        let ptr = unsafe { capi::pa_encoding_to_string(e.into()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy() }),
            true => None,
        }
    }

    /// Converts a string of the form returned by [`to_string()`](Self::to_string) back to an
    /// `Encoding`.
    #[cfg(any(doc, feature = "pa_v12"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v12")))]
    pub fn from_string(encoding: &str) -> Self {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_enc = CString::new(encoding).unwrap();
        unsafe { capi::pa_encoding_from_string(c_enc.as_ptr()).into() }
    }
}

impl Info {
    /// Allocates a new `Info` structure.
    ///
    /// Clients must initialise at least the encoding field themselves. Returns `None` on failure.
    pub fn new() -> Option<Self> {
        let ptr = unsafe { capi::pa_format_info_new() };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr as *mut InfoInternal)),
            true => None,
        }
    }

    /// Parses a human-readable string of the form generated by [`print()`](Self::print) into an
    /// `Info` structure.
    ///
    /// Returns `None` on failure.
    pub fn new_from_string(s: &str) -> Option<Self> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_str = CString::new(s).unwrap();
        let ptr = unsafe { capi::pa_format_info_from_string(c_str.as_ptr()) };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr as *mut InfoInternal)),
            true => None,
        }
    }

    /// Utility function to take a [`Spec`] and generate the corresponding `Info`.
    ///
    /// Note that if you want the server to choose some of the stream parameters, for example the
    /// sample rate, so that they match the device parameters, then you shouldn’t use this function.
    /// In order to allow the server to choose a parameter value, that parameter must be left
    /// unspecified in the `Info` object, and this function always specifies all parameters. An
    /// exception is the channel map: if you pass `None` for the channel map, then the channel map
    /// will be left unspecified, allowing the server to choose it.
    ///
    /// Returns `None` on failure.
    ///
    /// [`Spec`]: crate::sample::Spec
    pub fn new_from_sample_spec(ss: &sample::Spec, map: Option<&channelmap::Map>) -> Option<Self> {
        let p_map = map.map_or(null::<capi::pa_channel_map>(), |m| m.as_ref());
        let ptr = unsafe { capi::pa_format_info_from_sample_spec(ss.as_ref(), p_map) };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr as *mut InfoInternal)),
            true => None,
        }
    }

    /// Creates a new `Info` from an existing [`InfoInternal`] pointer.
    pub(crate) fn from_raw(ptr: *mut InfoInternal) -> Self {
        assert_eq!(false, ptr.is_null());
        // Note, yes, this should be weak; the ‘free’ function for a format info object free’s its
        // own proplist!
        let pl = Proplist::from_raw_weak(unsafe { (*ptr).list });
        Self { ptr: ptr, properties: pl, weak: false }
    }

    /// Creates a new `Info` from an existing [`InfoInternal`] pointer.
    ///
    /// This is the ‘weak’ version, which avoids destroying the internal object when dropped.
    pub(crate) fn from_raw_weak(ptr: *mut InfoInternal) -> Self {
        assert_eq!(false, ptr.is_null());
        let pl = Proplist::from_raw_weak(unsafe { (*ptr).list });
        Self { ptr: ptr, properties: pl, weak: true }
    }

    /// Returns a new `Info` struct representing the same format.
    ///
    /// If this is called on a ‘weak’ instance, a non-weak object is returned.
    #[inline]
    pub(crate) fn to_owned(&self) -> Self {
        let ptr = unsafe { capi::pa_format_info_copy(self.ptr as *const capi::pa_format_info) };
        Self::from_raw(ptr as *mut InfoInternal)
    }

    /// Checks whether the `Info` structure is valid.
    #[inline]
    pub fn is_valid(&self) -> bool {
        unsafe { capi::pa_format_info_valid(self.ptr as *const capi::pa_format_info) != 0 }
    }

    /// Checks whether the `Info` structure represents a PCM (i.e. uncompressed data) format.
    #[inline]
    pub fn is_pcm(&self) -> bool {
        unsafe { capi::pa_format_info_is_pcm(self.ptr as *const capi::pa_format_info) != 0 }
    }

    /// Checks whether the format represented by self is a subset of the format represented by
    /// `with`.
    ///
    /// This means that `with` must have all the fields that self does, but the reverse need not be
    /// true. This is typically expected to be used to check if a stream’s format is compatible with
    /// a given sink. In such a case, self would be the sink’s format and `with` would be the
    /// streams.
    #[inline]
    pub fn is_compatible_with(&self, with: &Self) -> bool {
        unsafe { capi::pa_format_info_is_compatible(self.ptr as *const capi::pa_format_info,
            with.ptr as *const capi::pa_format_info) != 0 }
    }

    /// Gets a human-readable string representing the given format.
    pub fn print(&self) -> String {
        const PRINT_MAX: usize = capi::PA_FORMAT_INFO_SNPRINT_MAX;
        let mut tmp = Vec::with_capacity(PRINT_MAX);
        unsafe {
            capi::pa_format_info_snprint(tmp.as_mut_ptr(), PRINT_MAX,
                self.ptr as *const capi::pa_format_info);
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Utility function to generate a [`Spec`] and [`Map`] corresponding to a given `Info`.
    ///
    /// The conversion for PCM formats is straight-forward. For non-PCM formats, if there is a fixed
    /// size-time conversion (i.e. all IEC61937-encapsulated formats), a “fake” sample spec whose
    /// size-time conversion corresponds to this format is provided and the channel map argument is
    /// ignored. For formats with variable size-time conversion, this function will fail.
    ///
    /// [`Spec`]: crate::sample::Spec
    /// [`Map`]: crate::channelmap::Map
    pub fn to_sample_spec(&self, ss: &mut sample::Spec, map: &mut channelmap::Map)
        -> Result<(), PAErr>
    {
        match unsafe { capi::pa_format_info_to_sample_spec(
            self.ptr as *const capi::pa_format_info, ss.as_mut(), map.as_mut()) }
        {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the encoding.
    #[inline]
    pub fn get_encoding(&self) -> Encoding {
        unsafe { (*self.ptr).encoding }
    }

    /// Sets the encoding attribute.
    #[inline]
    pub fn set_encoding(&mut self, encoding: Encoding) {
        unsafe { (*self.ptr).encoding = encoding };
    }

    /// Gets an immutable reference to the property list.
    #[inline]
    pub fn get_properties(&self) -> &Proplist {
        &self.properties
    }

    /// Gets a mutable reference to the property list.
    #[inline]
    pub fn get_properties_mut(&mut self) -> &mut Proplist {
        &mut self.properties
    }

    /// Gets the type of property key.
    pub fn get_prop_type(&self, key: &str) -> PropType {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        unsafe { capi::pa_format_info_get_prop_type(self.ptr as *const capi::pa_format_info,
            c_key.as_ptr()) }
    }

    /// Gets an integer property.
    pub fn get_prop_int(&self, key: &str) -> Result<i32, PAErr> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let mut i: i32 = 0;
        let c_key = CString::new(key).unwrap();
        match unsafe { capi::pa_format_info_get_prop_int(self.ptr as *const capi::pa_format_info,
            c_key.as_ptr(), &mut i) }
        {
            0 => Ok(i),
            e => Err(PAErr(e)),
        }
    }

    /// Gets an integer range property. On success, returns min-max tuple.
    pub fn get_prop_int_range(&self, key: &str) -> Result<(i32, i32), PAErr> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let mut min: i32 = 0;
        let mut max: i32 = 0;
        let c_key = CString::new(key).unwrap();
        match unsafe { capi::pa_format_info_get_prop_int_range(
            self.ptr as *const capi::pa_format_info, c_key.as_ptr(), &mut min, &mut max) }
        {
            0 => Ok((min, max)),
            e => Err(PAErr(e)),
        }
    }

    /// Gets an integer array property.
    ///
    /// Returns `None` on error.
    pub fn get_prop_int_array(&self, key: &str) -> Option<Vec<i32>> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let mut count: i32 = 0;
        let mut p_ints = null_mut::<i32>();
        let result = unsafe { capi::pa_format_info_get_prop_int_array(
            self.ptr as *const capi::pa_format_info, c_key.as_ptr(), &mut p_ints, &mut count) };
        if result != 0 {
            return None;
        }
        // Clone each int in the array
        let mut values: Vec<i32> = Vec::with_capacity(count as usize);
        for i in 0..count {
            values.push(unsafe { *p_ints.offset(i as isize) });
        }
        // Free the PA allocated array
        unsafe { capi::pa_xfree(p_ints as *mut c_void) };
        // Return vector of ints
        Some(values)
    }

    /// Gets a string property.
    pub fn get_prop_string(&self, key: &str) -> Option<String> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let mut p_str = null_mut::<c_char>();
        let result = unsafe { capi::pa_format_info_get_prop_string(
            self.ptr as *const capi::pa_format_info, c_key.as_ptr(), &mut p_str) };
        if result != 0 || p_str.is_null() {
            return None;
        }
        unsafe {
            let ret = Some(CStr::from_ptr(p_str).to_string_lossy().into_owned());
            capi::pa_xfree(p_str as *mut c_void);
            ret
        }
    }

    /// Gets a string array property.
    pub fn get_prop_string_array(&self, key: &str) -> Option<Vec<String>> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let mut count: i32 = 0;
        let mut pp_str = null_mut::<*mut c_char>();
        let result = unsafe { capi::pa_format_info_get_prop_string_array(
            self.ptr as *const capi::pa_format_info, c_key.as_ptr(), &mut pp_str, &mut count) };
        if result != 0 || pp_str.is_null() {
            return None;
        }
        // Clone each string in the array to owned String
        let mut values: Vec<String> = Vec::with_capacity(count as usize);
        for i in 0..count {
            let p_str = unsafe { *pp_str.offset(i as isize) };
            if !p_str.is_null() {
                values.push(unsafe { CStr::from_ptr(p_str).to_string_lossy().into_owned() });
            }
        }
        // Free all PA internally allocated strings
        unsafe { capi::pa_format_info_free_string_array(pp_str, count) };
        // Return vector of Strings
        Some(values)
    }

    /// Gets the sample format stored in the format info.
    ///
    /// Returns `Err` if the sample format property is not set at all, or is invalid.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn get_sample_format(&self) -> Result<crate::sample::Format, PAErr> {
        let mut sf: capi::pa_sample_format_t = capi::PA_SAMPLE_INVALID;
        match unsafe { capi::pa_format_info_get_sample_format(
            self.ptr as *const capi::pa_format_info, &mut sf) }
        {
            0 => Ok(crate::sample::Format::from(sf)),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the sample rate stored in the format info.
    ///
    /// Returns `Err` if the sample rate property is not set at all, or is invalid.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn get_rate(&self) -> Result<u32, PAErr> {
        let mut rate: u32 = 0;
        match unsafe { capi::pa_format_info_get_rate(self.ptr as *const capi::pa_format_info,
            &mut rate) }
        {
            0 => Ok(rate),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the channel count stored in the format info.
    ///
    /// Returns `Err` if the channels property is not set at all, or is invalid.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn get_channel_count(&self) -> Result<u8, PAErr> {
        let mut channels: u8 = 0;
        match unsafe { capi::pa_format_info_get_channels(self.ptr as *const capi::pa_format_info,
            &mut channels) }
        {
            0 => Ok(channels),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the channel map stored in the format info.
    ///
    /// Returns `Err` if the channel map property is not set at all, or if the string form it is
    /// stored in within the property set fails to parse successfully.
    #[cfg(any(doc, feature = "pa_v13"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v13")))]
    pub fn get_channel_map(&self) -> Result<crate::channelmap::Map, PAErr> {
        // Returning the entire struct written to here may be a little less efficient than taking a
        // pointer like the C API, but we avoid the possibility of leaving the user with an
        // incomplete struct; parsing from string form is inefficient anyway, and we thus should not
        // expect this to be done frequently anyway.
        let mut map: capi::pa_channel_map = capi::pa_channel_map::default();
        match unsafe { capi::pa_format_info_get_channel_map(
            self.ptr as *const capi::pa_format_info, &mut map) }
        {
            0 => Ok(crate::channelmap::Map::from(map)),
            e => Err(PAErr(e)),
        }
    }

    /// Sets an integer property.
    pub fn set_prop_int(&mut self, key: &str, value: i32) {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        unsafe { capi::pa_format_info_set_prop_int(self.ptr as *mut capi::pa_format_info,
            c_key.as_ptr(), value); }
    }

    /// Sets a property with a list of integer values.
    ///
    /// Panics if length of array is larger than `i32::MAX`.
    pub fn set_prop_int_array(&mut self, key: &str, values: &[i32]) {
        assert!(values.len() <= i32::MAX as usize);
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        unsafe { capi::pa_format_info_set_prop_int_array(self.ptr as *mut capi::pa_format_info,
            c_key.as_ptr(), values.as_ptr(), values.len() as i32); }
    }

    /// Sets a property which can have any value in a given integer range.
    pub fn set_prop_int_range(&mut self, key: &str, min: i32, max: i32) {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        unsafe { capi::pa_format_info_set_prop_int_range(self.ptr as *mut capi::pa_format_info,
            c_key.as_ptr(), min, max); }
    }

    /// Sets a string property.
    pub fn set_prop_string(&mut self, key: &str, value: &str) {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let c_value = CString::new(value).unwrap();
        unsafe { capi::pa_format_info_set_prop_string(self.ptr as *mut capi::pa_format_info,
            c_key.as_ptr(), c_value.as_ptr()); }
    }

    /// Sets a property with a list of string values.
    ///
    /// Panics if length of array is larger than `i32::MAX`.
    pub fn set_prop_string_array(&mut self, key: &str, values: &[&str]) {
        assert!(values.len() <= i32::MAX as usize);
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_key = CString::new(key).unwrap();
        let mut c_values: Vec<CString> = Vec::with_capacity(values.len());
        for v in values {
            c_values.push(CString::new(*v).unwrap());
        }

        // Capture array of pointers to the above CString values
        let mut c_value_ptrs: Vec<*const c_char> = Vec::with_capacity(c_values.len());
        for v in &c_values {
            c_value_ptrs.push(v.as_ptr());
        }
        unsafe {
            capi::pa_format_info_set_prop_string_array(self.ptr as *mut capi::pa_format_info,
                c_key.as_ptr(), c_value_ptrs.as_ptr(), c_value_ptrs.len() as i32);
        }
    }

    /// Convenience method to set the sample format as a property.
    ///
    /// Note for PCM: If the sample format is left unspecified in the `Info` object, then the server
    /// will select the stream sample format. In that case the stream sample format will most likely
    /// match the device sample format, meaning that sample format conversion will be avoided.
    #[inline]
    pub fn set_sample_format(&mut self, sf: sample::Format) {
        unsafe { capi::pa_format_info_set_sample_format(self.ptr as *mut capi::pa_format_info,
            sf.into()); }
    }

    /// Convenience method to set the sampling rate as a property.
    ///
    /// Note for PCM: If the sample rate is left unspecified in the `Info` object, then the server
    /// will select the stream sample rate. In that case the stream sample rate will most likely
    /// match the device sample rate, meaning that sample rate conversion will be avoided.
    #[inline]
    pub fn set_rate(&mut self, rate: i32) {
        unsafe { capi::pa_format_info_set_rate(self.ptr as *mut capi::pa_format_info, rate) }
    }

    /// Convenience method to set the number of channels as a property.
    ///
    /// Note for PCM: If the channel count is left unspecified in the `Info` object, then the server
    /// will select the stream channel count. In that case the stream channel count will most likely
    /// match the device channel count, meaning that up/downmixing will be avoided.
    ///
    /// Panics if `channels` is larger than can be submitted to the C function.
    #[inline]
    pub fn set_channels(&mut self, channels: u32) {
        assert!(channels <= std::i32::MAX as u32);
        unsafe { capi::pa_format_info_set_channels(self.ptr as *mut capi::pa_format_info,
            channels as i32) }
    }

    /// Convenience method to set the channel map as a property.
    ///
    /// Note for PCM: If the channel map is left unspecified in the `Info` object, then the server
    /// will select the stream channel map. In that case the stream channel map will most likely
    /// match the device channel map, meaning that remixing will be avoided.
    #[inline]
    pub fn set_channel_map(&mut self, map: &channelmap::Map) {
        unsafe { capi::pa_format_info_set_channel_map(self.ptr as *mut capi::pa_format_info,
            map.as_ref()) }
    }
}

impl Drop for Info {
    fn drop(&mut self) {
        if !self.weak {
            unsafe { capi::pa_format_info_free(self.ptr as *mut capi::pa_format_info) };
        }
    }
}

impl Clone for Info {
    /// Returns a new `Info` struct and representing the same format.
    ///
    /// If this is called on a ‘weak’ instance, a non-weak object is returned.
    fn clone(&self) -> Self {
        self.to_owned()
    }
}
