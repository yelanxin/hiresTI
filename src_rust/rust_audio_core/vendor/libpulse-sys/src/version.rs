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

//! Version constants and functions.
//!
//! This module contains functions and constants relating to PulseAudio (PA) client API version
//! compatibility.
//!
//! # Dynamic compatibility
//!
//! As discussed in the project `COMPATIBILITY.md` file, support is offered for multiple versions of
//! the PA client library, with changes made in newer versions being guarded with Cargo feature
//! flags.
//!
//! Note that the minimum supported version of PA is v5.0.
//!
//! # Dynamic constants
//!
//! The version constants defined here mostly relate to those provided in the PA C headers. They are
//! typically only updated following a new **major** release of PA. They are also dynamic, depending
//! upon the level of compatibility support selected at compile time via the available Cargo feature
//! flags.
//!
//! Note that there is **not** a one-to-one mapping of major PA version to compatibility feature. A
//! new such feature is only introduced where actual changes in the PA client API require one
//! because they introduce changes such as the addition of new functions.
//!
//! It is not obvious how the constants relate to version compatibility levels without reading the
//! code, so this needs explaining. Simply put, version numbers are updated typically only on
//! release of a new major version of PA, and update the existing version number associated with the
//! current latest compatibility level selector when there are no changes requiring a new
//! compatibility feature.
//!
//! Thus, for instance, PA versions 8 and 12 introduced additions to the API and have corresponding
//! compatibility features to control the inclusion of those additions on top of the minimum level
//! of support offered. If you have v8 compatibility enabled but not v12, then the version number
//! indicated will be v11.

use std::os::raw::c_char;

/// PulseAudio version compatibility.
///
/// Used for indicating what level of PA version compatibility was selected at compile time via
/// Cargo feature flags.
///
/// Note that PA v4 is the oldest supported.
#[non_exhaustive]
pub enum Compatibility {
    /// Support for PA version 5+ selected.
    V5Plus,
    /// Support for PA version 6+ selected.
    V6Plus,
    /// Support for PA version 8+ selected.
    V8Plus,
    /// Support for PA version 12+ selected.
    V12Plus,
    /// Support for PA version 13+ selected.
    V13Plus,
    /// Support for PA version 14+ selected.
    V14Plus,
    /// Support for PA version 15+ selected.
    V15Plus,
}

// Latest
#[cfg(any(feature = "pa_v15", all(doc, not(feature = "pa_v6"))))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V15Plus;
    pub const TARGET_VERSION_STRING: &str = "15.0.0";
    pub const TARGET_VERSION: (u8, u8) = (15, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 35;
}

// Pre-v15
#[cfg(all(feature = "pa_v14", not(feature = "pa_v15")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V14Plus;
    pub const TARGET_VERSION_STRING: &str = "14.0.0";
    pub const TARGET_VERSION: (u8, u8) = (14, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 34;
}

// Pre-v14
#[cfg(all(feature = "pa_v13", not(feature = "pa_v14")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V13Plus;
    pub const TARGET_VERSION_STRING: &str = "13.0.0";
    pub const TARGET_VERSION: (u8, u8) = (13, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 33;
}

// Pre-v13
#[cfg(all(feature = "pa_v12", not(feature = "pa_v13")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V12Plus;
    pub const TARGET_VERSION_STRING: &str = "12.0.0";
    pub const TARGET_VERSION: (u8, u8) = (12, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 32;
}

// Pre-v12
#[cfg(all(feature = "pa_v8", not(feature = "pa_v12")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V8Plus;
    pub const TARGET_VERSION_STRING: &str = "8.0.0";
    pub const TARGET_VERSION: (u8, u8) = (8, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 30;
}

// Pre-v8
#[cfg(all(feature = "pa_v6", not(feature = "pa_v8")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V6Plus;
    pub const TARGET_VERSION_STRING: &str = "6.0.0";
    pub const TARGET_VERSION: (u8, u8) = (6, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 30;
}

// Pre-v6
#[cfg(all(not(doc), not(feature = "pa_v6")))]
mod actual {
    pub const COMPATIBILITY: super::Compatibility = super::Compatibility::V5Plus;
    pub const TARGET_VERSION_STRING: &str = "5.0.0";
    pub const TARGET_VERSION: (u8, u8) = (5, 0);
    pub const PA_PROTOCOL_VERSION: u16 = 29;
}

/// Version string of targetted version.
///
/// See the module level documentation for an explanation.
pub const TARGET_VERSION_STRING: &str = actual::TARGET_VERSION_STRING;

/// Version number of targetted version.
///
/// See the module level documentation for an explanation.
pub const TARGET_VERSION: (u8, u8) = actual::TARGET_VERSION;

/// Protocol version of targetted version.
///
/// See the module level documentation for an explanation.
pub const PA_PROTOCOL_VERSION: u16 = actual::PA_PROTOCOL_VERSION;

/// The current API version.
///
/// Note, this has not been updated since PA v0.9.11. It is presumed that it would only ever be
/// updated for backwards-breaking API changes.
pub const PA_API_VERSION: u8 = 12;

/// Get selected compatibility level.
///
/// Returns indication of the level of PulseAudio version compatibility selected at compile time via
/// Cargo feature flags.
#[inline(always)]
pub const fn get_compatibility() -> Compatibility {
    actual::COMPATIBILITY
}

#[link(name = "pulse")]
extern "C" {
    pub fn pa_get_library_version() -> *const c_char;
}
