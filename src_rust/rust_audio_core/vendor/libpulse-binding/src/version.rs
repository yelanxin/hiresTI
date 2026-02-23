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

//! Version related constants and functions.
//!
//! This module contains functions and constants relating to the version of the PulseAudio (PA)
//! client system library.
//!
//! # Dynamic compatibility
//!
//! As discussed in the project `COMPATIBILITY.md` file, compatibility is offered for multiple
//! versions of the PA client system library, with feature flags adapting the crate to changes made
//! in the API of newer PA versions.
//!
//! Note that the minimum supported version of PA is v5.0.
//!
//! # Runtime checking
//!
//! The following functions are provided to retrieve and compare the version of the actual PA client
//! system library in use at runtime:
//!
//!  - The [`get_library_version()`] function obtains the version string the system library
//!    provides.
//!  - The [`get_library_version_numbers()`] function uses the previous function and attempts to
//!    parse the version string it returns into numeric form for comparison purposes.
//!  - The [`compare_with_library_version()`] function uses the previous function and allows
//!    comparing a provided major and minor version number with what it returned.
//!  - The [`library_version_is_too_old()`] function uses the previous function to compare against
//!    the [`TARGET_VERSION`] constant version numbers. This constant varies depending upon PA
//!    version feature flags, and thus this can be used to check that a program is not being run on
//!    a system with too old of a version of PA, helping combat the “forward” compatibility problem
//!    discussed in the project `COMPATIBILITY.md` documentation.
//!
//! # Dynamic constants
//!
//! The version constants defined here mostly relate to those provided in the PA C headers, and are
//! likely of little use to most projects. They are set dynamically, depending upon the feature
//! flags used, or in other words the level of minimum compatibility support selected. Note that PA
//! version feature flags are only introduced when new versions of PA introduce changes to its API
//! that would require one. The version numbers associated with each PA version feature flag are
//! those from the PA version that required introduction of that feature flag.
//!
//! As an example to clarify, if the “newest” PA version feature flag enabled is `pa_v8` (which
//! obviously corresponds to a minimum compatibility level of PA version 8.0), then the
//! [`TARGET_VERSION`] constant is set to `(8, 0)`. The “next-newest” feature flag is `pa_v11`,
//! which if enabled would bump it up to `(11, 0)`.

use capi;
use std::borrow::Cow;
use std::cmp::Ordering;
use std::ffi::CStr;

// Re-export from sys
pub use capi::version::{Compatibility, get_compatibility};
pub use capi::version::{TARGET_VERSION_STRING, TARGET_VERSION};
pub use capi::version::{PA_API_VERSION as API_VERSION, PA_PROTOCOL_VERSION as PROTOCOL_VERSION};

/// Kinds of errors from trying to parse the runtime PulseAudio system library version string.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[non_exhaustive]
enum ErrorKind {
    /// Error parsing part as integer.
    ParseIntError,
    /// Missing version part.
    MissingPart,
    /// Too many parts found in the string (unexpected; something is wrong).
    ExtraParts,
}

/// Error from trying to parse the runtime PulseAudio system library version string.
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct Error {
    /// The problematic version sring which could not be parsed.
    ver_str: Cow<'static, str>,
}

impl Error {
    #[inline]
    fn new(ver_str: Cow<'static, str>) -> Self {
        Self { ver_str }
    }
}

impl std::error::Error for Error {}

impl std::fmt::Display for Error {
    #[inline]
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        format!("failed to parse PulseAudio system library version string '{}'", &self.ver_str)
            .fmt(f)
    }
}

/// Checks whether the version of the running system library is older than the version corresponding
/// to the compatibility level selected via the available feature flags.
///
/// Returns `Ok(true)` if the library version is older, `Ok(false)` if equal or newer, or `Err` if a
/// problem occurred processing the version string.
#[inline]
pub fn library_version_is_too_old() -> Result<bool, Error> {
    match compare_with_library_version(TARGET_VERSION.0, TARGET_VERSION.1)? {
        Ordering::Less | Ordering::Equal => Ok(false),
        Ordering::Greater => Ok(true),
    }
}

/// Compares the supplied version with that of the runtime system library.
///
/// Returns the comparison, or `Err` if a problem occurred parsing the library version string. The
/// comparison will represent `supplied.cmp(&library)`.
#[inline]
pub fn compare_with_library_version(major: u8, minor: u8) -> Result<std::cmp::Ordering, Error> {
    let (lib_major, lib_minor, _) = get_library_version_numbers()?;
    Ok((major).cmp(&lib_major).then_with(|| minor.cmp(&lib_minor)))
}

