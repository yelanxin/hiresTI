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

//! Error management.

use std::ffi::CStr;
use num_traits::FromPrimitive as FromPrimitiveTrait;
use num_derive::{FromPrimitive, ToPrimitive};

/// A wrapper around integer errors returned by PulseAudio. Can be converted to a [`Code`] variant
/// for comparison purposes if desired.
#[repr(transparent)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct PAErr(pub i32);

/// These represent errors returned by many of the underlying PulseAudio C functions.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum Code {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */
    /// No error.
    Ok = 0,
    /// Access failure.
    Access,
    /// Unknown command.
    Command,
    /// Invalid argument.
    Invalid,
    /// Entity exists.
    Exist,
    /// No such entity.
    NoEntity,
    /// Connection refused.
    ConnectionRefused,
    /// Protocol error.
    Protocol,
    /// Timeout.
    Timeout,
    /// No authentication key.
    AuthKey,
    /// Internal.
    Internal,
    /// Connection terminated.
    ConnectionTerminated,
    /// Entity killed.
    Killed,
    /// Invalid server.
    InvalidServer,
    /// Module init failed.
    ModInitFailed,
    /// Bad state.
    BadState,
    /// No data.
    NoData,
    /// Incompatible protocol version.
    Version,
    /// Data too large.
    TooLarge,
    /// Operation not supported.
    NotSupported,
    /// The error code was unknown to the client.
    Unknown,
    /// Extension does not exist.
    NoExtension,
    /// Obsolete functionality.
    Obsolete,
    /// Missing implementation.
    NotImplemented,
    /// The caller forked without calling execve() and tried to reuse the context.
    Forked,
    /// An IO error happened.
    IO,
    /// Device or resource busy.
    Busy,
}

/// Check is equal to `sys` equivalent
#[test]
fn code_compare_capi() {
    assert_eq!(std::mem::size_of::<Code>(), std::mem::size_of::<capi::pa_error_code_t>());
    assert_eq!(std::mem::align_of::<Code>(), std::mem::align_of::<capi::pa_error_code_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(Code::Ok,                   Code::from(capi::pa_error_code_t::Ok));
    assert_eq!(Code::Access,               Code::from(capi::pa_error_code_t::Access));
    assert_eq!(Code::Command,              Code::from(capi::pa_error_code_t::Command));
    assert_eq!(Code::Invalid,              Code::from(capi::pa_error_code_t::Invalid));
    assert_eq!(Code::Exist,                Code::from(capi::pa_error_code_t::Exist));
    assert_eq!(Code::NoEntity,             Code::from(capi::pa_error_code_t::NoEntity));
    assert_eq!(Code::ConnectionRefused,    Code::from(capi::pa_error_code_t::ConnectionRefused));
    assert_eq!(Code::Protocol,             Code::from(capi::pa_error_code_t::Protocol));
    assert_eq!(Code::Timeout,              Code::from(capi::pa_error_code_t::Timeout));
    assert_eq!(Code::AuthKey,              Code::from(capi::pa_error_code_t::AuthKey));
    assert_eq!(Code::Internal,             Code::from(capi::pa_error_code_t::Internal));
    assert_eq!(Code::ConnectionTerminated, Code::from(capi::pa_error_code_t::ConnectionTerminated));
    assert_eq!(Code::Killed,               Code::from(capi::pa_error_code_t::Killed));
    assert_eq!(Code::InvalidServer,        Code::from(capi::pa_error_code_t::InvalidServer));
    assert_eq!(Code::ModInitFailed,        Code::from(capi::pa_error_code_t::ModInitFailed));
    assert_eq!(Code::BadState,             Code::from(capi::pa_error_code_t::BadState));
    assert_eq!(Code::NoData,               Code::from(capi::pa_error_code_t::NoData));
    assert_eq!(Code::Version,              Code::from(capi::pa_error_code_t::Version));
    assert_eq!(Code::TooLarge,             Code::from(capi::pa_error_code_t::TooLarge));
    assert_eq!(Code::NotSupported,         Code::from(capi::pa_error_code_t::NotSupported));
    assert_eq!(Code::Unknown,              Code::from(capi::pa_error_code_t::Unknown));
    assert_eq!(Code::NoExtension,          Code::from(capi::pa_error_code_t::NoExtension));
    assert_eq!(Code::Obsolete,             Code::from(capi::pa_error_code_t::Obsolete));
    assert_eq!(Code::NotImplemented,       Code::from(capi::pa_error_code_t::NotImplemented));
    assert_eq!(Code::Forked,               Code::from(capi::pa_error_code_t::Forked));
    assert_eq!(Code::IO,                   Code::from(capi::pa_error_code_t::IO));
    assert_eq!(Code::Busy,                 Code::from(capi::pa_error_code_t::Busy));
}

impl From<Code> for capi::pa_error_code_t {
    #[inline]
    fn from(c: Code) -> Self {
        unsafe { std::mem::transmute(c) }
    }
}
impl From<capi::pa_error_code_t> for Code {
    #[inline]
    fn from(c: capi::pa_error_code_t) -> Self {
        unsafe { std::mem::transmute(c) }
    }
}

impl PAErr {
    /// Converts an integer error value, as returned by many PA C API functions, to a human readable
    /// string.
    pub fn to_string(&self) -> Option<String> {
        let ptr = unsafe { capi::pa_strerror(self.0) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }),
            true => None,
        }
    }
}

