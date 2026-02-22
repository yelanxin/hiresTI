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

//! Time handling functionality.

mod convert; //private!
mod microseconds;
mod monotonic;
mod timeval;
mod unix;

use std::time::Duration;

pub use self::microseconds::*;
pub use self::monotonic::*;
pub use self::timeval::*;
pub use self::unix::*;

// (Copied constants from rust’s std/time/duration.rs)
/// Nanoseconds per second.
pub const NANOS_PER_SEC:    u32 = 1_000_000_000;
/// Nanoseconds per millisecond.
pub const NANOS_PER_MILLI:  u32 = 1_000_000;
/// Nanoseconds per microsecond.
pub const NANOS_PER_MICRO:  u32 = 1_000;
/// Microseconds per second.
pub const MICROS_PER_SEC:   u64 = 1_000_000;
/// Microseconds per millisecond.
pub const MICROS_PER_MILLI: u64 = 1_000;
/// Milliseconds per second.
pub const MILLIS_PER_SEC:   u64 = 1_000;

/// Basic math operation errors.
mod op_err {
    pub const ADD: &str = "attempt to add with overflow";
    pub const SUB: &str = "attempt to subtract with overflow";
    pub const MUL: &str = "attempt to multiply with overflow";
    pub const DIV: &str = "attempt to divide by zero";
    pub const REM: &str = DIV;
}