/// Tries to convert the runtime system library version to numeric major, minor and micro form, for
/// comparison purposes.
///
/// Note, currently micro is always zero. This is the case even in beta/rc versions (like 13.99.1)
/// due to the fact that the version string returned by PA always has micro fixed to zero.
///
/// Returns `Err` if parsing the version number string fails.
#[inline]
pub fn get_library_version_numbers() -> Result<(u8, u8, u8), Error> {
    let ver = get_library_version().to_string_lossy();
    pa_version_str_to_num(&ver).or_else(|_e| Err(Error::new(ver)))
}

/// Convert PulseAudio version string to major, minor and micro numbers.
///
/// The version number string should come from `pa_get_library_version()` and thus currently will
/// always consist of exactly `$MAJOR.$MINOR.0` per the compiled version.h header. Note that the
/// micro number is fixed to zero.
#[inline]
fn pa_version_str_to_num(ver: &str) -> Result<(u8, u8, u8), ErrorKind> {
    let mut parts = ver.split('.');
    let major: u8 =
        parts.next().ok_or(ErrorKind::MissingPart)?.parse().or(Err(ErrorKind::ParseIntError))?;
    let minor: u8 =
        parts.next().ok_or(ErrorKind::MissingPart)?.parse().or(Err(ErrorKind::ParseIntError))?;
    // Note, we want to be very strict about accepting only properly formatted values, as anything
    // otherwise suggests a wierd problem, thus we do parse the micro number even though it will
    // always be zero.
    let micro: u8 =
        parts.next().ok_or(ErrorKind::MissingPart)?.parse().or(Err(ErrorKind::ParseIntError))?;
    match parts.next().is_some() {
        true => Err(ErrorKind::ExtraParts), // Something isn’t right
        false => Ok((major, minor, micro)),
    }
}

/// Gets the version string of the (PulseAudio client system) library actually in use at runtime.
#[inline]
pub fn get_library_version() -> &'static CStr {
    unsafe { CStr::from_ptr(capi::pa_get_library_version()) }
}

#[test]
fn test_ver_str_to_num() {
    assert_eq!(pa_version_str_to_num(""),         Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num(" "),        Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("."),        Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("a"),        Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("a.a"),      Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("a.1"),      Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("14"),       Err(ErrorKind::MissingPart));
    assert_eq!(pa_version_str_to_num("14.0"),     Err(ErrorKind::MissingPart));
    assert_eq!(pa_version_str_to_num("14.0.0"),   Ok((14, 0, 0)));
    assert_eq!(pa_version_str_to_num("14.1.0"),   Ok((14, 1, 0)));
    assert_eq!(pa_version_str_to_num("14.2.0."),  Err(ErrorKind::ExtraParts));
    assert_eq!(pa_version_str_to_num("14.2.0.0"), Err(ErrorKind::ExtraParts));
    assert_eq!(pa_version_str_to_num("12.2a"),    Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("12.a"),     Err(ErrorKind::ParseIntError));
    assert_eq!(pa_version_str_to_num("12.a.1"),   Err(ErrorKind::ParseIntError));
}

#[test]
fn test_getting_pa_version() {
    let actual_ver_str =
        unsafe { CStr::from_ptr(capi::pa_get_library_version()).to_string_lossy() };
    let (major, minor, micro) = get_library_version_numbers().unwrap();
    assert_eq!(format!("{}.{}.{}", major, minor, micro), actual_ver_str);
}

#[test]
fn test_comparing_pa_version() {
    let (major, minor, _micro) = get_library_version_numbers().unwrap();
    assert_eq!(compare_with_library_version(major, minor).unwrap(), Ordering::Equal);
    assert_eq!(compare_with_library_version(major + 1, minor).unwrap(), Ordering::Greater);
    assert_eq!(compare_with_library_version(major - 1, minor).unwrap(), Ordering::Less);
    assert_eq!(compare_with_library_version(major, minor + 1).unwrap(), Ordering::Greater);
    assert_eq!(compare_with_library_version(major - 1, minor + 1).unwrap(), Ordering::Less);
    if minor > 0 {
        assert_eq!(compare_with_library_version(major, minor - 1).unwrap(), Ordering::Less);
        assert_eq!(compare_with_library_version(major + 1, minor - 1).unwrap(), Ordering::Greater);
    }
}

#[test]
fn test_lib_ver_not_too_old() {
    assert_eq!(library_version_is_too_old(), Ok(false));
}
