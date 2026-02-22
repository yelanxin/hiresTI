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

//! Error management.

use std::os::raw::c_char;
use num_derive::{FromPrimitive, ToPrimitive};

/// Error code.
///
/// These represent the i32 error codes returned by many of the underlying PulseAudio C functions.
/// Beware, these enum values are positive values, whilst PA functions return them in negative form,
/// i.e. the `Invalid` variant here has a value of `3`, while functions returning this error code
/// return `-3`. (This is identical to the enum provided in the PA C API).
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
#[allow(non_camel_case_types)]
pub enum pa_error_code_t {
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
    Timeout,
    /// No authentication key.
    AuthKey,
    Internal,
    ConnectionTerminated,
    /// Entity killed.
    Killed,
    InvalidServer,
    ModInitFailed,
    BadState,
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

pub const PA_ERR_MAX: usize = 27;

pub const PA_OK:                       pa_error_code_t = pa_error_code_t::Ok;
pub const PA_ERR_ACCESS:               pa_error_code_t = pa_error_code_t::Access;
pub const PA_ERR_COMMAND:              pa_error_code_t = pa_error_code_t::Command;
pub const PA_ERR_INVALID:              pa_error_code_t = pa_error_code_t::Invalid;
pub const PA_ERR_EXIST:                pa_error_code_t = pa_error_code_t::Exist;
pub const PA_ERR_NOENTITY:             pa_error_code_t = pa_error_code_t::NoEntity;
pub const PA_ERR_CONNECTIONREFUSED:    pa_error_code_t = pa_error_code_t::ConnectionRefused;
pub const PA_ERR_PROTOCOL:             pa_error_code_t = pa_error_code_t::Protocol;
pub const PA_ERR_TIMEOUT:              pa_error_code_t = pa_error_code_t::Timeout;
pub const PA_ERR_AUTHKEY:              pa_error_code_t = pa_error_code_t::AuthKey;
pub const PA_ERR_INTERNAL:             pa_error_code_t = pa_error_code_t::Internal;
pub const PA_ERR_CONNECTIONTERMINATED: pa_error_code_t = pa_error_code_t::ConnectionTerminated;
pub const PA_ERR_KILLED:               pa_error_code_t = pa_error_code_t::Killed;
pub const PA_ERR_INVALIDSERVER:        pa_error_code_t = pa_error_code_t::InvalidServer;
pub const PA_ERR_MODINITFAILED:        pa_error_code_t = pa_error_code_t::ModInitFailed;
pub const PA_ERR_BADSTATE:             pa_error_code_t = pa_error_code_t::BadState;
pub const PA_ERR_NODATA:               pa_error_code_t = pa_error_code_t::NoData;
pub const PA_ERR_VERSION:              pa_error_code_t = pa_error_code_t::Version;
pub const PA_ERR_TOOLARGE:             pa_error_code_t = pa_error_code_t::TooLarge;
pub const PA_ERR_NOTSUPPORTED:         pa_error_code_t = pa_error_code_t::NotSupported;
pub const PA_ERR_UNKNOWN:              pa_error_code_t = pa_error_code_t::Unknown;
pub const PA_ERR_NOEXTENSION:          pa_error_code_t = pa_error_code_t::NoExtension;
pub const PA_ERR_OBSOLETE:             pa_error_code_t = pa_error_code_t::Obsolete;
pub const PA_ERR_NOTIMPLEMENTED:       pa_error_code_t = pa_error_code_t::NotImplemented;
pub const PA_ERR_FORKED:               pa_error_code_t = pa_error_code_t::Forked;
pub const PA_ERR_IO:                   pa_error_code_t = pa_error_code_t::IO;
pub const PA_ERR_BUSY:                 pa_error_code_t = pa_error_code_t::Busy;

#[link(name = "pulse")]
extern "C" {
    pub fn pa_strerror(error: i32) -> *const c_char;
}
