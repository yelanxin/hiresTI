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

//! Memory allocation functions.

use std::os::raw::{c_char, c_void};

/// Allocates `n` new structures of the specified type.
#[inline(always)]
pub unsafe fn pa_xnew(n: usize, k: usize) -> *mut c_void {
    assert!(n < (std::i32::MAX as usize / k));
    pa_xmalloc(n * k)
}

/// Same as [`pa_xnew()`] but sets the memory to zero.
#[inline(always)]
pub unsafe fn pa_xnew0(n: usize, k: usize) -> *mut c_void {
    assert!(n < (std::i32::MAX as usize / k));
    pa_xmalloc0(n * k)
}

/// Same as [`pa_xnew()`] but duplicates the specified data.
#[inline(always)]
pub unsafe fn pa_xnewdup(p: *const c_void, n: usize, k: usize) -> *mut c_void {
    assert!(n < (std::i32::MAX as usize / k));
    pa_xmemdup(p, n * k)
}

/// Reallocates `n` new structures of the specified type.
#[inline(always)]
pub unsafe fn pa_xrenew(p: *mut c_void, n: usize, k: usize) -> *mut c_void {
    assert!(n < (std::i32::MAX as usize / k));
    pa_xrealloc(p, n * k)
}

#[link(name = "pulse")]
extern "C" {
    /// Allocates the specified number of bytes, just like `malloc()` does.
    /// However, in case of OOM, terminate.
    pub fn pa_xmalloc(l: usize) -> *mut c_void;

    /// Same as [`pa_xmalloc()`] , but initializes allocated memory to 0.
    pub fn pa_xmalloc0(l: usize) -> *mut c_void;

    ///  The combination of [`pa_xmalloc()`] and `realloc()`.
    pub fn pa_xrealloc(ptr: *mut c_void, size: usize) -> *mut c_void;

    /// Frees allocated memory.
    pub fn pa_xfree(p: *mut c_void);

    /// Duplicates the specified string, allocating memory with [`pa_xmalloc()`].
    pub fn pa_xstrdup(s: *const c_char) -> *mut c_char;

    /// Duplicates the specified string, but truncate after `l` characters.
    pub fn pa_xstrndup(s: *const c_char, l: usize) -> *mut c_char;

    /// Duplicates the specified memory block.
    pub fn pa_xmemdup(p: *const c_void, l: usize) -> *mut c_void;
}