impl std::error::Error for PAErr {}

impl std::fmt::Display for PAErr {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self.to_string() {
            Some(s) => write!(f, "{}", s),
            None => write!(f, ""),
        }
    }
}

impl Code {
    /// Converts a `Code` to a human readable string.
    #[inline]
    pub fn to_string(self) -> Option<String> {
        PAErr::from(self).to_string()
    }
}

impl std::error::Error for Code {}

impl std::fmt::Display for Code {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match (*self).to_string() {
            Some(s) => write!(f, "{}", s),
            None => write!(f, ""),
        }
    }
}

impl From<Code> for PAErr {
    #[inline]
    fn from(c: Code) -> Self {
        // Error codes are negative, `Code` enum variants are positive
        PAErr(-(c as i32))
    }
}

impl TryFrom<PAErr> for Code {
    type Error = ();

    /// Attempts to convert the wrapped integer error value to a `Code` variant.
    ///
    /// Returns `Err(())` if the value cannot be mapped.
    #[inline]
    fn try_from(e: PAErr) -> Result<Self, Self::Error> {
        // Error codes are negative, `Code` enum variants are positive
        let abs = -(e.0);
        Code::from_i32(abs).ok_or(())
    }
}

/// Check `PAErr` <=> `Code` conversions
#[test]
fn check_code_paerr_conversions() {
    assert_eq!(Ok(Code::Ok),                   Code::try_from(PAErr(0)));
    assert_eq!(Ok(Code::Access),               Code::try_from(PAErr(-1)));
    assert_eq!(Ok(Code::Command),              Code::try_from(PAErr(-2)));
    assert_eq!(Ok(Code::Invalid),              Code::try_from(PAErr(-3)));
    assert_eq!(Ok(Code::Exist),                Code::try_from(PAErr(-4)));
    assert_eq!(Ok(Code::NoEntity),             Code::try_from(PAErr(-5)));
    assert_eq!(Ok(Code::ConnectionRefused),    Code::try_from(PAErr(-6)));
    assert_eq!(Ok(Code::Protocol),             Code::try_from(PAErr(-7)));
    assert_eq!(Ok(Code::Timeout),              Code::try_from(PAErr(-8)));
    assert_eq!(Ok(Code::AuthKey),              Code::try_from(PAErr(-9)));
    assert_eq!(Ok(Code::Internal),             Code::try_from(PAErr(-10)));
    assert_eq!(Ok(Code::ConnectionTerminated), Code::try_from(PAErr(-11)));
    assert_eq!(Ok(Code::Killed),               Code::try_from(PAErr(-12)));
    assert_eq!(Ok(Code::InvalidServer),        Code::try_from(PAErr(-13)));
    assert_eq!(Ok(Code::ModInitFailed),        Code::try_from(PAErr(-14)));
    assert_eq!(Ok(Code::BadState),             Code::try_from(PAErr(-15)));
    assert_eq!(Ok(Code::NoData),               Code::try_from(PAErr(-16)));
    assert_eq!(Ok(Code::Version),              Code::try_from(PAErr(-17)));
    assert_eq!(Ok(Code::TooLarge),             Code::try_from(PAErr(-18)));
    assert_eq!(Ok(Code::NotSupported),         Code::try_from(PAErr(-19)));
    assert_eq!(Ok(Code::Unknown),              Code::try_from(PAErr(-20)));
    assert_eq!(Ok(Code::NoExtension),          Code::try_from(PAErr(-21)));
    assert_eq!(Ok(Code::Obsolete),             Code::try_from(PAErr(-22)));
    assert_eq!(Ok(Code::NotImplemented),       Code::try_from(PAErr(-23)));
    assert_eq!(Ok(Code::Forked),               Code::try_from(PAErr(-24)));
    assert_eq!(Ok(Code::IO),                   Code::try_from(PAErr(-25)));
    assert_eq!(Ok(Code::Busy),                 Code::try_from(PAErr(-26)));
    assert_eq!(Err(()),                        Code::try_from(PAErr(-27)));
    assert_eq!(Err(()),                        Code::try_from(PAErr(1)));

    assert_eq!(PAErr::from(Code::Ok),                   PAErr(0));
    assert_eq!(PAErr::from(Code::Access),               PAErr(-1));
    assert_eq!(PAErr::from(Code::Command),              PAErr(-2));
    assert_eq!(PAErr::from(Code::Invalid),              PAErr(-3));
    assert_eq!(PAErr::from(Code::Exist),                PAErr(-4));
    assert_eq!(PAErr::from(Code::NoEntity),             PAErr(-5));
    assert_eq!(PAErr::from(Code::ConnectionRefused),    PAErr(-6));
    assert_eq!(PAErr::from(Code::Protocol),             PAErr(-7));
    assert_eq!(PAErr::from(Code::Timeout),              PAErr(-8));
    assert_eq!(PAErr::from(Code::AuthKey),              PAErr(-9));
    assert_eq!(PAErr::from(Code::Internal),             PAErr(-10));
    assert_eq!(PAErr::from(Code::ConnectionTerminated), PAErr(-11));
    assert_eq!(PAErr::from(Code::Killed),               PAErr(-12));
    assert_eq!(PAErr::from(Code::InvalidServer),        PAErr(-13));
    assert_eq!(PAErr::from(Code::ModInitFailed),        PAErr(-14));
    assert_eq!(PAErr::from(Code::BadState),             PAErr(-15));
    assert_eq!(PAErr::from(Code::NoData),               PAErr(-16));
    assert_eq!(PAErr::from(Code::Version),              PAErr(-17));
    assert_eq!(PAErr::from(Code::TooLarge),             PAErr(-18));
    assert_eq!(PAErr::from(Code::NotSupported),         PAErr(-19));
    assert_eq!(PAErr::from(Code::Unknown),              PAErr(-20));
    assert_eq!(PAErr::from(Code::NoExtension),          PAErr(-21));
    assert_eq!(PAErr::from(Code::Obsolete),             PAErr(-22));
    assert_eq!(PAErr::from(Code::NotImplemented),       PAErr(-23));
    assert_eq!(PAErr::from(Code::Forked),               PAErr(-24));
    assert_eq!(PAErr::from(Code::IO),                   PAErr(-25));
    assert_eq!(PAErr::from(Code::Busy),                 PAErr(-26));
}
